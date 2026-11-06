"""Contract and golden-command tests for the Python port of scripts/build-windows.ps1.

They prove which commands run, in which order, with which arguments and exit codes. They do not prove that PyInstaller, npm or the Windows
tools accept those commands on Windows: that is the remaining validation gate (see docs/BUILD.md, "Windows validation checklist")."""
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_system.windows import stages  # noqa: E402
from build_system import targets  # noqa: E402

PS = (ROOT / 'scripts' / 'build-windows.ps1').read_text(encoding='utf-8')
ENV = os.environ.copy()


class Recorder:
    def __init__(self, fail_on=None, site='C:/site-packages'):
        self.commands, self.envs, self.fail_on, self.site = [], [], fail_on, site

    def run(self, command, cwd, env):
        self.commands.append((command, Path(cwd))); self.envs.append(env)
        return 1 if self.fail_on and self.fail_on in ' '.join(command) else 0

    def capture(self, command, cwd, env):
        self.commands.append((command, Path(cwd)))
        return 0, self.site


def options(**values):
    parsed = stages.parser().parse_args([])
    for key, value in values.items():
        setattr(parsed, key, value)
    return parsed


class Case(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'backend/build').mkdir(parents=True)
        self.output = []

    def run_stage(self, recorder=None, environ=None, **values):
        recorder = recorder or Recorder()
        engine = stages.WindowsStages(options(**values), self.root, recorder, environ or {'PATH': 'ORIGINAL'}, self.output.append)
        engine.host_python = 'HOSTPY'
        engine.audit_python = values.get('AuditPython') or 'HOSTPY'
        engine.npm = lambda: 'npm'
        engine.execute()
        return recorder

    def rel(self, recorder):
        """Commands with the build interpreter and the temporary root normalised, as (cwd, text)."""
        python = str(stages.venv_python(self.root))
        result = []
        for command, cwd in recorder.commands:
            text = ' '.join(str(part) for part in command).replace(python, '<buildpy>').replace(str(self.root), '<root>').replace('\\', '/')
            cwd_text = str(cwd).replace(str(self.root), '<root>').replace('\\', '/')
            result.append((cwd_text, text))
        return result


