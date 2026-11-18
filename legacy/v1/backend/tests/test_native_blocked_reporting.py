"""A Windows App Control block is reported as BLOCKED (never PASS, never an application failure) at every level: stage failure, manifest row,
terminal verdict and exit status. Synthetic output only; native Windows behavior is covered by the PowerShell evidence tests."""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_windows_acceptance_split import builder, failures  # noqa: E402

BLOCKED = ('SMOKE FAILURE [windows_application_control_blocked] An application control policy has blocked this file.\n'
           'Process creation failed; executable_started=False; native_error_code=4551; Authenticode=NotSigned\n'
           'event_id=3077; policy_id={0283ac0f-fff1-49ae-ada1-8a933130cad6}; correlation=exact_path\n'
           'Next: NATIVE ACCEPTANCE BLOCKED [environment_policy_blocked]: the operating system refused to run this file')
LABEL = 'Canonical Windows Desktop package and native smoke tests'


def run_object(build):
    run = object.__new__(builder.Builder)
    run.system, run.manifest, run.stage, run.build, run.current_target = 'Windows', {}, 'x', Path(build), 'desktop'
    return run


def journal(build, **stages):
    names = dict(packaging='PyInstaller packaging (clean)', verification='Package verification and checksum', smoke='EXE smoke testing')
    (Path(build) / 'timings.jsonl').write_text('\n'.join(json.dumps(dict(stage=names[key], seconds=1, status=value)) for key, value in stages.items()), encoding='utf-8')


class BlockedClassification(unittest.TestCase):
    def test_a_correlated_policy_block_is_its_own_failure_class_with_a_clear_hint(self):
        failure = failures.StageFailure(LABEL, ['powershell'], '.', 1, BLOCKED, 'build.log', 'desktop_packaging')
        self.assertEqual(failure.failure_class, 'environment_policy_blocked')
        self.assertIn('not an application failure and not a pass', failure.hint)
        self.assertIn('Do not disable or bypass', failure.hint)

    def test_startup_failures_after_the_process_was_created_stay_failures(self):
        for text in ('SMOKE FAILURE [http_unavailable] Not ready within 60 s: health not answering\nLast health: none received. Last HTTP error: timeout',
                     'SMOKE FAILURE [process_exited_before_readiness] exited', 'SMOKE FAILURE [process_creation_failed] generic error\nexecutable_started=False; Authenticode=NotSigned\nNo correlated blocking events found.',
                     'SMOKE FAILURE [assertion_failed] Runtime version differs'):
            with self.subTest(text=text[:40]):
                self.assertEqual(failures.StageFailure(LABEL, ['powershell'], '.', 1, text, 'build.log', 'desktop_packaging').failure_class, 'desktop_packaging')

    def test_the_stage_label_names_its_target_and_keeps_the_packaging_class(self):
        run = object.__new__(builder.Builder)
        run.current_target = 'desktop'
        self.assertEqual(run.failure_class(LABEL), 'desktop_packaging')
        run.current_target = 'service'
        self.assertEqual(run.failure_class('Canonical Windows Service package and native smoke tests'), 'service_packaging')
        self.assertEqual(run.failure_class('Canonical Windows package and native smoke tests'), 'service_packaging')   # historical label


class BlockedManifestRow(unittest.TestCase):
    def row(self, stages, result=None):
        with tempfile.TemporaryDirectory() as directory:
            journal(directory, **stages)
            if result is not None: (Path(directory) / 'native-smoke-result.json').write_text(json.dumps(result), encoding='utf-8')
            run = run_object(directory)
            failure = failures.StageFailure(LABEL, ['powershell'], '.', 1, BLOCKED, 'build.log', 'desktop_packaging')
            with redirect_stderr(io.StringIO()):
                return run.failed_row('desktop', failure)

    def test_packaging_passed_native_blocked_and_nothing_claims_the_app_ran(self):
        row = self.row(dict(packaging='passed', verification='passed', smoke='failed'),
                       dict(schema=1, kind='windows-native-smoke', status='blocked', reason='environment_policy_blocked', executable='SAP-Lens.exe', executable_started=False,
                            native_error_code=4551, authenticode='NotSigned', correlated_events=[dict(event_id=3077, policy_id='{0283ac0f-fff1-49ae-ada1-8a933130cad6}', correlation='exact_path')],
                            limitations=[], secret_environment='must-not-be-copied'))
        self.assertEqual((row['status'], row['blocked_by']), ('blocked', 'environment_policy_blocked'))
        self.assertTrue(row['built']); self.assertTrue(row['package_verified']); self.assertFalse(row['runtime_smoke_tested'])
        self.assertEqual(row['native_smoke']['stages'], dict(packaging='passed', verification='passed', smoke='failed'))
        self.assertEqual(row['native_smoke']['result']['native_error_code'], 4551)
        self.assertNotIn('secret_environment', row['native_smoke']['result'])
        self.assertEqual(row['failure_class'], 'environment_policy_blocked')

    def test_missing_or_malformed_evidence_degrades_to_none_and_not_recorded(self):
        row = self.row(dict(packaging='passed'), None)
        self.assertIsNone(row['native_smoke']['result'])
        self.assertEqual(row['native_smoke']['stages']['verification'], 'not_recorded')
        self.assertFalse(row['package_verified'])
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'native-smoke-result.json').write_text('{not json')
            self.assertIsNone(run_object(directory).native_smoke_result())
            (Path(directory) / 'native-smoke-result.json').write_text(json.dumps(dict(schema=2, status='passed')))
            self.assertIsNone(run_object(directory).native_smoke_result())


