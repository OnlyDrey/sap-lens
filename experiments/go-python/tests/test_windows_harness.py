"""Static and logic checks of the Windows harness on any platform with PowerShell (pwsh). Windows execution itself is NOT covered here."""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / 'windows'
SCRIPTS = sorted(WINDOWS.glob('*.ps1'))
PWSH = shutil.which('pwsh')

# Anything that could change policy, security settings, services, registry or installations. The harness must stay read-mostly and isolated.
FORBIDDEN = [r'Set-ExecutionPolicy', r'-ExecutionPolicy\s+Bypass', r'Set-MpPreference', r'Add-MpPreference', r'Remove-MpPreference', r'CiTool(\.exe)?["\']?\s+--(update|remove|set|enable|disable)',
             r'\bbcdedit\b', r'\breg(\.exe)?\s+(add|delete|import)\b', r'New-Service', r'Set-Service', r'Stop-Service', r'Start-Service', r'\bsc(\.exe)?\s+(create|config|delete|stop)\b',
             r'Set-ItemProperty\s+[^\n]*HK(LM|CU)', r'New-ItemProperty', r'Remove-ItemProperty', r'HKLM:', r'HKCU:', r'Invoke-Expression', r'\biex\b', r'Add-AppxPackage',
             r'msiexec', r'RunAs', r'netsh', r'Disable-', r'Unblock-File', r'Add-Type\s+-TypeDefinition', r'DownloadString', r'DownloadFile', r'Invoke-WebRequest\s+[^\n]*https?://[^l]']


def code_of(path):
    """Script text without block comments (help) and line comments."""
    text = re.sub(r'<#.*?#>', '', Path(path).read_text(encoding='utf-8'), flags=re.DOTALL)
    return '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('#'))


class Static(unittest.TestCase):
    def test_scripts_exist(self):
        self.assertEqual({p.name for p in SCRIPTS}, {'Phase1Common.ps1', 'Test-Phase1Logic.ps1', 'Test-WindowsFeasibility.ps1', 'Get-AppControlDiagnostics.ps1', 'Run-Phase1.ps1'})

    def test_no_forbidden_operations(self):
        for script in SCRIPTS:
            text = '\n'.join(line for line in script.read_text(encoding='utf-8').splitlines() if not line.lstrip().startswith('#'))
            for pattern in FORBIDDEN:
                self.assertIsNone(re.search(pattern, text, re.IGNORECASE), f'{script.name}: {pattern}')

    def test_no_non_ascii_and_no_em_dash(self):
        for script in SCRIPTS:
            data = script.read_bytes()
            self.assertNotIn(b'\xe2\x80\x94', data, script.name)
            data.decode('ascii')  # Windows PowerShell 5.1 reads BOM-less files as ANSI; stay ASCII

    def test_only_isolated_writes(self):
        text = (WINDOWS / 'Test-WindowsFeasibility.ps1').read_text()
        self.assertIn("'SAP Lens'", text)  # refuses inputs inside an SAP Lens installation or data directory
        self.assertIn("Contains('saplens-poc-')", text)  # cleanup only ever removes its own temp identity folder

    def test_runner_safety_properties(self):
        text = (WINDOWS / 'Run-Phase1.ps1').read_text()
        code = '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('#'))
        self.assertIn('[Parameter(Mandatory = $true)][ValidatePattern', code)  # trusted checksum is mandatory and validated
        self.assertIn('TrustedSumsSha256', code)
        for forbidden in ('Remove-Item', 'rmdir', 'Stop-Process', 'Set-ExecutionPolicy', 'Unblock-File', 'LanguageMode =', 'LanguageMode='):
            self.assertNotIn(forbidden, code, forbidden)  # the runner never deletes, never stops processes itself and never changes modes or policy
        self.assertIn("'System32\\tar.exe'", code)  # absolute system tar, never resolved through PATH or the working directory on Windows
        self.assertIn('Local\\SAPLensPhase1Runner', code)  # no overlapping runs
        self.assertIn('AllowElevated', code)
        self.assertIn('Test-ArchiveMembers', code)  # archive members are validated before extraction
        self.assertIn('Test-BundleSums', code)

    def test_process_cleanup_never_matches_by_name(self):
        text = (WINDOWS / 'Test-WindowsFeasibility.ps1').read_text() + (WINDOWS / 'Phase1Common.ps1').read_text()
        self.assertNotIn('Get-Process -Name', text)
        self.assertNotIn('taskkill', text.lower())
        self.assertNotIn('Stop-Process -Name', text)
        self.assertEqual(len(re.findall(r'Stop-Process', text)), 2)  # exactly two call sites: Stop-OwnedLeftovers (harness) and the timeout path of Invoke-Native; both select by recorded ownership

    def test_runner_runs_bundle_scripts_in_process_not_in_noninteractive_children(self):
        """Root cause of the first Windows run: a -NonInteractive child cannot answer PowerShell's prompt for a script with a Mark-of-the-Web."""
        code = code_of(WINDOWS / 'Run-Phase1.ps1')
        self.assertNotIn('-NonInteractive', code.replace("GetCommandLineArgs() -contains '-NonInteractive'", ''))  # only the read-only check that the session is interactive
        self.assertNotIn("'-File'", code)
        self.assertEqual(len(re.findall(r'Invoke-PhaseScript \(Join-Path \$scripts', code)), 3)  # self-test, harness, diagnostics
        for name in ('Test-WindowsFeasibility.ps1', 'Get-AppControlDiagnostics.ps1', 'Test-Phase1Logic.ps1'):
            text = (WINDOWS / name).read_text()
            self.assertIn("if (-not (Get-Command Get-OverallVerdict -ErrorAction SilentlyContinue)) { . (Join-Path $PSScriptRoot 'Phase1Common.ps1') }", text, name)  # no second authorization prompt

    def test_nothing_unblocks_or_alters_the_mark_of_the_web(self):
        for script in SCRIPTS:
            code = code_of(script)
            for match in re.finditer(r'[^\n]*-Stream[^\n]*', code):
                self.assertRegex(match.group(0), r'Get-(Item|Content)', f'{script.name}: only reads of alternate data streams are allowed: {match.group(0).strip()}')
            for pattern in (r'Unblock-File', r'Clear-Content', r'Set-ExecutionPolicy', r'(?<=\s)-ExecutionPolicy', r'SessionState\.LanguageMode\s*=(?!=)', r'Add-Type'):
                self.assertIsNone(re.search(pattern, code), f'{script.name}: {pattern}')
            if script.name == 'Run-Phase1.ps1':
                self.assertNotIn('Remove-Item', code)

    def test_wrong_capability_check_uses_the_real_header(self):
        text = (WINDOWS / 'Test-WindowsFeasibility.ps1').read_text()
        self.assertIn("'X-SAP-Lens'", text)
        self.assertNotIn('X-SAP-Lens-Session', text)