class GoldenCommands(Case):
    def test_environment_and_frontend(self):
        self.assertEqual(self.rel(self.run_stage(Stage='Environment')), [('<root>', 'HOSTPY -m venv backend/build/python-env')])
        self.assertEqual(self.rel(self.run_stage(Stage='Frontend')), [('<root>/frontend', 'npm ci --no-audit --no-fund'), ('<root>/frontend', 'npm run build')])
        self.assertEqual(self.rel(self.run_stage(Stage='FrontendInstall')), [('<root>/frontend', 'npm ci --no-audit --no-fund')])

    def test_python_and_audit(self):
        self.assertEqual(self.rel(self.run_stage(Stage='Python')), [
            ('<root>', '<buildpy> -m pip install --disable-pip-version-check -r backend/requirements-build.txt -r backend/requirements-dev.txt'),
            ('<root>', '<buildpy> -m pip check')])
        self.assertEqual(self.rel(self.run_stage(Stage='Audit', AuditPython='AUDITPY')), [
            ('<root>', 'AUDITPY -m pip install --disable-pip-version-check -r scripts/requirements-audit.txt'),
            ('<root>', "<buildpy> -c import sysconfig; print(sysconfig.get_paths()['purelib'])"),
            ('<root>', 'AUDITPY -m pip_audit --path C:/site-packages --vulnerability-service pypi --progress-spinner off')])
        self.assertEqual(self.rel(self.run_stage(Stage='JavaScriptAudit')), [('<root>/frontend', 'npm audit --omit=dev')])

    def test_backend_full_and_targeted(self):
        self.assertEqual(self.rel(self.run_stage(Stage='Backend')), [('<root>', '<buildpy> -W error::DeprecationWarning -m unittest discover -s backend/tests -v')])
        targeted = self.rel(self.run_stage(Stage='Backend', TargetedValidation=True))
        self.assertEqual([text.split('-p ')[1].split(' ')[0] for _, text in targeted],
                         ['test_desktop.py', 'test_windows_package.py', 'test_server.py', 'test_build_version.py', 'test_local_build.py'])
        self.assertTrue(all('-W error::DeprecationWarning -m unittest discover -s backend/tests -p' in text and text.endswith('-v') for _, text in targeted))

    def test_browser(self):
        self.assertEqual(self.rel(self.run_stage(Stage='Browser')), [
            ('<root>/frontend', 'npm audit --omit=dev'),
            ('<root>/frontend', 'node node_modules/playwright/cli.js install chromium --only-shell'),
            ('<root>/frontend', 'npm run test:browser -- --reporter=line,github --workers=1')])
        self.assertTrue(self.rel(self.run_stage(Stage='Browser', TargetedValidation=True))[-1][1].endswith('--workers=1 --grep @smoke'))

    def test_package_validated_deployment_and_local(self):
        local = self.rel(self.run_stage(Stage='Package'))
        self.assertEqual(local[0], ('<root>', '<buildpy> scripts/packaging/release-windows.py ensure-local-build'))
        deployment = self.rel(self.run_stage(Stage='Package', ValidatedDeployment=True))
        self.assertEqual(deployment[0], ('<root>', '<buildpy> scripts/deployment-package.py require-inputs'))
        for commands in (local, deployment):
            self.assertEqual(commands[1], ('<root>', '<buildpy> scripts/packaging/write-windows-metadata.py'))
            self.assertEqual(len(commands), 3)
            text = commands[2][1]
            self.assertTrue(text.startswith('<buildpy> -m PyInstaller --clean --noconfirm --onefile --windowed --noupx --name SAP-Lens --icon <root>/assets/sap-lens.ico --version-file <root>/backend/build/version-info.txt '))
            self.assertIn('--add-data <root>/assets/sap-lens.ico;assets --paths backend --add-data <root>/backend/build/build-version.json;. --add-data <root>/backend/resources;resources '
                          '--add-data <root>/frontend/dist;frontend/dist --specpath backend', text)
            self.assertTrue(text.endswith('--distpath backend/dist --workpath backend/build backend/desktop.py'))
        benchmark = self.rel(self.run_stage(Stage='Package', BenchmarkPackaging=True))
        self.assertEqual(len(benchmark), 4)
        self.assertNotIn('--clean', benchmark[3][1])
        self.assertEqual(benchmark[3][1].replace('-m PyInstaller ', '-m PyInstaller --clean '), benchmark[2][1])

    def test_verify_writes_the_checksum_and_verifies(self):
        (self.root / 'backend/dist').mkdir(parents=True)
        (self.root / 'backend/dist/SAP-Lens.exe').write_bytes(b'synthetic executable')
        commands = self.rel(self.run_stage(Stage='Verify'))
        self.assertEqual(commands, [('<root>', '<buildpy> scripts/packaging/verify-windows-package.py')])
        digest = __import__('hashlib').sha256(b'synthetic executable').hexdigest()
        self.assertEqual((self.root / 'backend/dist/SAP-Lens.exe.sha256').read_bytes().decode().strip(), f'{digest}  SAP-Lens.exe')

    def test_smoke_runs_the_powershell_native_test(self):
        commands = self.rel(self.run_stage(Stage='Smoke'))
        self.assertEqual(len(commands), 1)
        self.assertTrue(commands[0][1].endswith('-NoProfile -File <root>/scripts/test-windows-exe.ps1'))

    def test_artifact_stage(self):
        (self.root / 'backend/build/package-verification.json').write_text('{"exe_sha256": "abc"}', encoding='utf-8')
        commands = self.rel(self.run_stage(Stage='Artifact', ArtifactDirectory='D', ArtifactDownloadDirectory='Z', ArtifactDigest='H'))
        self.assertEqual(commands, [('<root>', '<buildpy> scripts/packaging/verify-artifact-zip.py --download Z --destination D --expected-digest H'),
                                    ('<root>', '<buildpy> scripts/packaging/verify-windows-package.py --distribution D --expected-sha256 abc --report backend/build/artifact-verification.json')])
        without_download = self.rel(self.run_stage(Stage='Artifact', ArtifactDirectory='D'))
        self.assertEqual(len(without_download), 1)
        with self.assertRaisesRegex(stages.StageError, 'needs a downloaded artifact directory'):
            self.run_stage(Stage='Artifact')

    def test_all_runs_every_stage_in_the_powershell_order_and_never_the_artifact_stage(self):
        (self.root / 'backend/dist').mkdir(parents=True)
        (self.root / 'backend/dist/SAP-Lens.exe').write_bytes(b'x')
        commands = [text for _, text in self.rel(self.run_stage(Stage='All'))]
        markers = ['-m venv', 'npm ci', 'npm run build', 'pip install --disable-pip-version-check -r backend/requirements-build.txt', 'pip check', 'pip install --disable-pip-version-check -r scripts/requirements-audit.txt',
                   'pip_audit', 'npm audit', 'unittest discover', 'playwright/cli.js install', 'test:browser', 'release-windows.py ensure-local-build', 'write-windows-metadata.py', 'PyInstaller',
                   'verify-windows-package.py', 'test-windows-exe.ps1']
        positions = [next(index for index, text in enumerate(commands) if marker in text) for marker in markers]
        self.assertEqual(positions, sorted(positions))
        self.assertFalse(any('verify-artifact-zip' in text for text in commands))
        self.assertEqual(self.output[-1], 'Completed build stage: All')


