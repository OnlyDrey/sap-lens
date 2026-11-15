"""Bundle reproducibility and the Phase 1 runner's behaviour that can be verified off Windows: integrity, tamper detection, archive safety on the real
archive, preserved evidence, non-Windows and Constrained Language Mode reports. The Windows execution path of the runner is NOT covered here."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / 'windows'
PWSH = shutil.which('pwsh')
GO = shutil.which('go')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@unittest.skipUnless(PWSH and GO, 'needs pwsh and go')
class BundleAndRunner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = Path(tempfile.mkdtemp(prefix='poc-bundle-test-'))
        cls.bundles, cls.summaries = [], []
        if not any((ROOT / '.cache').rglob('*.whl')):
            raise unittest.SkipTest('wheel cache not populated')
        for name in ('a', 'b'):
            out = cls.base / name
            result = subprocess.run([sys.executable, str(WINDOWS / 'make_bundle.py'), '--out', str(out)], capture_output=True, text=True, timeout=900)
            if result.returncode != 0:
                raise unittest.SkipTest(f'bundle could not be built: {result.stderr[-300:]}')
            cls.bundles.append(out)
            cls.summaries.append(json.loads(result.stdout.strip().splitlines()[-1]))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.base, ignore_errors=True)

    def run_runner(self, bundle, trusted, work, *extra, runner=None):
        runner = runner or (bundle / 'scripts' / 'Run-Phase1.ps1')
        return subprocess.run([PWSH, '-NoProfile', '-File', str(runner), '-BundleDir', str(bundle), '-TrustedSumsSha256', trusted, '-WorkRoot', str(work), *extra],
                              capture_output=True, text=True, timeout=300)

    def summary(self, work):
        files = list(Path(work).glob('*/evidence/run-summary.json'))
        self.assertEqual(len(files), 1, 'the evidence must be preserved even when the run stops')
        return json.loads(files[0].read_text())

    # ---- bundle ----------------------------------------------------------------------------------------------------------------------------
    def test_bundle_is_reproducible(self):
        self.assertEqual((self.bundles[0] / 'SHA256SUMS.txt').read_text(), (self.bundles[1] / 'SHA256SUMS.txt').read_text())
        self.assertEqual(self.summaries[0]['sums_sha256'], self.summaries[1]['sums_sha256'])
        self.assertEqual(self.summaries[0]['sums_sha256'], sha(self.bundles[0] / 'SHA256SUMS.txt'))

    def test_bundle_contents(self):
        files = sorted(p.relative_to(self.bundles[0]).as_posix() for p in self.bundles[0].rglob('*') if p.is_file())
        self.assertEqual(files, ['SHA256SUMS.txt', 'runtime.tar.gz', 'saplens-host.exe', 'scripts/Get-AppControlDiagnostics.ps1', 'scripts/Phase1Common.ps1',
                                 'scripts/Run-Phase1.ps1', 'scripts/Test-Phase1Logic.ps1', 'scripts/Test-WindowsFeasibility.ps1'])
        self.assertNotIn('python', ' '.join(files).replace('Phase1', ''))  # no interpreter or Python tooling is needed on the Windows target besides the runtime archive

    def test_host_is_independent_of_vcs_stamping(self):
        data = (self.bundles[0] / 'saplens-host.exe').read_bytes()
        self.assertNotIn(b'vcs.revision', data)

    # ---- verify-only on the real bundle and archive ------------------------------------------------------------------------------------------
    def test_verify_only_passes_on_the_real_bundle(self):
        bundle, trusted = self.bundles[0], self.summaries[0]['sums_sha256']
        work = self.base / 'w-ok'
        result = self.run_runner(bundle, trusted, work, '-VerifyOnly')
        self.assertEqual(result.returncode, 0, result.stdout[-600:])
        summary = self.summary(work)
        self.assertTrue(summary['verified'])
        self.assertEqual(summary['mode'], 'verify-only (not a Phase 1 result)')
        self.assertEqual({s['id']: s['status'] for s in summary['steps']}['R03 archive safety and extraction'], 'PASS')
        self.assertTrue(any(Path(work).glob('*/bundle/runtime.tar.gz')), 'nothing may be deleted')
        self.assertEqual(sha(bundle / 'SHA256SUMS.txt'), trusted)

    def test_verify_only_refuses_every_tamper(self):
        trusted = self.summaries[0]['sums_sha256']
        cases = {}
        for name, mutate in {'changed_archive': lambda b: (b / 'runtime.tar.gz').write_bytes((b / 'runtime.tar.gz').read_bytes() + b'x'),
                             'changed_script': lambda b: (b / 'scripts' / 'Test-WindowsFeasibility.ps1').write_text('# tampered\n'),
                             'extra_file': lambda b: (b / 'scripts' / 'extra.ps1').write_text('x'),
                             'missing_host': lambda b: (b / 'saplens-host.exe').unlink(),
                             'sums_replaced': lambda b: (b / 'SHA256SUMS.txt').write_text('0' * 64 + '  saplens-host.exe\n')}.items():
            copy = self.base / ('t-' + name)
            shutil.copytree(self.bundles[0], copy)
            mutate(copy)
            result = self.run_runner(copy, trusted, self.base / ('w-' + name), '-VerifyOnly')
            self.assertEqual(result.returncode, 3, f'{name}: {result.stdout[-300:]}')
            summary = self.summary(self.base / ('w-' + name))
            self.assertFalse(summary['verified'], name)
            self.assertEqual(summary['overall'], 'NOT EXECUTED', name)
            self.assertIn('R02', ' '.join(s['id'] for s in summary['steps'] if s['status'] == 'NOT EXECUTED'), name)

    def test_wrong_trusted_checksum_and_foreign_runner_are_refused(self):
        bundle = self.bundles[0]
        self.assertEqual(self.run_runner(bundle, '0' * 64, self.base / 'w-wrong', '-VerifyOnly').returncode, 3)
        result = self.run_runner(bundle, self.summaries[0]['sums_sha256'], self.base / 'w-foreign', '-VerifyOnly', runner=WINDOWS / 'Run-Phase1.ps1')
        self.assertEqual(result.returncode, 3)
        self.assertIn('scripts folder of the bundle', self.summary(self.base / 'w-foreign')['stopped_reason'])

    def test_malformed_trusted_checksum_is_rejected_before_anything_runs(self):
        result = self.run_runner(self.bundles[0], 'not-a-hash', self.base / 'w-bad')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.base / 'w-bad').exists())

    # ---- non-Windows and Constrained Language Mode ---------------------------------------------------------------------------------------------
    def test_non_windows_run_executes_nothing_and_keeps_evidence(self):
        work = self.base / 'w-linux'
        result = self.run_runner(self.bundles[0], self.summaries[0]['sums_sha256'], work)
        self.assertEqual(result.returncode, 3)
        summary = self.summary(work)
        self.assertEqual(summary['overall'], 'NOT EXECUTED')
        self.assertEqual(summary['platform'], 'not-windows')
        self.assertEqual({s['status'] for s in summary['steps']}, {'NOT EXECUTED'})
        self.assertFalse(any(Path(work).glob('*/runtime')), 'nothing was extracted')

    def test_constrained_language_mode_still_produces_a_report(self):
        work = self.base / 'w-clm'
        bundle, trusted = self.bundles[0], self.summaries[0]['sums_sha256']
        command = (f'$ExecutionContext.SessionState.LanguageMode = "ConstrainedLanguage"; & "{bundle}/scripts/Run-Phase1.ps1" -BundleDir "{bundle}" '
                   f'-TrustedSumsSha256 "{trusted}" -WorkRoot "{work}" -VerifyOnly; exit $LASTEXITCODE')
        result = subprocess.run([PWSH, '-NoProfile', '-Command', command], capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 3, result.stdout[-400:] + result.stderr[-400:])
        self.assertIn('ConstrainedLanguage', self.summary(work)['stopped_reason'])

    def test_harness_reports_constrained_language_mode_as_not_executed(self):
        out = self.base / 'h-clm'
        command = (f'$env:OS = "Windows_NT"; $ExecutionContext.SessionState.LanguageMode = "ConstrainedLanguage"; & "{WINDOWS}/Test-WindowsFeasibility.ps1" '
                   f'-HostExe /bin/true -RuntimeDir /tmp -OutDir "{out}"; exit $LASTEXITCODE')
        result = subprocess.run([PWSH, '-NoProfile', '-Command', command], capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 3)
        report = json.loads((out / 'phase1-windows-result.json').read_text())
        self.assertEqual(report['overall'], 'NOT EXECUTED')
        self.assertEqual(len(report['stages']), 14)


if __name__ == '__main__':
    unittest.main()
