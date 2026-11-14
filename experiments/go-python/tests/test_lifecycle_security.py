"""End-to-end host + bundled runtime on Linux: lifecycle, health, security boundary. Synthetic data, isolated temp dirs, bounded waits."""
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import support
from support import NAVIGATE, RUNTIME, Host, alive, children_of, request, wait_gone


def setUpModule():
    support.need_runtime(None)


class Lifecycle(unittest.TestCase):
    def test_ready_health_identity_and_clean_stop(self):
        with Host(extra=['--hold', '3s']) as host:
            status, body = request(host.url + '/health')
            self.assertEqual(status, 200)
            health = json.loads(body)
            self.assertEqual(health['app'], 'sap-lens')
            self.assertRegex(health['instance_id'], r'^[0-9a-f]{32}$')
            self.assertTrue(alive(host.backend_pid))
            self.assertEqual(host.process.wait(timeout=15), 0)
            self.assertTrue(wait_gone(host.backend_pid, 3))

    def test_sigterm_stops_backend_gracefully(self):
        with Host() as host:
            host.process.send_signal(signal.SIGTERM)
            self.assertEqual(host.process.wait(timeout=15), 0)
            self.assertTrue(wait_gone(host.backend_pid, 3))

    def test_sigint_stops_backend_gracefully(self):
        with Host() as host:
            host.process.send_signal(signal.SIGINT)
            self.assertEqual(host.process.wait(timeout=15), 0)
            self.assertTrue(wait_gone(host.backend_pid, 3))

    def test_sigkill_of_host_leaves_no_orphan(self):
        """Defence in depth: Pdeathsig and the stdin watchdog. The backend must disappear without any cooperation from the host."""
        with Host() as host:
            tree = [host.backend_pid, *children_of(host.backend_pid)]
            host.process.kill()
            host.process.wait()
            for pid in tree:
                self.assertTrue(wait_gone(pid, 10), f'pid {pid} outlived the host')

    def test_port_is_closed_after_stop(self):
        with Host(extra=['--exit-after-ready']) as host:
            port = int(host.url.rsplit(':', 1)[1])
            host.process.wait(timeout=20)
            with self.assertRaises(OSError):
                socket.create_connection(('127.0.0.1', port), timeout=1).close()

    def test_two_instances_get_distinct_ports_ids_and_capabilities(self):
        with Host() as one, Host() as two:
            self.assertNotEqual(one.url, two.url)
            a = json.loads(request(one.url + '/health')[1])['instance_id']
            b = json.loads(request(two.url + '/health')[1])['instance_id']
            self.assertNotEqual(a, b)
            page_a = request(one.url + '/', NAVIGATE)[1]
            page_b = request(two.url + '/', NAVIGATE)[1]
            self.assertNotEqual(page_a.split(b"'sap-lens-session',")[1][:60], page_b.split(b"'sap-lens-session',")[1][:60])


class StartupFailure(unittest.TestCase):
    def run_host(self, *args, timeout=40):
        return subprocess.run([str(support.HOST), *args], capture_output=True, text=True, timeout=timeout)

    def test_usage_error_exit_code(self):
        self.assertEqual(self.run_host().returncode, 1)

    def test_missing_runtime_is_a_start_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_host('--runtime', tmp + '/nope', '--data', tmp + '/data')
            self.assertEqual(result.returncode, 2)

    def test_data_directory_that_is_not_ours_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'foreign.txt').write_text('x')
            result = self.run_host('--runtime', str(RUNTIME), '--data', tmp)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(Path(tmp, 'foreign.txt').read_text(), 'x')

    def test_relative_data_directory_is_refused(self):
        result = self.run_host('--runtime', str(RUNTIME), '--data', 'relative/dir')
        self.assertEqual(result.returncode, 2)

    def test_start_timeout_kills_the_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            started = time.monotonic()
            result = self.run_host('--runtime', str(RUNTIME), '--data', tmp + '/d', '--start-timeout', '50ms')
            self.assertEqual(result.returncode, 3)
            self.assertLess(time.monotonic() - started, 10)
            time.sleep(0.5)
            leftovers = subprocess.run(['pgrep', '-f', tmp], capture_output=True, text=True).stdout.split()
            self.assertEqual(leftovers, [], 'backend left behind after start timeout')


class BackendRefusals(unittest.TestCase):
    """poc_backend run directly (no host): refuses anything but an isolated, marked directory and a valid handoff."""

    def run_backend(self, env_data, stdin='', timeout=30):
        python = RUNTIME / 'python' / 'bin' / 'python3'
        env = {'PATH': '/usr/bin:/bin'}
        if env_data is not None:
            env['SAP_LENS_POC_DATA'] = env_data
        return subprocess.run([str(python), '-I', '-m', 'poc_backend'], input=stdin, capture_output=True, text=True, env=env, timeout=timeout)

    def test_no_data_variable_is_refused(self):
        self.assertEqual(self.run_backend(None).returncode, 10)

    def test_relative_path_is_refused(self):
        self.assertEqual(self.run_backend('relative').returncode, 10)

    def test_directory_without_marker_is_refused_and_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_backend(tmp).returncode, 10)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_marker_symlink_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp, 'real')
            real.write_text('sap-lens-poc-v1\n')
            os.symlink(real, Path(tmp, '.sap-lens-poc'))
            self.assertEqual(self.run_backend(tmp).returncode, 10)

    def test_invalid_handoffs_are_refused_without_echo(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, '.sap-lens-poc').write_text('sap-lens-poc-v1\n')
            secret = 'short-secret'
            for line in ('', 'not json\n', json.dumps({'capability': secret, 'instance_id': 'x' * 32}) + '\n',
                         json.dumps({'capability': 'A' * 43, 'instance_id': 'zz'}) + '\n', json.dumps({'capability': 'A' * 43}) + '\n'):
                result = self.run_backend(tmp, line)
                self.assertEqual(result.returncode, 11, line)
                self.assertNotIn(secret, result.stdout + result.stderr)
                self.assertNotIn('listening', result.stdout)


class SecurityBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.host = Host().start()

    @classmethod
    def tearDownClass(cls):
        cls.host.process.terminate()
        cls.host.process.wait(timeout=15)
        cls.host.__exit__()

    def session(self):
        page = request(self.host.url + '/', NAVIGATE)[1].decode()
        return page.split("'sap-lens-session',\"")[1].split('"')[0]

    def test_frontend_is_served_to_navigation_requests(self):
        status, body = request(self.host.url + '/', NAVIGATE)
        self.assertEqual(status, 200)
        self.assertIn(b'<div id="root"', body)

    def test_api_without_capability_is_forbidden(self):
        self.assertEqual(request(self.host.url + '/api/configuration')[0], 403)

    def test_api_with_wrong_capability_is_forbidden(self):
        # The backend reads the capability from X-SAP-Lens. (Phase 0 originally used a wrong header name, so this passed vacuously; the positive control below prevents that.)
        self.assertEqual(request(self.host.url + '/api/settings', {'X-SAP-Lens': 'A' * 43})[0], 403)

    def test_api_with_the_issued_capability_is_accepted(self):
        self.assertEqual(request(self.host.url + '/api/settings', {'X-SAP-Lens': self.session()})[0], 200)

    def test_foreign_host_header_is_forbidden(self):
        self.assertEqual(request(self.host.url + '/health', {'Host': 'evil.example'})[0], 403)
        self.assertEqual(request(self.host.url + '/', {**NAVIGATE, 'Host': 'evil.example'})[0], 403)

    def test_foreign_origin_is_forbidden(self):
        self.assertEqual(request(self.host.url + '/api/configuration', {'Origin': 'http://evil.example'})[0], 403)

    def test_listener_is_loopback_only(self):
        port = int(self.host.url.rsplit(':', 1)[1])
        listening = [line for line in Path('/proc/net/tcp').read_text().splitlines()[1:] if line.split()[1].endswith(f':{port:04X}') and line.split()[3] == '0A']
        self.assertEqual(len(listening), 1)
        self.assertTrue(listening[0].split()[1].startswith('0100007F'), listening[0])
        v6 = Path('/proc/net/tcp6').read_text().splitlines()[1:] if Path('/proc/net/tcp6').exists() else []
        self.assertEqual([l for l in v6 if l.split()[1].endswith(f':{port:04X}') and l.split()[3] == '0A'], [])

    def test_no_secret_in_arguments_environment_or_files(self):
        capability = self.session()
        for pid in (self.host.process.pid, self.host.backend_pid):
            cmdline = Path(f'/proc/{pid}/cmdline').read_bytes().decode(errors='replace')
            self.assertNotIn(capability, cmdline)
            try:
                environ = Path(f'/proc/{pid}/environ').read_bytes().decode(errors='replace')
            except OSError:
                continue
            self.assertNotIn(capability, environ)
        for path in Path(self.host.data).rglob('*'):
            if path.is_file():
                self.assertNotIn(capability.encode(), path.read_bytes(), str(path))

    def test_child_environment_is_minimal(self):
        environ = Path(f'/proc/{self.host.backend_pid}/environ').read_bytes().decode().split('\0')
        names = {e.split('=', 1)[0] for e in environ if e}
        self.assertTrue(names <= {'PATH', 'HOME', 'TMPDIR', 'TEMP', 'TMP', 'LANG', 'LC_ALL', 'PYTHONUTF8', 'PYTHONIOENCODING', 'PYTHONDONTWRITEBYTECODE',
                                  'SAP_LENS_POC_DATA', 'PYTHONNOUSERSITE', 'SystemRoot'}, names)
        for forbidden in ('HTTPS_PROXY', 'HTTP_PROXY', 'GITHUB_TOKEN', 'ANTHROPIC_API_KEY', 'SSH_AUTH_SOCK'):
            self.assertNotIn(forbidden, names)

    def test_data_stays_inside_the_isolated_directory(self):
        marker = Path(self.host.data, '.sap-lens-poc')
        self.assertEqual(marker.read_text(), 'sap-lens-poc-v1\n')
        self.assertEqual(oct(Path(self.host.data).stat().st_mode & 0o777), '0o700')
        home = Path.home()
        for suspicious in (home / '.sap-lens', home / '.config' / 'sap-lens', Path('/var/lib/sap-lens')):
            self.assertFalse(suspicious.exists() and suspicious.stat().st_mtime > time.time() - 120, f'{suspicious} touched')

    def test_runtime_tree_is_not_written_by_the_backend(self):
        from common import verify_tree
        self.assertEqual(verify_tree(RUNTIME), [])


if __name__ == '__main__':
    unittest.main()