class Behaviour(Case):
    def test_the_environment_stage_removes_stale_reports_and_timings(self):
        for name in ('timings.jsonl', 'package-verification.json', 'artifact-verification.json', 'keep.txt'):
            (self.root / 'backend/build' / name).write_text('x')
        self.run_stage(Stage='Environment')
        self.assertEqual(sorted(path.name for path in (self.root / 'backend/build').iterdir()), ['keep.txt', 'timings.jsonl'])  # timings.jsonl is recreated by this stage's own record

    def test_timing_records_and_log_markers(self):
        self.run_stage(Stage='Python')
        import json
        records = [json.loads(line) for line in (self.root / 'backend/build/timings.jsonl').read_text().splitlines()]
        self.assertEqual([(r['stage'], r['status']) for r in records], [('Python dependency installation', 'passed')])
        self.assertIn('::group::Python dependency installation', self.output)
        self.assertIn('::endgroup::', self.output)
        self.assertTrue(any(line.startswith('TIMING Python dependency installation : ') and line.endswith('(passed)') for line in self.output))

    def test_a_failing_command_stops_the_run_records_failure_and_reports_in_actions(self):
        with self.assertRaisesRegex(stages.StageError, 'Install build and test dependencies failed with exit code 1'):
            self.run_stage(Recorder(fail_on='pip install'), {'PATH': 'P', 'GITHUB_ACTIONS': 'true'}, Stage='Python')
        self.assertIn('::error title=SAP Lens build::Install build and test dependencies failed with exit code 1', self.output)
        self.assertTrue(any(line.endswith('(failed)') for line in self.output))
        self.assertNotIn('Completed build stage: Python', self.output)

    def test_no_actions_annotation_outside_github_actions(self):
        with self.assertRaises(stages.StageError):
            self.run_stage(Recorder(fail_on='npm ci'), Stage='FrontendInstall')
        self.assertFalse(any(line.startswith('::error') for line in self.output))

    def test_the_build_environment_leads_the_path_and_the_process_environment_is_untouched(self):
        recorder = self.run_stage(Stage='Python', environ={'PATH': 'ORIGINAL'})
        self.assertTrue(recorder.envs[0]['PATH'].startswith(str(stages.venv_python(self.root).parent) + os.pathsep))
        self.assertTrue(recorder.envs[0]['PATH'].endswith('ORIGINAL'))

    def test_main_maps_errors_to_exit_code_one(self):
        with patch.object(stages, 'WindowsStages') as engine, patch('builtins.print'):
            engine.return_value.execute.side_effect = stages.StageError('boom')
            self.assertEqual(stages.main(['-Stage', 'Python']), 1)
            engine.return_value.execute.side_effect = None
            self.assertEqual(stages.main(['-Stage', 'Python']), 0)

    def test_option_names_match_the_powershell_parameters(self):
        params = re.search(r'param\((.*?)\n\)', PS, re.S).group(1)
        ps_names = re.findall(r'\$(\w+)', params)
        port_names = [action.option_strings[0].lstrip('-') for action in stages.parser()._actions if action.option_strings and action.option_strings[0] != '-h']
        self.assertEqual(sorted(ps_names), sorted(port_names))
        self.assertEqual(re.findall(r"'(\w+)'", re.search(r"ValidateSet\((.*?)\)", params).group(1)), list(stages.STAGES))


