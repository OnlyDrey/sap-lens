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
server_spec = importlib.util.spec_from_file_location('serve_browser_tests', ROOT / 'scripts' / 'testing' / 'serve-browser-tests.py')
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
                # `tag: '@smoke'` or a list that includes it (`tag: ['@smoke', '@workflow']`), as Playwright accepts both
                if re.search(rf"tag:\s*(?:'{re.escape(tag)}'|\[[^\]]*'{re.escape(tag)}'[^\]]*\])", text):
                    owners.setdefault(feature, []).append(spec_name)
        for feature in ('dashboard', 'role-lookup', 'user-access', 'access-package', 'account-review', 'data-sources', 'sod', 'shared-ui', 'platform', 'role-comparison'):
            self.assertIn(feature, owners, f'no {tag} browser test for {feature}')

    def test_map_has_known_feature_descriptions_and_no_empty_features(self):
        for name, feature in runner.load_map()['features'].items():
            self.assertTrue(feature['description'], name)
            self.assertTrue(feature['backend'] or feature['browser'], name)


class QuietBackendRunnerTests(unittest.TestCase):
    """The backend worker is quiet on success, keeps every diagnostic of a failing test, reports leaks and fails with a non-zero exit code."""
    PROBE = (
        "import unittest\n"
        "class Probe(unittest.TestCase):\n"
        "    def test_expected_diagnostic(self):\n"
        "        print('EXPECTED-NOISE from a passing negative test')\n"
        "        import logging; logging.getLogger('sap-lens').warning('EXPECTED-WARNING retained previous data')\n"
        "    def test_failure_keeps_its_output(self):\n"
        "        print('FAILURE-CONTEXT printed before the failure')\n"
        "        self.fail('deliberate probe failure')\n"
        "    def test_leak(self):\n"
        "        open(__file__); import gc; gc.collect()\n")

    def run_worker(self, **env):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'probe_quiet_runner.py').write_text(self.PROBE, encoding='utf-8')
            out = Path(folder) / 'result.json'
            done = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'run-tests.py'), '_backend', str(out), 'probe_quiet_runner'],
                                  cwd=ROOT, capture_output=True, text=True, timeout=120, env={**os.environ, 'PYTHONPATH': folder, **env})
            import json
            return done, json.loads(out.read_text(encoding='utf-8'))

    def test_quiet_mode_hides_passing_output_but_keeps_failures_leaks_and_the_exit_code(self):
        done, data = self.run_worker()
        output = done.stdout + done.stderr
        self.assertNotIn('EXPECTED-NOISE', output); self.assertNotIn('EXPECTED-WARNING', output)
        self.assertIn('FAILURE-CONTEXT', output); self.assertIn('deliberate probe failure', output)
        self.assertEqual(done.returncode, 1); self.assertEqual((data['tests'], data['failures'], data['errors']), (3, 1, 0))
        self.assertTrue(any('unclosed file' in leak for leak in data['resource_warnings']), data['resource_warnings'])
        self.assertEqual(len(data['slowest']), 3)

    def test_verbose_mode_shows_everything(self):
        done, _ = self.run_worker(SAP_LENS_TEST_VERBOSE='1')
        output = done.stdout + done.stderr
        self.assertIn('EXPECTED-NOISE', output); self.assertIn('test_expected_diagnostic', output)

    def test_single_test_selection_and_log_file(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / 'run.log'
            done = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'run-tests.py'), 'targeted', '--test', 'test_test_profiles.TestProfileTests', '--log', str(log)],
                                  cwd=ROOT, capture_output=True, text=True, timeout=300)
            self.assertEqual(done.returncode, 0, done.stdout[-2000:] + done.stderr[-2000:])
            self.assertIn('backend selected tests', log.read_text(encoding='utf-8'))
        refused = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'run-tests.py'), 'regression', '--test', 'x'], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(refused.returncode, 0)


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
            process = subprocess.Popen([sys.executable, str(ROOT / 'scripts' / 'testing' / 'serve-browser-tests.py')], env=env,
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

    @unittest.skipIf(sys.platform == 'win32', 'process groups and SIGKILL semantics differ on Windows')
    def test_test_server_exits_and_removes_its_directory_when_its_parent_is_killed(self):
        """A SIGKILLed Playwright cannot run its own cleanup, so the server it started (via `exec`, as in playwright.config.ts) watches for it."""
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
        with tempfile.TemporaryDirectory() as root:
            env = {**os.environ, 'TMPDIR': root, 'SAP_LENS_BROWSER_TEST_PORT': str(port)}
            parent = subprocess.Popen(['sh', '-c', f'exec {sys.executable} -c "import subprocess,sys,time; subprocess.Popen([\'sh\',\'-c\',\'exec {sys.executable} {ROOT / "scripts" / "testing" / "serve-browser-tests.py"}\']); print(1, flush=True); time.sleep(120)"'],
                                      env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            try:
                parent.stdout.readline()
                deadline = time.time() + 30
                while time.time() < deadline and not list(Path(root).glob(f'{server.PREFIX}*/{server.OWNER_FILE}')):
                    time.sleep(0.1)
                markers = list(Path(root).glob(f'{server.PREFIX}*/{server.OWNER_FILE}'))
                self.assertEqual(len(markers), 1)
                pid = int(markers[0].read_text())
                parent.kill(); parent.wait()                                                       # no chance to clean up
                deadline = time.time() + 30
                while time.time() < deadline and (list(Path(root).glob(f'{server.PREFIX}*')) or runner.busy_ports_at(port)):
                    time.sleep(0.2)
                self.assertEqual(list(Path(root).glob(f'{server.PREFIX}*')), [], 'the storage directory was removed')
                self.assertFalse(runner.busy_ports_at(port), 'the port was released')
                def state_of() -> str:                                                           # a zombie awaiting an init that does not reap is already finished
                    try:
                        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0]
                    except OSError:
                        return 'gone'
                deadline = time.time() + 30
                while time.time() < deadline and state_of() not in {'Z', 'gone'}:
                    time.sleep(0.1)
                state = state_of()
                self.assertIn(state, {'Z', 'gone'}, 'the server process ended')
            finally:
                if parent.poll() is None:
                    parent.kill(); parent.wait()
                parent.stdout.close()                                                                # no unclosed pipe (ResourceWarning)

    @unittest.skipIf(sys.platform == 'win32', 'signals differ on Windows')
    def test_runner_stops_the_processes_it_started_when_it_receives_SIGTERM(self):
        script = (
            "import importlib.util,subprocess,sys,time\n"
            f"spec=importlib.util.spec_from_file_location('r','{ROOT / 'scripts' / 'run-tests.py'}');r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)\n"
            "with r.cleanup_on_signals():\n"
            "    child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'],start_new_session=True);r.OWNED.append(child)\n"
            "    print(child.pid,flush=True)\n"
            "    try:\n"
            "        time.sleep(120)\n"
            "    finally:\n"
            "        r.stop_owned()\n")
        process = subprocess.Popen([sys.executable, '-c', script], stdout=subprocess.PIPE, text=True)
        try:
            child = int(process.stdout.readline())
            process.send_signal(signal.SIGTERM)
            self.assertEqual(process.wait(30), 128 + signal.SIGTERM)
            deadline = time.time() + 20
            while time.time() < deadline:
                try:
                    os.kill(child, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.1)
            with self.assertRaises(ProcessLookupError):
                os.kill(child, 0)
        finally:
            if process.poll() is None:
                process.kill(); process.wait()
            process.stdout.close()

    def test_parallel_jobs_use_distinct_ports_and_storage(self):
        ports = [runner.BASE_PORT + index for index in range(runner.BROWSER_JOBS_MAX)]
        self.assertEqual(len(set(ports)), runner.BROWSER_JOBS_MAX)
        self.assertEqual(len({f'{server.PREFIX}{name}' for name in ('a', 'b')}), 2)
        text = (ROOT / 'scripts' / 'testing' / 'serve-browser-tests.py').read_text()
        self.assertIn('tempfile.TemporaryDirectory(prefix=PREFIX)', text, 'every server creates its own storage directory')
        self.assertIn("os.environ['SAP_LENS_CONFIG_DIR'] = directory", text)


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
        plan = self.plan('docs/deployment/RELEASES.md', 'docs/validation/validation-items.csv', 'README.md')
        self.assertEqual((plan['backend'], plan['frontend'], plan['browser']), ('repository', False, False))
        self.assertIn('test_repository_integrity', plan['modules']); self.assertNotIn('test_sod_reports', plan['modules'])

    def test_backend_sources_scripts_workflows_and_dependencies_run_the_whole_backend(self):
        for path in ('backend/main.py', 'backend/routers/sod.py', 'backend/sod_reports.py', 'scripts/deployment/deployment-release.py', '.github/workflows/build-deployments.yml',
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


class FrontendUnitTestWiringTests(unittest.TestCase):
    """Node unit tests were once present but executed by nothing; keep them reachable from the script and both validation workflows."""
    def test_unit_tests_are_run_by_the_package_script_and_the_workflows(self):
        import json
        files = sorted((ROOT / 'frontend/tests/unit').glob('*.test.ts'))
        self.assertTrue(files)
        script = json.loads((ROOT / 'frontend/package.json').read_text())['scripts']['test:unit']
        self.assertIn('tests/unit/*.test.ts', script)
        for workflow in ('validate.yml', 'full-validation.yml'):
            text = (ROOT / '.github/workflows' / workflow).read_text()
            self.assertIn('run unit -- npm --prefix frontend run test:unit', text, workflow)
            self.assertRegex(text, r'CI_(?:REQUIRED|OPTIONAL): [^\n]*\bunit\b', workflow)

    def test_frontend_source_and_unit_test_changes_run_the_frontend_stage_without_extra_specs(self):
        for path in ('frontend/src/lib/sessionState.ts', 'frontend/tests/unit/sod-bulk.test.ts'):
            plan = runner.plan_changes([path])
            self.assertTrue(plan['frontend'], path)   # the stage that now includes the unit step
            self.assertEqual(plan['specs'], [], path)  # no browser spec is named by these paths


if __name__ == '__main__':
    unittest.main()
