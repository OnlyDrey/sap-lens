"""Real embedded HTTP lifecycle with only native GUI/Windows boundaries mocked."""
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs, urlsplit
from urllib.request import ProxyHandler, Request, build_opener
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cache
import config
import desktop
from main import create_app
from fastapi.testclient import TestClient
from instance import WindowsInstance
from windows_runtime import webview2_available


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {
            'SAP_LENS_CONFIG_DIR': str(self.root), 'DATA_CSV_PATH': '',
        })
        self.environment.start()
        config.get_settings.cache_clear()
        cache._cache = cache._CacheState()
        self.gui = types.ModuleType('webview')
        self.gui.settings = {}
        self.gui.FileDialog = types.SimpleNamespace(OPEN=10)
        self.window = MagicMock()
        self.gui.create_window = MagicMock(return_value=self.window)
        self.gui.start = MagicMock()
        self.native = patch.dict(sys.modules, {'webview': self.gui})
        self.native.start()
        self.platform = patch.object(desktop, 'is_windows', return_value=False)
        self.platform.start()
        self.resource = patch('main.frontend_dir', self.root)
        self.resource.start()
        self.error = patch.object(desktop, 'report_error')
        self.report = self.error.start()

    def tearDown(self):
        self.error.stop()
        self.resource.stop()
        self.platform.stop()
        self.native.stop()
        self.environment.stop()
        config.get_settings.cache_clear()
        self.temp.cleanup()

    def session(self):
        url = self.gui.create_window.call_args.args[1]
        parts = urlsplit(url)
        origin = f'{parts.scheme}://{parts.netloc}'
        token = parse_qs(parts.fragment)['session'][0]
        return origin, token

    def request(self, path, token=None):
        return build_opener(ProxyHandler({})).open(Request(path, headers={
            'X-SAP-Lens': token or '1'}), timeout=3)

    def verify_session(self, **kwargs):
        origin, token = self.session()
        with self.request(origin + '/health') as response:
            health = json.load(response)
        runtime = json.loads((self.root / 'runtime.json').read_text())
        self.assertEqual(health['app'], 'sap-lens')
        self.assertEqual(health['instance_id'], runtime['instance_id'])
        self.assertEqual(runtime['pid'], os.getpid())
        self.assertNotIn(token, (self.root / 'runtime.json').read_text())
        self.assertNotIn(token, (self.root / 'sap-lens.log').read_text())
        with self.request(origin + '/api/settings', token) as response:
            self.assertIn('data_csv_path', json.load(response))
        with self.assertRaises(HTTPError) as error:
            self.request(origin + '/api/settings')
        self.assertEqual(error.exception.code, 403)

    def test_repeated_window_launch_and_shutdown(self):
        self.gui.start.side_effect = self.verify_session
        tokens = []
        for _ in range(3):
            self.assertEqual(desktop.run(), 0)
            origin, token = self.session()
            tokens.append(token)
            with socket.socket() as check:
                self.assertNotEqual(check.connect_ex(('127.0.0.1', urlsplit(origin).port)), 0)
            self.assertFalse((self.root / 'runtime.json').exists())
        self.assertEqual(len(set(tokens)), 3)
        self.report.assert_not_called()

    def test_occupied_port_is_not_contacted_or_terminated(self):
        with socket.socket() as unrelated:
            unrelated.bind(('127.0.0.1', 0))
            unrelated.listen()
            port = unrelated.getsockname()[1]
            self.gui.start.side_effect = self.verify_session
            with patch.object(desktop, 'APP_PORT', port):
                self.assertEqual(desktop.run(), 0)
            self.assertNotEqual(urlsplit(self.session()[0]).port, port)
            unrelated.setblocking(False)
            with self.assertRaises(BlockingIOError):
                unrelated.accept()  # The launcher never probed this listener.
            self.assertEqual(unrelated.getsockname()[1], port)

    def test_gui_failure_cleans_up_server(self):
        self.gui.start.side_effect = RuntimeError('native failure')
        self.assertEqual(desktop.run(), 1)
        origin, _ = self.session()
        with socket.socket() as check:
            self.assertNotEqual(check.connect_ex(('127.0.0.1', urlsplit(origin).port)), 0)
        self.assertFalse((self.root / 'runtime.json').exists())
        self.report.assert_called_once()

    def test_backend_failure_does_not_open_a_window(self):
        with patch.object(desktop.ManagedBackend, 'start', side_effect=RuntimeError('not ready')):
            self.assertEqual(desktop.run(), 1)
        self.gui.create_window.assert_not_called()
        self.report.assert_called_once()

    def test_duplicate_launch_activates_without_starting_backend(self):
        guard = MagicMock()
        guard.acquire.return_value = False
        with patch.object(desktop, 'is_windows', return_value=True), \
             patch.object(desktop, 'WindowsInstance', return_value=guard), \
             patch.object(desktop, 'activate_existing_window', return_value=True) as activate, \
             patch.object(desktop, 'reserve_listener') as reserve:
            self.assertEqual(desktop.run(), 0)
        activate.assert_called_once()
        reserve.assert_not_called()
        guard.close.assert_called_once()
        self.gui.create_window.assert_not_called()

    def test_missing_webview_runtime_is_explained_without_server(self):
        guard = MagicMock()
        with patch.object(desktop, 'is_windows', return_value=True), \
             patch.object(desktop, 'WindowsInstance', return_value=guard), \
             patch.object(desktop, 'webview2_available', return_value=False), \
             patch.object(desktop, 'reserve_listener') as reserve:
            self.assertEqual(desktop.run(), 1)
        self.assertIn('Evergreen WebView2 Runtime', self.report.call_args.args[0])
        reserve.assert_not_called()
        guard.close.assert_called_once()

    def test_stalled_initial_csv_does_not_prevent_window_or_exit(self):
        started, release = threading.Event(), threading.Event()
        os.environ['DATA_CSV_PATH'] = str(self.root / 'network.csv')
        config.get_settings.cache_clear()

        def stalled(*args, **kwargs):
            started.set()
            release.wait(5)
            kwargs['before_commit']()

        def window(**kwargs):
            self.assertTrue(started.wait(1))
            origin, _ = self.session()
            with self.request(origin + '/health') as response:
                self.assertEqual(json.load(response)['status'], 'loading')

        self.gui.start.side_effect = window
        try:
            with patch('cache.load_cache', side_effect=stalled):
                start = time.monotonic()
                self.assertEqual(desktop.run(), 0)
                self.assertLess(time.monotonic() - start, 2)
        finally:
            release.set()

    def test_native_picker_selection_cancel_and_authorization(self):
        bridge = desktop.NativeDialogs('private-token')
        bridge._window = self.window
        self.window.create_file_dialog.return_value = [str(self.root / 'chosen.csv')]
        self.assertTrue(bridge.choose_csv('private-token').endswith('chosen.csv'))
        self.window.create_file_dialog.return_value = None
        self.assertIsNone(bridge.choose_csv('private-token'))
        count = self.window.create_file_dialog.call_count
        for bad in ['wrong', 'é', None]:
            with self.assertRaises(ValueError):
                bridge.choose_csv(bad)
        self.assertEqual(self.window.create_file_dialog.call_count, count)

    def test_dynamic_origin_and_launch_capability(self):
        app = create_app(origin='http://127.0.0.1:41234', session_token='secret-session')
        with TestClient(app, base_url='http://127.0.0.1:41234') as client:
            for origin in ['http://localhost:41234', 'http://127.0.0.1:18743', 'https://example.com']:
                self.assertEqual(client.get('/api/settings', headers={
                    'Origin': origin, 'X-SAP-Lens': 'secret-session'}).status_code, 403)
            self.assertEqual(client.get('/api/settings').status_code, 403)
            allowed = client.get('/api/settings', headers={
                'Origin': 'http://127.0.0.1:41234', 'X-SAP-Lens': 'secret-session'})
            self.assertEqual(allowed.status_code, 200)
            self.assertEqual(allowed.headers['access-control-allow-origin'], 'http://127.0.0.1:41234')
        for origin in ['*', 'https://example.com', 'http://127.0.0.1:41234/evil']:
            with self.assertRaises(ValueError):
                create_app(origin=origin)

    def test_windows_mutex_new_duplicate_and_release(self):
        kernel = MagicMock()
        kernel.CreateMutexW.return_value = 123
        guard = WindowsInstance(kernel)
        with patch('ctypes.get_last_error', return_value=0, create=True):
            self.assertTrue(guard.acquire())
        guard.close()
        guard.close()
        kernel.CloseHandle.assert_called_once_with(123)
        with patch('ctypes.get_last_error', return_value=183, create=True):
            self.assertFalse(guard.acquire())
        guard.close()

    def test_webview2_registry_check(self):
        registry = MagicMock()
        registry.QueryValueEx.return_value = ('130.0.1.2', 1)
        self.assertTrue(webview2_available(registry))
        registry.OpenKey.side_effect = FileNotFoundError
        self.assertFalse(webview2_available(registry))


if __name__ == '__main__':
    unittest.main()