class Verdict(unittest.TestCase):
    PASSED_SERVICE = dict(status='passed', built=True, package_verified=True, runtime_smoke_tested=True, native_acceptance=dict(status='passed'))
    BLOCKED_DESKTOP = dict(status='blocked', blocked_by='environment_policy_blocked', built=True, package_verified=True, runtime_smoke_tested=False)

    def test_blocked_desktop_with_a_passing_server_is_not_verified_and_not_approved(self):
        lines = builder.Builder.verdict_lines(dict(desktop=self.BLOCKED_DESKTOP, service=self.PASSED_SERVICE))
        self.assertIn('desktop: packaging PASS, package integrity PASS, native acceptance BLOCKED (environment_policy_blocked)', lines)
        self.assertIn('service: packaging PASS, package integrity PASS, native acceptance PASS', lines)
        self.assertIn('Overall native acceptance: NOT VERIFIED', lines)
        self.assertIn('Release readiness: NOT APPROVED', lines)

    def test_only_fully_executed_targets_are_verified(self):
        ok = dict(status='passed', built=True, package_verified=True, runtime_smoke_tested=True)
        lines = builder.Builder.verdict_lines(dict(desktop=ok, service=self.PASSED_SERVICE))
        self.assertIn('Overall native acceptance: VERIFIED', lines)
        self.assertTrue(lines[-1].startswith('Release readiness: local criteria met'))
        not_run = dict(self.PASSED_SERVICE, native_acceptance=dict(status='not_run'))
        lines = builder.Builder.verdict_lines(dict(desktop=ok, service=not_run))
        self.assertIn('Overall native acceptance: NOT VERIFIED', lines)
        self.assertTrue(any('NOT RUN (privileged SCM acceptance not executed)' in line for line in lines))

    def test_failed_and_unreached_targets_are_never_verified(self):
        failed = dict(status='failed', built=True, package_verified=True, runtime_smoke_tested=False)
        shared = dict(status='blocked', blocked_by='shared_validation', built=False, package_verified=False)
        lines = builder.Builder.verdict_lines(dict(desktop=failed, service=shared))
        self.assertIn('desktop: packaging PASS, package integrity PASS, native acceptance FAILED', lines)
        self.assertIn('service: packaging NOT RUN, package integrity NOT RUN, native acceptance BLOCKED (shared_validation)', lines)
        self.assertIn('Overall native acceptance: NOT VERIFIED', lines)


class AggregateStatus(unittest.TestCase):
    def execute(self, rows):
        with tempfile.TemporaryDirectory() as directory:
            run = run_object(directory)
            run.args = SimpleNamespace(platform=['desktop', 'service'])
            run.output, run.manifest = Path(directory), dict(targets={})
            out = io.StringIO()
            with patch.object(builder, 'requested', return_value=['desktop', 'service']), patch.object(builder, 'host_for', return_value='Windows'), \
                    patch.object(run, 'local', side_effect=lambda target: rows[target]), patch.object(run, 'save'), redirect_stdout(out):
                code = run.execute()
            return code, out.getvalue()

    def test_a_blocked_target_makes_the_run_fail_and_prints_one_consistent_verdict(self):
        code, text = self.execute(dict(desktop=Verdict.BLOCKED_DESKTOP, service=Verdict.PASSED_SERVICE))
        self.assertEqual(code, 1)
        self.assertEqual(text.count('Overall native acceptance:'), 1)
        self.assertIn('desktop: blocked', text)
        self.assertIn('service: passed', text)
        self.assertIn('Release readiness: NOT APPROVED', text)

    def test_all_passed_exits_zero(self):
        ok = dict(status='passed', built=True, package_verified=True, runtime_smoke_tested=True, artifact='x.zip')
        code, text = self.execute(dict(desktop=ok, service=dict(Verdict.PASSED_SERVICE, artifact='y.zip')))
        self.assertEqual(code, 0)
        self.assertIn('Overall native acceptance: VERIFIED', text)


if __name__ == '__main__':
    unittest.main()
