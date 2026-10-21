"""Build summaries preserve failure/incomplete results and separate digest scopes."""
from datetime import datetime, timezone
import importlib.util
import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('build_report', Path(__file__).resolve().parents[2] / 'scripts/write-build-report.py')
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class BuildReportTests(unittest.TestCase):
    def test_one_table_keeps_partial_failures_and_missing_stages_honest(self):
        records = [{'stage': 'npm installation', 'seconds': 2, 'status': 'passed'},
                   {'stage': 'Backend tests', 'seconds': 3, 'status': 'failed'}]
        text = report.render(records, {}, [], {'BUILD_STATUS': 'failure'})
        self.assertEqual(text.count('| Stage | Duration | Status |'), 1)
        self.assertIn('| Frontend | 2.00 s | Incomplete |', text)
        self.assertIn('| Backend tests | 3.00 s | Failed |', text)
        self.assertIn('| Packaging | Unavailable | Not run |', text)
        self.assertNotIn('secret', text)

    def test_success_report_includes_upload_duration_metadata_and_separate_checksums(self):
        records = [{'stage': task, 'seconds': 1, 'status': 'passed'} for tasks in report.STAGES.values() for task in tasks[:1] if task]
        records += [{'stage': task, 'seconds': 1, 'status': 'passed'} for task in ['Frontend compilation', 'Python vulnerability audit', 'Production JavaScript audit', 'Playwright tests']]
        package = {'version': '1.2.0', 'format': 'one-file', 'size_bytes': 100, 'exe_sha256': 'a'*64}
        jobs = [{'name': 'windows-exe', 'started_at': '2026-10-21T10:00:00Z', 'steps': [
            {'name': 'Upload verified executable', 'started_at': '2026-10-21T10:01:00Z', 'completed_at': '2026-10-21T10:01:03Z', 'conclusion': 'success'}]}]
        text = report.render(records, package, jobs, {'BUILD_STATUS': 'success', 'ARTIFACT_DIGEST': 'b'*64, 'GITHUB_SHA': 'c'*40, 'GITHUB_REF_NAME': 'work', 'RUNNER_OS': 'Windows', 'RUNNER_ARCH': 'X64'}, datetime(2026,10,21,10,2,tzinfo=timezone.utc))
        self.assertIn('| Artifact upload | 3.00 s | Passed |', text)
        self.assertIn('| Executable SHA-256 | '+'a'*64, text)
        self.assertIn('| GitHub artifact ZIP SHA-256 | '+'b'*64, text)
        self.assertIn('post-job cleanup', text)
        self.assertIn('Unsigned; signing deferred', text)
        self.assertIn('| Packaging | 1.00 s | Passed |', text)

    def test_invalid_or_interrupted_timing_lines_do_not_hide_completed_records(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'timings.jsonl'
            record = {'stage': 'Backend tests', 'seconds': 2.2, 'status': 'passed'}
            path.write_text(json.dumps(record)+'\n'+json.dumps({'stage':'bad','seconds':float('nan'),'status':'passed'})+'\n{"interrupted"')
            self.assertEqual(report.read_timings(path), [record])

    def test_summary_escapes_table_and_html_values(self):
        text = report.render([], {}, [], {'GITHUB_REF_NAME':'x|y\n<script>'})
        self.assertIn('x\\|y &lt;script&gt;', text)
        self.assertNotIn('<script>', text)

    def test_github_api_timeout_does_not_suppress_local_failure_report(self):
        from unittest.mock import patch
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root/'backend/build').mkdir(parents=True)
            summary = root/'summary.md'
            (root/'backend/build/timings.jsonl').write_text(json.dumps({'stage': 'Backend tests', 'seconds': 1, 'status': 'failed'})+'\n')
            output = io.StringIO()
            with redirect_stdout(output), patch.object(report, 'ROOT', root), patch.dict(report.os.environ, {'GITHUB_STEP_SUMMARY':str(summary), 'GITHUB_REPOSITORY':'Example/project', 'GITHUB_RUN_ID':'1'}, clear=True), patch.object(report.subprocess, 'run', side_effect=subprocess.TimeoutExpired('gh', 20)):
                report.main()
            self.assertIn('| Backend tests | 1.00 s | Failed |', summary.read_text())
            self.assertIn('::warning::Workflow timing metadata unavailable', output.getvalue())
