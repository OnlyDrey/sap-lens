"""Windows packaging is separate from the privileged native service (SCM) acceptance: orchestration, manifest and prerequisite contracts.
Static and orchestration evidence only; the native acceptance itself is reported separately."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_system import failures  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_') + '_split', next((ROOT / 'scripts').rglob(name + '.py')))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


builder = load('build-deployments')


class ManifestSemantics(unittest.TestCase):
    def test_service_without_acceptance_is_a_valid_package_but_not_release_evidence(self):
        row = dict(runtime_smoke_tested=False, native_acceptance=dict(status='not_run'))
        self.assertTrue(builder.smoke_evidence('service', row, release=False))
        self.assertFalse(builder.smoke_evidence('service', row, release=True))
        self.assertFalse(builder.smoke_evidence('desktop', row, release=False), 'only the service may omit the SCM acceptance')
        self.assertTrue(builder.smoke_evidence('service', dict(runtime_smoke_tested=True, native_acceptance=dict(status='passed')), release=True))
        self.assertFalse(builder.smoke_evidence('service', dict(runtime_smoke_tested=False, native_acceptance=dict(status='blocked')), release=False))

    def test_verify_outputs_reads_the_split_evidence_from_the_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            name = 'sap-lens-' + builder.STEMS['service'][0] + '-v1.0.0' + builder.STEMS['service'][1]
            (directory / name).write_bytes(b'payload')
            digest = hashlib.sha256(b'payload').hexdigest()
            (directory / (name + '.sha256')).write_text(digest + '  ' + name + '\n')
            row = dict(status='passed', artifact=name, sha256=digest, built=True, package_verified=True, runtime_smoke_tested=False, native_acceptance=dict(status='not_run'))
            (directory / 'build-manifest.json').write_text(json.dumps(dict(version='1.0.0', source_commit='a' * 40, targets=dict(service=row))))
            builder.verify_outputs(directory, '1.0.0', 'a' * 40, ['service'])
            with self.assertRaisesRegex(ValueError, 'differs'):
                builder.verify_outputs(directory, '1.0.0', 'a' * 40, ['service'], release=True)


class PrerequisiteDiagnostics(unittest.TestCase):
    OUTPUT = 'ACCEPTANCE PREREQUISITE: the native service (SCM) acceptance needs an elevated PowerShell. Nothing was built.'

    def test_missing_elevation_is_an_acceptance_prerequisite_not_a_packaging_failure(self):
        failure = failures.StageFailure('Canonical Windows package and native smoke tests', ['powershell'], '.', 3, self.OUTPUT, 'build.log', 'service_packaging')
        self.assertEqual(failure.failure_class, 'acceptance_prerequisite')
        self.assertIn('elevated', failure.hint)
        self.assertIn('-NativeAcceptance', failure.hint)
        run = object.__new__(builder.Builder)
        run.system, run.manifest, run.stage = 'Windows', {}, 'x'
        row = run.failed_row('service', failure)
        self.assertEqual(row['status'], 'blocked')
        self.assertEqual(row['blocked_by'], 'acceptance_prerequisite')
        self.assertEqual(row['native_acceptance']['status'], 'blocked')
        self.assertFalse(row['built'])

    def test_other_failures_stay_failures(self):
        failure = failures.StageFailure('Canonical Windows package and native smoke tests', ['powershell'], '.', 1, 'FAILED (failures=2)', 'build.log', 'service_packaging')
        run = object.__new__(builder.Builder)
        run.system, run.manifest, run.stage = 'Windows', {}, 'x'
        self.assertEqual(run.failed_row('service', failure)['status'], 'failed')


class EntrypointContracts(unittest.TestCase):
    def read(self, relative):
        return (ROOT / relative).read_text(encoding='utf-8')

    def test_packaging_script_runs_the_scm_test_only_on_request_and_checks_elevation_first(self):
        text = self.read('scripts/package-windows-deployment.ps1')
        self.assertIn('[switch]$NativeAcceptance', text)
        self.assertIn("$runAcceptance = $Target -eq 'Service' -and ($NativeAcceptance -or $env:GITHUB_ACTIONS -eq 'true')", text)
        self.assertIn('if ($runAcceptance) { & ./scripts/test-server-service.ps1', text)
        self.assertLess(text.index('ACCEPTANCE PREREQUISITE'), text.index('python scripts/deployment-package.py require-inputs'), 'the prerequisite is checked before the expensive build')
        self.assertLess(text.index('exit 3'), text.index('build-server-windows.ps1'))

    def test_scm_acceptance_checks_elevation_before_changing_anything_and_runs_standalone(self):
        text = self.read('scripts/test-server-service.ps1')
        self.assertLess(text.index('IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)'), text.index('-Action Install'))
        self.assertIn('exit 3', text)
        self.assertIn('ACCEPTANCE PREREQUISITE', text)
        self.assertIn('GetTempPath()', text, 'works outside CI without RUNNER_TEMP')
        self.assertIn('An existing SAPLens service must not be changed', text, 'existing safety check preserved')

    def test_public_entrypoints_forward_the_flag(self):
        self.assertIn("@('--native-acceptance',$NativeAcceptance)", self.read('scripts/build.ps1'))
        self.assertIn('--native-acceptance', self.read('scripts/build_system/cli.py'))
        self.assertIn("command+=['--native-acceptance']", self.read('scripts/build_system/targets.py'))
        cli = SimpleNamespace()
        del cli


if __name__ == '__main__':
    unittest.main()
