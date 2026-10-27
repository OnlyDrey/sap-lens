"""Real embedded HTTP lifecycle with only native GUI/Windows boundaries mocked."""
import json
import re
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


class WindowEvent:
    def __init__(self): self.handlers=[]
    def __iadd__(self, handler): self.handlers.append(handler); return self
    def wait(self, timeout): return True
    def set(self):
        for handler in self.handlers: handler()


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
        self.gui.FileDialog = types.SimpleNamespace(OPEN=10,SAVE=30)
        self.window = MagicMock()
        self.window.events = types.SimpleNamespace(loaded=WindowEvent(), closed=WindowEvent())
        self.navigate = MagicMock()
        def evaluate(script):
            if script.startswith('window.location.replace('):
                self.navigate(json.loads(script[len('window.location.replace('):-1]))
        self.window.evaluate_js.side_effect = evaluate
        self.gui_session = lambda **kwargs: None
        self.gui.create_window = MagicMock(return_value=self.window)
        self.gui.start = MagicMock(side_effect=self.drive_gui)
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

    def drive_gui(self, **kwargs):
        self.navigate.reset_mock()
        worker=threading.Thread(target=kwargs['func'], daemon=True)
        worker.start()
        deadline=time.monotonic()+3
        while not self.navigate.called and worker.is_alive() and time.monotonic()<deadline:
            time.sleep(.01)
        try: self.gui_session(**kwargs)
        finally:
            self.window.events.closed.set()
            worker.join(2)

    def session(self):
        url = self.navigate.call_args.args[0]
        parts = urlsplit(url)
        origin = f'{parts.scheme}://{parts.netloc}'
        token = parse_qs(parts.fragment)['session'][0]
        return origin, token

    def request(self, path, token=None):
        return build_opener(ProxyHandler({})).open(Request(path, headers={
            'X-SAP-Lens': token or '1'}), timeout=3)

    def verify_session(self, **kwargs):
        self.window.load_url.assert_not_called()
        self.assertTrue(any(call.args[0].startswith('window.location.replace(') for call in self.window.evaluate_js.call_args_list))
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
        ready = threading.Event()
        self.navigate.side_effect = lambda _url: ready.set()
        def verify_ready_session(**kwargs):
            # The generic GUI harness waits only three seconds. Repeated real
            # HTTP startups must wait for the actual load-url event instead of
            # closing a valid startup early on a busy runner. Production's
            # backend readiness deadline remains unchanged at fifteen seconds.
            self.assertTrue(ready.wait(15), 'The embedded service did not load its window.')
            self.verify_session(**kwargs)
        self.gui_session = verify_ready_session
        tokens = []
        for _ in range(3):
            ready.clear()
            result = desktop.run()
            category = None
            if result:
                # Only static stage/error-class labels, never URLs or log values.
                log = (self.root / 'sap-lens.log').read_text()
                category = re.findall(r'Desktop failure during ([^\n(]+) \((\w+)\)', log)
            self.assertEqual(result, 0, f'Repeated launch failure categories: {category}')
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
            self.gui_session = self.verify_session
            with patch.object(desktop, 'APP_PORT', port):
                self.assertEqual(desktop.run(), 0)
            self.assertNotEqual(urlsplit(self.session()[0]).port, port)
            unrelated.setblocking(False)
            with self.assertRaises(BlockingIOError):
                unrelated.accept()  # The launcher never probed this listener.
            self.assertEqual(unrelated.getsockname()[1], port)

    def test_gui_failure_cleans_up_server(self):
        self.gui_session = MagicMock(side_effect=RuntimeError('native failure'))
        self.assertEqual(desktop.run(), 1)
        origin, _ = self.session()
        with socket.socket() as check:
            self.assertNotEqual(check.connect_ex(('127.0.0.1', urlsplit(origin).port)), 0)
        self.assertFalse((self.root / 'runtime.json').exists())
        self.report.assert_called_once()

    def test_backend_failure_keeps_responsive_recovery_screen(self):
        with patch.object(desktop.ManagedBackend, 'start', side_effect=RuntimeError('not ready')):
            self.assertEqual(desktop.run(), 1)
        self.gui.create_window.assert_called_once()
        self.window.load_url.assert_not_called()
        self.assertIn('Startup needs attention', self.window.evaluate_js.call_args.args[0])
        self.report.assert_not_called()

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
        started, release, read_finished = threading.Event(), threading.Event(), threading.Event()
        os.environ['DATA_CSV_PATH'] = str(self.root / 'network.csv')
        config.get_settings.cache_clear()

        def stalled(*args, **kwargs):
            started.set()
            release.wait(5)
            read_finished.set()
            kwargs['before_commit']()

        def window(**kwargs):
            self.assertTrue(started.wait(1))
            self.assertFalse(read_finished.is_set(), 'Window waited for the stalled CSV reader')
            origin, _ = self.session()
            with self.request(origin + '/health') as response:
                self.assertEqual(json.load(response)['status'], 'loading')

        self.gui_session = window
        try:
            with patch('csv_lifecycle.load', side_effect=stalled):
                self.assertEqual(desktop.run(), 0)
                self.assertFalse(read_finished.is_set(), 'Shutdown waited for the stalled CSV reader')
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

    def test_native_logo_export_and_configuration_folder_are_guarded(self):
        bridge=desktop.NativeDialogs('private-token');bridge._window=self.window
        image=str(self.root/'synthetic.png')
        self.window.create_file_dialog.return_value=[image]
        self.assertEqual(bridge.choose_logo('private-token'),image)
        target=self.root/'synthetic.sap-lens.json'
        self.window.create_file_dialog.return_value=[str(target)]
        self.assertTrue(bridge.export_configuration('private-token',False))
        package=json.loads(target.read_text())
        self.assertEqual(package['settings']['organization']['name'],'Example Inc.')
        self.assertEqual(package['settings']['data_csv_path'],'')
        with patch.object(desktop,'is_windows',return_value=True),patch('desktop.os.startfile',create=True) as open_folder:
            self.assertTrue(bridge.open_configuration_folder('private-token'))
            open_folder.assert_called_once_with(str(self.root))
        for method in [bridge.choose_logo,bridge.open_configuration_folder,bridge.export_configuration]:
            with self.assertRaises(ValueError):method('not-the-token')

    def test_unexpected_backend_exit_reports_error_and_closes_owned_window(self):
        original=desktop.ManagedBackend
        managed=[]
        def factory(*args):
            instance=original(*args);managed.append(instance);return instance
        def gui_session(**kwargs):
            managed[0].server.should_exit=True
            managed[0].worker.join(2)
            deadline=time.monotonic()+2
            while not self.window.destroy.called and time.monotonic()<deadline: time.sleep(.01)
        self.gui_session=gui_session
        with patch.object(desktop,'ManagedBackend',side_effect=factory):
            self.assertEqual(desktop.run(),1)
        self.window.destroy.assert_called_once()
        self.assertIn('service stopped',self.report.call_args.args[0])

    def test_startup_timeout_is_visible_and_owned_listener_is_closed(self):
        # Do not let the generic GUI harness auto-close after three seconds before
        # the expected startup error is delivered on a loaded/slow test runner.
        visible_error = threading.Event()
        def record_script(script):
            if 'Startup needs attention' in script:
                visible_error.set()
        self.window.evaluate_js.side_effect = record_script
        self.gui_session = lambda **kwargs: self.assertTrue(visible_error.wait(10))
        with patch('urllib.request.OpenerDirector.open', side_effect=TimeoutError('synthetic connection timeout')):
            self.assertEqual(desktop.run(), 1)
        self.window.load_url.assert_not_called()
        script=self.window.evaluate_js.call_args.args[0]
        self.assertIn('Startup needs attention', script)
        self.assertNotIn('synthetic connection timeout', script)
        self.assertFalse((self.root/'runtime.json').exists())

    def test_closing_before_webview_load_does_not_wait_for_startup_timeout(self):
        def unloaded(timeout): time.sleep(.01);return False
        self.window.events.loaded.wait=unloaded
        def close_immediately(**kwargs):
            worker=threading.Thread(target=kwargs['func'],daemon=True);worker.start()
            self.window.events.closed.set();worker.join(.5)
            self.assertFalse(worker.is_alive())
        self.gui.start.side_effect=close_immediately
        with patch.object(desktop,'ManagedBackend') as managed:
            self.assertEqual(desktop.run(),0)
            managed.assert_not_called()
        self.window.load_url.assert_not_called()
        self.assertFalse((self.root/'runtime.json').exists())

    def test_csv_save_requires_capability_and_explicit_csv_destination(self):
        bridge = desktop.NativeDialogs('synthetic-capability')
        bridge._window = self.window
        filename = 'sap-lens-DEMO-all-2026-10-23.csv'
        content = '\ufeff"Username","User group","Full name"\r\n"DEMO","G","Synthetïc"\r\n'
        with self.assertRaises(ValueError):
            bridge.save_user_access_csv('wrong', filename, content)
        for bad in ['../' + filename, 'sap-lens.exe', None]:
            with self.assertRaises(ValueError):
                bridge.save_user_access_csv('synthetic-capability', bad, content)
        with self.assertRaises(ValueError):
            bridge.save_user_access_csv('synthetic-capability', filename, 'invalid')
        self.window.create_file_dialog.return_value = None
        self.assertFalse(bridge.save_user_access_csv('synthetic-capability', filename, content))
        for bad in ['relative.csv', str(self.root / 'not-csv.exe')]:
            self.window.create_file_dialog.return_value = [bad]
            with self.assertRaises(ValueError):
                bridge.save_user_access_csv('synthetic-capability', filename, content)
        target = self.root / 'Synthetïc export.csv'
        self.window.create_file_dialog.return_value = [str(target)]
        self.assertTrue(bridge.save_user_access_csv('synthetic-capability', filename, content))
        self.assertEqual(target.read_bytes(), content.encode('utf-8'))
        self.assertTrue(bridge._picker_lock.acquire(blocking=False))
        try:
            self.assertFalse(bridge.save_user_access_csv('synthetic-capability', filename, content))
        finally:
            bridge._picker_lock.release()

    def test_assignment_exports_reuse_only_the_exact_authenticated_native_contract(self):
        from csv_exports import ASSIGNMENT_HEADER
        bridge=desktop.NativeDialogs('synthetic-capability');bridge._window=self.window
        content=ASSIGNMENT_HEADER+'"SYN";"Åse";"Example";"";"G";"ZC:SYN:EN*";"";"";"Unknown";"";"";"";"No"\r\n'
        target=self.root/'Synthetic assignment export.csv';self.window.create_file_dialog.return_value=[str(target)]
        for kind in ['user-directory','release-roles']:
            name=f'sap-lens-{kind}-review-2026-10-26.csv'
            with self.assertRaises(ValueError):bridge.save_user_access_csv('wrong',name,content)
            with self.assertRaises(ValueError):bridge.save_user_access_csv('synthetic-capability',name,'\ufeff"Username","User group",')
            self.assertTrue(bridge.save_user_access_csv('synthetic-capability',name,content));self.assertEqual(target.read_bytes(),content.encode('utf-8'))
        with self.assertRaises(ValueError):bridge.save_user_access_csv('synthetic-capability','sap-lens-unrelated-review-2026-10-26.csv',content)

    def test_sod_export_native_contract_keeps_capability_header_and_destination_guards(self):
        from routers.sod_analysis import EXPORT_HEADER
        bridge=desktop.NativeDialogs('synthetic-capability');bridge._window=self.window
        content=EXPORT_HEADER+'"Synthetic evidence"\r\n'
        target=self.root/'Synthetic SoD export.csv';self.window.create_file_dialog.return_value=[str(target)]
        for kind in ('users','roles'):
            name=f'sap-lens-sod-{kind}-findings-2026-10-27.csv'
            with self.assertRaises(ValueError):bridge.save_sod_csv('wrong',name,content)
            with self.assertRaises(ValueError):bridge.save_sod_csv('synthetic-capability','../'+name,content)
            with self.assertRaises(ValueError):bridge.save_sod_csv('synthetic-capability',name,'unrelated header')
            self.assertTrue(bridge.save_sod_csv('synthetic-capability',name,content))
            self.assertEqual(target.read_bytes(),content.encode('utf-8'))
            with self.assertRaises(ValueError):bridge.save_user_access_csv('synthetic-capability',name,content)
        self.window.create_file_dialog.return_value=None
        self.assertFalse(bridge.save_sod_csv('synthetic-capability',name,content))
        with self.assertRaises(ValueError):bridge.save_sod_csv('synthetic-capability','sap-lens-sod-arbitrary-findings-2026-10-27.csv',content)

    def test_change_report_save_reuses_guarded_dialog_with_its_own_csv_contract(self):
        bridge=desktop.NativeDialogs('synthetic-capability');bridge._window=self.window
        filename='sap-lens-refresh-changes-report-2026-10-23.csv'
        content='\ufeff"Timestamp","Source","Change","Identifier","Field","Before","After"\r\n"2026-10-23","Employee Directory","modified","DEMO","Name","Example","Synthetïc"\r\n'
        with self.assertRaises(ValueError):bridge.save_refresh_changes_csv('wrong',filename,content)
        with self.assertRaises(ValueError):bridge.save_refresh_changes_csv('synthetic-capability','../'+filename,content)
        with self.assertRaises(ValueError):bridge.save_refresh_changes_csv('synthetic-capability',filename,'\ufeff"Username","User group",')
        with self.assertRaises(ValueError):bridge.save_user_access_csv('synthetic-capability',filename,content)
        self.window.create_file_dialog.return_value=None
        self.assertFalse(bridge.save_refresh_changes_csv('synthetic-capability',filename,content))
        target=self.root/'Synthetïc changes.csv';self.window.create_file_dialog.return_value=[str(target)]
        self.assertTrue(bridge.save_refresh_changes_csv('synthetic-capability',filename,content))
        self.assertEqual(target.read_bytes(),content.encode('utf-8'))

    def test_startup_close_and_log_actions_require_capability(self):
        bridge=desktop.NativeDialogs('synthetic-capability');bridge._window=self.window
        for method in [bridge.close_application,bridge.open_logs,bridge.export_diagnostics]:
            with self.assertRaises(ValueError):method('wrong')
        bridge.close_application('synthetic-capability')
        self.window.destroy.assert_called_once()
        (self.root/'sap-lens.log').write_text('synthetic safe log')
        with patch.object(desktop,'is_windows',return_value=True),patch('desktop.os.startfile',create=True) as open_log:
            self.assertTrue(bridge.open_logs('synthetic-capability'))
            open_log.assert_called_once_with(str(self.root/'sap-lens.log'))
        target=self.root/'diagnostics.json'
        self.window.create_file_dialog.return_value=[str(target)]
        self.assertTrue(bridge.export_diagnostics('synthetic-capability'))
        self.assertNotIn('application_directory',json.loads(target.read_text()))

    def test_startup_document_has_brand_status_and_no_external_resources(self):
        from startup_screen import startup_html
        document=startup_html(Path(__file__).resolve().parents[2]/'assets/sap-lens.png','synthetic-capability')
        self.assertIn('Starting backend',document)
        self.assertIn('data:image/png;base64,',document)
        self.assertIn('role="status"',document)
        self.assertIn('Close SAP Lens',document)
        self.assertNotIn('https://',document)
        self.assertNotIn('file://',document)

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
