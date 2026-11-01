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


if __name__ == '__main__':
    unittest.main()
