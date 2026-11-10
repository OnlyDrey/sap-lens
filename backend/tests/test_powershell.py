"""PowerShell 7 validation on Linux/macOS (skipped where `pwsh` is absent). Verifies parsing, parameter binding, argument forwarding, paths with spaces, exit-code
propagation and the read-only/safe-repair guarantees of the prerequisites mode. It does NOT verify Windows PowerShell 5.1, Windows APIs or native Windows paths."""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PWSH = shutil.which('pwsh')
HELPERS = r'''
$ErrorActionPreference = 'Stop'
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:SCRIPT_UNDER_TEST, [ref]$null, [ref]$null)
foreach ($f in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $false)) { . ([scriptblock]::Create($f.Extent.Text)) }
'''


def pwsh(command, env=None, cwd=None, timeout=120):
    return subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-Command', command], capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, **(env or {})}, cwd=cwd, stdin=subprocess.DEVNULL)


def fake_python(folder, version, bits=64, exit_code=0):
    path = Path(folder) / 'python'
    path.write_text(f'#!/bin/sh\nif [ {exit_code} -ne 0 ]; then exit {exit_code}; fi\necho "$0"\necho {version}\necho {bits}\n')
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


@unittest.skipUnless(PWSH, 'PowerShell 7 (pwsh) is not installed')
class ScriptsParse(unittest.TestCase):
    def test_every_script_parses_under_powershell_7_and_static_guards_pass(self):
        done = subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-File', str(ROOT / 'scripts/check-powershell.ps1')], capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn('scripts/build.ps1 syntax and static guards passed', done.stdout)

    def test_all_ps1_files_parse_without_errors(self):
        script = r'''$bad = foreach ($file in Get-ChildItem -Recurse -Filter *.ps1 scripts, deploy) {
            $e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$null, [ref]$e); if ($e.Count) { "$($file.Name): $($e[0].Message)" } }
        if ($bad) { $bad; exit 1 }'''
        done = pwsh(script, cwd=ROOT)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


BAD = {
    'PS7-Ternary': '$a = $true ? 1 : 2', 'PS7-PipelineChain': 'Get-Item . && Get-Item .', 'PS7-NullCoalescing': '$a = $null ?? 1',
    'PS7-NullCoalescingAssign': '$a ??= 1', 'PS7-NullConditional': '(Get-Item .)?.Name', 'PS7-Variable': 'if ($IsWindows) { 1 }',
    'NetCore-Api': '[System.IO.Path]::GetRelativePath("a","b")', 'PS7-Parameter': '"{}" | ConvertFrom-Json -AsHashtable',
    'PS7-Encoding': '"x" | Set-Content t -Encoding utf8NoBOM', 'PS7-Cmdlet': 'Get-Error', 'PS7-Requires': '#requires -Version 7.0\nGet-Item .',
    'PS7-Parameter ': '1..3 | ForEach-Object -Parallel { $_ }'}