class PowerShellContract(Case):
    """The literal arguments of the original script must all appear in the commands of the port."""
    def test_every_pyinstaller_flag_and_script_of_the_original_is_issued_by_the_port(self):
        commands = ' '.join(text for _, text in self.rel(self.run_stage(Stage='Package')))
        packaging = re.search(r'\$packagingArguments = @\((.*?)\n        \)', PS, re.S).group(1)
        for flag in re.findall(r"'(--[a-z-]+)'", packaging):
            self.assertIn(flag, commands, flag)
        for value in re.findall(r"'(docx|reportlab|tzdata|python-docx|lxml|charset-normalizer|SAP-Lens|backend)'", packaging):
            self.assertIn(value, commands, value)
        everything = ' '.join(text for stage in ('Package', 'Verify', 'Smoke', 'Artifact') for _, text in self._safe(stage))
        everything += ' ' + ' '.join(text for _, text in self.rel(self.run_stage(Stage='Package', ValidatedDeployment=True)))
        for script in set(re.findall(r'scripts/([\w-]+\.(?:py|ps1))', PS)):
            with self.subTest(script=script):
                self.assertIn(script, everything)

    def _safe(self, stage):
        (self.root / 'backend/dist').mkdir(parents=True, exist_ok=True)
        (self.root / 'backend/dist/SAP-Lens.exe').write_bytes(b'x')
        (self.root / 'backend/build/package-verification.json').write_text('{"exe_sha256": "a"}')
        return self.rel(self.run_stage(Stage=stage, ArtifactDirectory='D', ArtifactDownloadDirectory='Z', ArtifactDigest='H'))

    def test_the_original_script_is_still_present_as_the_default(self):
        self.assertTrue((ROOT / 'scripts/build-windows.ps1').is_file())


class Selection(unittest.TestCase):
    def plan(self, environment):
        from types import SimpleNamespace
        args = SimpleNamespace(ci_tool='windows-stage', mode='build', benchmark_packaging='true', tool_args=['-Stage', 'Package'], setup_only=False)
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', **environment}, clear=False):
            os.environ.pop('SAP_LENS_WINDOWS_STAGES', None) if 'SAP_LENS_WINDOWS_STAGES' not in environment else None
            return targets.plan(args, 'PY')

    def test_powershell_is_the_default(self):
        (_, command), = self.plan({})
        self.assertEqual(command[1:3], ['-NoProfile', '-File'])
        self.assertTrue(command[3].replace('\\', '/').endswith('scripts/build-windows.ps1'))
        self.assertEqual(command[-3:], ['-Stage', 'Package', '-BenchmarkPackaging'])

    def test_python_stages_are_opt_in(self):
        (name, command), = self.plan({'SAP_LENS_WINDOWS_STAGES': 'python'})
        self.assertIn('Python stages', name)
        self.assertEqual(command[0], 'PY')
        self.assertTrue(command[1].replace('\\', '/').endswith('scripts/build_system/windows/stages.py'))
        self.assertEqual(command[2:], ['-Stage', 'Package', '-BenchmarkPackaging'])


if __name__ == '__main__':
    unittest.main()
