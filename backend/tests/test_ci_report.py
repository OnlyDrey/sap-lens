"""CI reports reflect actual step outcomes, including failures and skipped work."""
import importlib.util
import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('ci_report', Path(__file__).resolve().parents[2] / 'scripts/ci.py')
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


class CIReportTests(unittest.TestCase):
    def test_missing_and_skipped_mandatory_checks_are_incomplete(self):
        for outcome in ('skipped', 'cancelled', None):
            with self.subTest(outcome=outcome):
                text = ci.render({'backend': {'outcome': outcome}}, [], {'CI_REQUIRED': 'backend browser'})
                self.assertNotIn('**Passed**', text)
        self.assertNotIn('**Passed**', ci.render({}, [], {}))

    def test_failed_checks_override_successful_timing(self):
        text = ci.render({'backend': {'outcome': 'failure'}}, [{'stage':'backend','seconds':1,'tests':84}], {'CI_REQUIRED':'backend'})
        self.assertIn('**Failed**', text)
        self.assertIn('| backend | failure | 1.00 s | 84 |', text)

    def test_success_counts_skipped_tests_and_escapes_source(self):
        text = ci.render({'backend': {'outcome':'success'}}, [{'stage':'backend','seconds':2,'tests':84,'skipped':1}], {'CI_REQUIRED':'backend','GITHUB_REF_NAME':'demo|<script>'})
        self.assertIn('**Passed**', text)
        self.assertIn('84; 1 skipped', text)
        self.assertNotIn('<script>', text)
        self.assertIn('demo\\|&lt;script&gt;', text)

    def test_real_command_exit_status_and_test_counts_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'RUNNER_TEMP':directory}):
            for code in (0, 7):
                with redirect_stdout(io.StringIO()):
                    result = ci.run('synthetic', [sys.executable, '-c', f'print("Ran 3 tests in 1s"); raise SystemExit({code})'])
                self.assertEqual(result, code)
            records = [json.loads(line) for line in ci.timing_path().read_text().splitlines()]
            self.assertEqual([record['status'] for record in records], ['passed', 'failed'])
            self.assertEqual([record['tests'] for record in records], [3, 3])

    def test_partial_timing_records_do_not_hide_failed_step(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'RUNNER_TEMP':directory,'CI_REQUIRED':'backend','CI_STEPS':'{"backend":{"outcome":"failure"}}'}, clear=True):
            ci.timing_path().write_text('{"interrupted"\n')
            with redirect_stdout(io.StringIO()) as output: ci.summary()
            self.assertIn('**Failed**', output.getvalue())