@unittest.skipUnless(PWSH, 'pwsh not available')
class Powershell(unittest.TestCase):
    def test_parse(self):
        for script in SCRIPTS:
            command = f"$e=$null;[void][System.Management.Automation.Language.Parser]::ParseFile('{script}',[ref]$null,[ref]$e);exit $e.Count"
            self.assertEqual(subprocess.run([PWSH, '-NoProfile', '-Command', command], capture_output=True, timeout=60).returncode, 0, script.name)

    def test_logic_self_test(self):
        result = subprocess.run([PWSH, '-NoProfile', '-File', str(WINDOWS / 'Test-Phase1Logic.ps1')], capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout[-800:])

    def test_bundle_scripts_run_in_process_with_raw_exit_codes_and_scoped_helpers(self):
        """The runner's R04 to R06 mechanics on Linux: the real scripts run through Invoke-PhaseScript in one session that loaded the helpers once."""
        with tempfile.TemporaryDirectory() as tmp:
            command = f'''
. '{WINDOWS}/Phase1Common.ps1'
$out = '{tmp}/evidence'; New-Item -ItemType Directory -Force $out | Out-Null
$before = $env:TEMP
$self = Invoke-PhaseScript '{WINDOWS}/Test-Phase1Logic.ps1' @{{}} @{{ TEMP = '{tmp}'; TMP = '{tmp}' }} "$out/self.txt" "$out/self.err" $false
$harness = Invoke-PhaseScript '{WINDOWS}/Test-WindowsFeasibility.ps1' @{{ HostExe = '/bin/true'; RuntimeDir = '{tmp}'; OutDir = "$out/harness" }} @{{ TEMP = '{tmp}' }} "$out/h.txt" "$out/h.err" $false
$diag = Invoke-PhaseScript '{WINDOWS}/Get-AppControlDiagnostics.ps1' @{{ RuntimeDir = '{tmp}' }} @{{}} "$out/d.txt" "$out/d.err" $false
$outcome = Resolve-HarnessOutcome $harness.ExitCode "$out/harness/phase1-windows-result.json"
[ordered]@{{ self_exit = $self.ExitCode; self_ok = ($self.Output -match 'all assertions passed'); self_step = (Resolve-ScriptStep $self 'x').Kind; harness_exit = $harness.ExitCode;
            harness_status = $outcome.Status; diag_exit = $diag.ExitCode; diag_kind = (Resolve-ScriptStep $diag 'x').Kind; env_restored = ($env:TEMP -eq $before); errors = @($self.ErrorType, $harness.ErrorType, $diag.ErrorType) }} | ConvertTo-Json -Compress
'''
            result = subprocess.run([PWSH, '-NoProfile', '-Command', command], capture_output=True, text=True, timeout=300)
            data = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertEqual(data['self_exit'], 0, result.stdout[-600:])
            self.assertTrue(data['self_ok'])
            self.assertEqual(data['harness_exit'], 3)
            self.assertEqual(data['harness_status'], 'NOT EXECUTED')
            self.assertEqual(data['diag_exit'], 3)
            self.assertEqual((data['self_step'], data['diag_kind']), ('exit', 'exit'))
            self.assertTrue(data['env_restored'])
            self.assertEqual([e for e in data['errors'] if e], [])

    def test_non_windows_run_reports_not_executed_for_every_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([PWSH, '-NoProfile', '-File', str(WINDOWS / 'Test-WindowsFeasibility.ps1'), '-HostExe', '/bin/true', '-RuntimeDir', tmp, '-OutDir', tmp + '/out'],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 3)
            report = json.loads(Path(tmp, 'out', 'phase1-windows-result.json').read_text())
            self.assertEqual(report['overall'], 'NOT EXECUTED')
            self.assertEqual(report['platform'], 'not-windows')
            self.assertEqual({s['status'] for s in report['stages']}, {'NOT EXECUTED'})
            self.assertEqual(len(report['stages']), 14)

    def test_diagnostics_not_executed_off_windows(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run([PWSH, '-NoProfile', '-File', str(WINDOWS / 'Get-AppControlDiagnostics.ps1'), '-RuntimeDir', tmp], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 3)


if __name__ == '__main__':
    unittest.main()