@unittest.skipUnless(PWSH, 'PowerShell 7 (pwsh) is not installed')
class Windows51StaticCompatibility(unittest.TestCase):
    """AST-based, runs on PowerShell 7. Proves the absence of known 7-only constructs; it does not prove Windows PowerShell 5.1 runs the scripts."""
    def check(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'sample.ps1'; path.write_text(text)
            done = subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-File', str(ROOT / 'scripts/check-powershell-compat.ps1'), str(path)], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        return done.returncode, done.stdout

    def test_repository_scripts_have_no_powershell_7_only_constructs(self):
        done = subprocess.run([PWSH, '-NoProfile', '-NonInteractive', '-File', str(ROOT / 'scripts/check-powershell-compat.ps1')], capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr); self.assertIn('0 errors', done.stdout); self.assertIn('static analysis only', done.stdout)

    def test_each_seven_only_construct_is_detected(self):
        for rule, code in BAD.items():
            returncode, output = self.check(code + '\n')
            self.assertEqual(returncode, 1, (rule, output)); self.assertIn(rule.strip(), output, output)

    def test_portable_code_passes_and_warnings_do_not_fail(self):
        good = "$ErrorActionPreference = 'Stop'\nif ($env:OS -eq 'Windows_NT') { $x = 1 } else { $x = 2 }\n'a' | Set-Content t.txt\n$y = [System.IO.Path]::Combine('a','b')\n& cmd.exe /c exit 0 2>$null\n"
        returncode, output = self.check(good)
        self.assertEqual(returncode, 0, output); self.assertIn('Encoding-Default', output); self.assertNotIn('Redirect-Encoding', output)

    def test_syntax_errors_fail(self):
        self.assertEqual(self.check('if ($x {\n')[0], 1)


@unittest.skipUnless(PWSH, 'PowerShell 7 (pwsh) is not installed')
class BuildBootstrapper(unittest.TestCase):
    def test_parameter_binding_exposes_the_documented_and_new_switches(self):
        done = pwsh("(Get-Command ./scripts/build.ps1).Parameters.Keys -join ','", cwd=ROOT)
        names = set(done.stdout.strip().split(','))
        for name in ('Mode', 'Platform', 'Target', 'Version', 'Scope', 'Output', 'Area', 'Setup', 'SetupOnly', 'SkipSetup', 'InstallSystem', 'NonInteractive', 'DryRun',
                     'ConfirmClean', 'CheckOnly', 'Repair', 'Json', 'NoCache', 'NativeAcceptance'):
            self.assertIn(name, names)

    def test_switch_parameters_are_typed_as_switches_and_mode_as_string(self):
        done = pwsh("$p=(Get-Command ./scripts/build.ps1).Parameters; 'CheckOnly','Repair','Json' | % { $p[$_].SwitchParameter }; $p['Mode'].ParameterType.Name", cwd=ROOT)
        self.assertEqual(done.stdout.split(), ['True', 'True', 'True', 'String'])

    def test_unknown_parameter_is_rejected_by_binding(self):
        done = subprocess.run([PWSH, '-NoProfile', '-File', str(ROOT / 'scripts/build.ps1'), '-NoSuchSwitch'], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        self.assertNotEqual(done.returncode, 0)

    def test_exit_code_of_the_windows_only_bootstrapper_propagates_on_linux(self):
        done = subprocess.run([PWSH, '-NoProfile', '-File', str(ROOT / 'scripts/build.ps1'), '-Mode', 'prerequisites', '-CheckOnly'], capture_output=True, text=True, timeout=60,
                              stdin=subprocess.DEVNULL, env={**os.environ, 'OS': 'Linux'})
        self.assertEqual(done.returncode, 2); self.assertIn('python3.12 scripts/build.py', done.stdout)

    def test_interpreter_probe_accepts_only_312_x64_and_handles_spaces(self):
        with tempfile.TemporaryDirectory(prefix='sap lens ') as tmp:
            folder = Path(tmp) / 'Program Files' / 'Python 312'; folder.mkdir(parents=True)
            cases = {('3.12.10', 64, 0): ('True', 'Compatible'), ('3.15.0', 64, 0): ('False', '3.12 is required'), ('3.12.10', 32, 0): ('False', '64-bit'),
                     ('3.12.10', 64, 3): ('False', 'probe')}
            for (version, bits, code), (compatible, text) in cases.items():
                python = fake_python(folder, version, bits, code)
                done = pwsh(HELPERS + f"$r = Test-PythonCandidate -Source t -Path '{python}'; \"$($r.Compatible)|$($r.Result)|$($r.Executable)\"", env={'SCRIPT_UNDER_TEST': str(ROOT / 'scripts/build.ps1')})
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                flag, result, executable = done.stdout.strip().split('|')
                self.assertEqual(flag, compatible, (version, bits, code, result)); self.assertIn(text, result)
                if compatible == 'True':
                    self.assertEqual(executable, str(python))     # the spaces in the interpreter path survive

    def test_repository_root_is_resolved_from_the_script_location_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix='sap lens ') as tmp:
            (Path(tmp) / 'scripts').mkdir(); (Path(tmp) / 'scripts/build.py').write_text('')
            done = pwsh(HELPERS + f"Get-RepositoryRoot -ScriptDirectory '{Path(tmp) / 'scripts'}'", env={'SCRIPT_UNDER_TEST': str(ROOT / 'scripts/build.ps1')})
            self.assertEqual(done.stdout.strip(), tmp)
            done = pwsh(HELPERS + f"'[' + (Get-RepositoryRoot -ScriptDirectory '{Path(tmp)}') + ']'", env={'SCRIPT_UNDER_TEST': str(ROOT / 'scripts/build.ps1')})
            self.assertEqual(done.stdout.strip(), '[]')          # no build.py next to it: never the working directory


@unittest.skipUnless(PWSH, 'PowerShell 7 (pwsh) is not installed')
class PrerequisitesThroughPowerShell(unittest.TestCase):
    def checkout(self, tmp):
        root = Path(tmp) / 'Sap Lens checkout'
        shutil.copytree(ROOT / 'scripts', root / 'scripts', ignore=shutil.ignore_patterns('__pycache__', 'benchmarks'))
        (root / 'backend').mkdir(); (root / 'frontend').mkdir()
        for name in ROOT.joinpath('backend').glob('requirements*.txt'):
            shutil.copy(name, root / 'backend' / name.name)
        shutil.copy(ROOT / 'frontend/package.json', root / 'frontend/package.json')
        return root

    def snapshot(self, root):
        return sorted(str(p.relative_to(root)) for p in root.rglob('*') if '__pycache__' not in p.parts)

    def run_engine(self, root, *args):
        command = f"& '{sys.executable}' '{root / 'scripts/build.py'}' {' '.join(args)}; exit $LASTEXITCODE"
        return pwsh(command, cwd=root)

    def test_check_only_through_powershell_is_read_only_and_reports_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.checkout(tmp); before = self.snapshot(root)
            done = self.run_engine(root, 'prerequisites', '--check-only', '--json')
            report = json.loads(done.stdout)
            self.assertEqual(done.returncode, report['exit_code']); self.assertIn(done.returncode, (0, 3))
            self.assertEqual(before, self.snapshot(root))
            names = {row['name']: row for row in report['items']}
            self.assertEqual(names['Project .venv']['status'], 'Missing')               # a fresh checkout: reported, not created

    def test_broken_environment_is_left_alone_without_repair_and_exit_code_is_3(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.checkout(tmp)
            (root / '.venv/bin').mkdir(parents=True); marker = root / '.venv/bin/keep.txt'; marker.write_text('mine')   # no pyvenv.cfg, no interpreter
            before = self.snapshot(root)
            done = self.run_engine(root, 'prerequisites', '--non-interactive')
            self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
            self.assertIn('--repair', done.stderr + done.stdout); self.assertEqual(before, self.snapshot(root)); self.assertEqual(marker.read_text(), 'mine')

    def test_incompatible_flags_are_rejected_with_a_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.checkout(tmp)
            self.assertNotEqual(self.run_engine(root, 'prerequisites', '--check-only', '--repair').returncode, 0)
            self.assertNotEqual(self.run_engine(root, 'build', '--check-only').returncode, 0)

    def test_native_command_failure_is_visible_to_powershell(self):
        done = pwsh(f"& '{sys.executable}' -c 'import sys; sys.exit(7)'; exit $LASTEXITCODE")
        self.assertEqual(done.returncode, 7)

    def test_a_hung_child_is_bounded_by_a_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            sleeper = Path(tmp) / 'sleeper.py'; sleeper.write_text('import time\ntime.sleep(30)\n')
            done = pwsh(f"$p = Start-Process -FilePath '{sys.executable}' -ArgumentList '{sleeper}' -PassThru; "
                        "if (-not $p.WaitForExit(1500)) { $p.Kill(); 'timeout'; exit 124 }")
        self.assertEqual(done.returncode, 124); self.assertIn('timeout', done.stdout)


if __name__ == '__main__':
    unittest.main()
