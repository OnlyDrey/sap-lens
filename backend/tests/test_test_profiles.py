"""Integrity of the test profiles: no test file may be silently left out of regression."""
import importlib.util
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('run_tests_script', ROOT / 'scripts' / 'run-tests.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
server_spec = importlib.util.spec_from_file_location('serve_browser_tests', ROOT / 'scripts' / 'serve-browser-tests.py')
server = importlib.util.module_from_spec(server_spec)
server_spec.loader.exec_module(server)


class TestProfileTests(unittest.TestCase):
    def test_every_backend_module_and_browser_spec_belongs_to_exactly_one_feature(self):
        self.assertEqual(runner.coverage_problems(), [])

    def test_smoke_backend_selection_resolves_to_real_tests(self):
        loader = unittest.TestLoader()
        for name in runner.load_map()['smoke']['backend']:
            try:
                suite = loader.loadTestsFromName(name)
            except (ImportError, AttributeError) as error:
                self.fail(f'{name} does not resolve: {error}')
            self.assertGreater(suite.countTestCases(), 0, name)
            self.assertNotIn('_FailedTest', repr(suite), name)

    def test_smoke_browser_tests_exist_and_cover_the_critical_features(self):
        tag = runner.load_map()['smoke']['browser_tag']
        owners = {}
        for feature, entry in runner.load_map()['features'].items():
            for spec_name in entry['browser']:
                text = (ROOT / 'frontend' / 'tests' / f'{spec_name}.spec.ts').read_text(encoding='utf-8')
                if re.search(rf"tag:\s*'{re.escape(tag)}'", text):
                    owners.setdefault(feature, []).append(spec_name)
        for feature in ('dashboard', 'role-lookup', 'user-access', 'access-package', 'account-review', 'data-sources', 'sod', 'shared-ui', 'platform', 'role-comparison'):
            self.assertIn(feature, owners, f'no {tag} browser test for {feature}')

    def test_map_has_known_feature_descriptions_and_no_empty_features(self):
        for name, feature in runner.load_map()['features'].items():
            self.assertTrue(feature['description'], name)
            self.assertTrue(feature['backend'] or feature['browser'], name)


class BrowserProcessHygieneTests(unittest.TestCase):
    """Test processes clean up after themselves and the tooling never signals processes it does not own."""

    def make_dir(self, root, name, pid=None, age=0):
        path = Path(root) / f'{server.PREFIX}{name}'
        path.mkdir()
        if pid is not None:
            (path / server.OWNER_FILE).write_text(str(pid), encoding='ascii')
        if age:
            old = time.time() - age
            os.utime(path, (old, old))
        return path

    @unittest.skipIf(sys.platform == 'win32', 'owner liveness is only probed on POSIX')
    def test_sweep_removes_only_directories_whose_owner_is_gone(self):
        with tempfile.TemporaryDirectory() as root:
            gone = subprocess.Popen([sys.executable, '-c', 'pass']); gone.wait()
            dead = self.make_dir(root, 'dead', gone.pid)
            live = self.make_dir(root, 'live', os.getpid())
            fresh = self.make_dir(root, 'fresh-legacy')
            old = self.make_dir(root, 'old-legacy', age=server.LEGACY_MAX_AGE + 60)
            unrelated = Path(root) / 'other-project-dir'; unrelated.mkdir()
            broken = self.make_dir(root, 'broken'); (broken / server.OWNER_FILE).write_text('not a pid')
            removed = server.sweep_stale(Path(root))
            self.assertEqual(sorted(removed), sorted([dead.name, old.name]))
            self.assertTrue(live.exists() and fresh.exists() and unrelated.exists() and broken.exists())

    def test_runner_reports_busy_ports_without_touching_the_owner(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); listener.listen()
            port = listener.getsockname()[1]
            original = runner.BASE_PORT
            runner.BASE_PORT = port
            try:
                self.assertEqual(runner.busy_ports(1), [port])
                result = runner.run_browser(None, None, 1, 'busy', [])
            finally:
                runner.BASE_PORT = original
            self.assertFalse(result['ok'])
            self.assertEqual(result['tests'], 0)
            self.assertGreaterEqual(listener.fileno(), 0)  # the listener is still ours and untouched

    @unittest.skipIf(sys.platform == 'win32', 'SIGTERM semantics differ on Windows')
    def test_test_server_removes_its_directory_on_sigterm(self):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
        with tempfile.TemporaryDirectory() as root:
            env = {**os.environ, 'TMPDIR': root, 'SAP_LENS_BROWSER_TEST_PORT': str(port)}
            process = subprocess.Popen([sys.executable, str(ROOT / 'scripts' / 'serve-browser-tests.py')], env=env,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.time() + 20
                while time.time() < deadline and not list(Path(root).glob(f'{server.PREFIX}*/{server.OWNER_FILE}')):
                    time.sleep(0.1)
                directories = list(Path(root).glob(f'{server.PREFIX}*'))
                self.assertEqual(len(directories), 1, 'the server created its isolated directory')
                self.assertEqual(int((directories[0] / server.OWNER_FILE).read_text()), process.pid)
                time.sleep(0.5)
                process.send_signal(signal.SIGTERM)
                self.assertIn(process.wait(15), (0, -signal.SIGTERM))
                self.assertEqual(list(Path(root).glob(f'{server.PREFIX}*')), [])
            finally:
                if process.poll() is None:
                    process.kill(); process.wait()


class ParallelExecutionTests(unittest.TestCase):
    """The browser suite can use up to three isolated processes: deterministic, balanced, bounded and always cleaned up."""

    def test_spec_distribution_is_deterministic_complete_and_balanced(self):
        files = [f'tests/{name}.spec.ts' for name in runner.browser_specs()]
        for jobs in (2, 3):
            groups = runner.split_specs(files, jobs)
            self.assertEqual(groups, runner.split_specs(list(reversed(files)), jobs), 'independent of the input order')
            self.assertEqual(sorted(file for group in groups for file in group), sorted(files), 'every spec file runs exactly once')
            hints = runner.load_map()['browser_seconds_hint']
            loads = [sum(hints.get(Path(file).name[:-8], runner.DEFAULT_SPEC_SECONDS) for file in group) for group in groups]
            self.assertLess(max(loads), 1.1 * sum(loads) / len(loads), f'{jobs} processes are balanced within 10 percent: {loads}')

    def test_every_hint_names_a_spec_and_new_specs_get_a_default(self):
        self.assertEqual(runner.coverage_problems(), [])
        groups = runner.split_specs(['tests/brand-new.spec.ts', 'tests/a11y-audit.spec.ts'], 2)
        self.assertEqual(sorted(len(group) for group in groups), [1, 1])

    def test_browser_processes_are_bounded_and_fall_back_conservatively(self):
        from unittest.mock import patch
        for cpus, expected in ((1, 1), (2, 1), (3, 2), (4, 3), (16, 3)):
            with patch.object(runner.os, 'cpu_count', return_value=cpus):
                self.assertEqual(runner.browser_jobs_value('auto', 1), expected, f'{cpus} CPUs')
        self.assertEqual(runner.browser_jobs_value('8', 1), runner.BROWSER_JOBS_MAX, 'never more than three')
        self.assertEqual(runner.browser_jobs_value('2', 1), 2)
        self.assertEqual(runner.browser_jobs_value(None, 1), 1, 'one process unless asked')
        with patch.dict(os.environ, {'SAP_LENS_BROWSER_JOBS': '2'}):
            self.assertEqual(runner.browser_jobs_value(None, 1), 2)
            self.assertEqual(runner.browser_jobs_value('1', 1), 1, 'the option wins over the environment')
        self.assertEqual(runner.jobs_value('auto', 'browser'), 1)

    def test_playwright_reports_are_summarised_per_test(self):
        report = {'suites': [{'file': 'a.spec.ts', 'suites': [{'specs': [{'file': 'a.spec.ts', 'title': 'slow', 'tests': [{'status': 'expected', 'results': [{'duration': 4000}]}]},
                                                                      {'file': 'a.spec.ts', 'title': 'broken', 'tests': [{'status': 'unexpected', 'results': [{'duration': 500}, {'duration': 250}]}]}]}]}]}
        self.assertEqual(runner.playwright_tests(report), [(4.0, 'a.spec.ts', 'slow', 'expected'), (0.75, 'a.spec.ts', 'broken', 'unexpected')])

    @unittest.skipIf(sys.platform == 'win32', 'process groups are POSIX')
    def test_cleanup_stops_only_the_processes_the_runner_started(self):
        owned = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
        stranger = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
        try:
            runner.OWNED.append(owned)
            runner.stop_owned(grace=10)
            self.assertIsNotNone(owned.poll(), 'the owned process was stopped')
            self.assertIsNone(stranger.poll(), 'a process the runner did not start is never signalled')
            self.assertEqual(runner.OWNED, [])
        finally:
            for process in (owned, stranger):
                if process.poll() is None:
                    process.kill()
                process.wait()


class ChangeSelectionTests(unittest.TestCase):
    """Fast Validation runs what a change can affect, and never less than the safe baseline for core changes."""
    def plan(self, *files):
        return runner.plan_changes(list(files))

    def test_paths_are_classified_and_unknown_paths_are_core(self):
        expected = {'docs/features/SOD.md': 'docs', 'README.md': 'docs', 'assets/sap-lens.png': 'docs', 'backend/tests/test_server.py': 'backend_tests',
                    'frontend/tests/a11y-audit.spec.ts': 'frontend_tests', 'frontend/src/components/Shared/Select.tsx': 'frontend', 'frontend/package-lock.json': 'frontend',
                    'frontend/vite.config.ts': 'frontend', 'backend/main.py': 'core', 'backend/routers/sod.py': 'core', 'scripts/run-tests.py': 'core', '.github/workflows/validate.yml': 'core',
                    'backend/requirements.txt': 'core', 'ruff.toml': 'core', 'compose.yml': 'core', 'deploy/linux/sap-lens.service': 'core', 'something/new/file.bin': 'core'}
        for path, category in expected.items():
            self.assertEqual(runner.classify(path), category, path)

    def test_documentation_only_changes_run_the_repository_checks_and_nothing_else(self):
        plan = self.plan('docs/deployment/BUILD.md', 'docs/validation/validation-items.csv', 'README.md')
        self.assertEqual((plan['backend'], plan['frontend'], plan['browser']), ('repository', False, False))
        self.assertIn('test_repository_integrity', plan['modules']); self.assertNotIn('test_sod_reports', plan['modules'])

    def test_backend_sources_scripts_workflows_and_dependencies_run_the_whole_backend(self):
        for path in ('backend/main.py', 'backend/routers/sod.py', 'backend/sod_reports.py', 'scripts/deployment-release.py', '.github/workflows/build-deployments.yml',
                     'backend/requirements-dev.txt', 'scripts/test-map.json', 'backend/tests/__init__.py', 'backend/tests/helpers.py', 'unknown.cfg'):
            with self.subTest(path=path):
                plan = self.plan(path)
                self.assertEqual(plan['backend'], 'full'); self.assertTrue(plan['reasons'])
        self.assertFalse(self.plan('backend/main.py')['frontend'])

    def test_a_changed_backend_test_module_runs_that_module_with_the_repository_checks(self):
        plan = self.plan('backend/tests/test_sod_reports.py', 'backend/tests/test_server.py')
        self.assertEqual(plan['backend'], 'modules'); self.assertIn('test_sod_reports', plan['modules']); self.assertIn('test_repository_integrity', plan['modules'])
        self.assertEqual(self.plan('backend/tests/test_deleted_long_ago.py')['backend'], 'repository', 'a deleted module has nothing to run')

    def test_frontend_changes_run_build_lint_and_browser_smoke_and_changed_specs(self):
        plan = self.plan('frontend/src/components/Shared/Select.tsx')
        self.assertEqual((plan['backend'], plan['frontend'], plan['browser'], plan['specs']), ('repository', True, True, []))
        plan = self.plan('frontend/tests/select-family.spec.ts', 'frontend/tests/sod-fixture.ts', 'frontend/tests/not-a-spec.spec.ts')
        self.assertEqual((plan['frontend'], plan['specs']), (True, ['select-family']), 'a spec runs itself; a helper or an unknown spec only triggers the smoke baseline')
        self.assertTrue(self.plan('frontend/package-lock.json')['browser'])

    def test_a_mixed_change_unions_the_needs_of_each_part(self):
        plan = self.plan('docs/x.md', 'frontend/src/App.tsx', 'backend/deployment.py')
        self.assertEqual((plan['backend'], plan['frontend'], plan['browser']), ('full', True, True))

    def test_an_unusable_base_selects_the_safe_baseline(self):
        for base in (None, '', '0' * 40, 'not-a-commit-at-all'):
            with self.subTest(base=base):
                plan = runner.plan_changes(runner.changed_files(base))
                self.assertEqual((plan['backend'], plan['frontend'], plan['browser']), ('full', True, True))
        self.assertTrue(runner.plan_changes(None)['reasons'])

    def test_changed_files_compares_with_a_real_commit(self):
        files = runner.changed_files('HEAD')
        self.assertIsInstance(files, list)  # the working tree against HEAD; empty or the current edits


if __name__ == '__main__':
    unittest.main()
