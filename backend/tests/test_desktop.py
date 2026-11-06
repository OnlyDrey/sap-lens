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


def wait_until(condition, describe, limit=20.0):
    """Condition wait for asynchronous shutdown. It returns as soon as the condition holds (a passing run is not slower) and only the
    failure path waits up to `limit`; the old fixed 2 s / 5 s windows raced uvicorn shutdown on a loaded Windows host. Failure names the state."""
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(.01)
    raise AssertionError('Timed out waiting for ' + describe())


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
            wait_until(lambda:not managed[0].worker.is_alive(),lambda:'the backend worker to stop after should_exit')
            wait_until(lambda:self.window.destroy.called,lambda:'the owned window to be destroyed after the backend stopped unexpectedly')
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
        with patch.dict(os.environ, {'SAP_LENS_DESKTOP_STARTUP_TIMEOUT':'1'}), patch('urllib.request.OpenerDirector.open', side_effect=TimeoutError('synthetic connection timeout')):
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

    def test_role_package_export_uses_the_native_save_contract(self):
        from routers.roles import PACKAGE_HEADER
        bridge=desktop.NativeDialogs('synthetic-capability');bridge._window=self.window
        target=self.root/'Synthetic package.csv';self.window.create_file_dialog.return_value=[str(target)]
        name='sap-lens-access-package-2026-10-28.csv';content=PACKAGE_HEADER+'"ZC:MM:BUY:ENS";"Synthetic";"ENS";"Confirmed"\r\n'
        with self.assertRaises(ValueError):bridge.save_role_package_csv('wrong',name,content)
        with self.assertRaises(ValueError):bridge.save_role_package_csv('synthetic-capability',name,'unrelated header')
        with self.assertRaises(ValueError):bridge.save_role_package_csv('synthetic-capability','sap-lens-sod-explorer-user-risk-2026-10-28.csv',content)
        self.assertTrue(bridge.save_role_package_csv('synthetic-capability',name,content));self.assertEqual(target.read_bytes(),content.encode('utf-8'))

    def test_sod_group_heatmap_export_uses_the_native_save_contract(self):
        from routers.sod_governance import HEATMAP_COLUMNS, csv_header
        bridge=desktop.NativeDialogs('synthetic-capability');bridge._window=self.window
        target=self.root/'Synthetic heatmap.csv';self.window.create_file_dialog.return_value=[str(target)]
        name='sap-lens-sod-group-risk-heatmap-2026-10-28.csv';content=csv_header(HEATMAP_COLUMNS['risk'])+'"FIN";"R1";"1";"1"\r\n'
        with self.assertRaises(ValueError):bridge.save_sod_csv('synthetic-capability',name,'unrelated header')
        with self.assertRaises(ValueError):bridge.save_sod_csv('synthetic-capability','sap-lens-sod-group-other-heatmap-2026-10-28.csv',content)
        self.assertTrue(bridge.save_sod_csv('synthetic-capability',name,content));self.assertEqual(target.read_bytes(),content.encode('utf-8'))

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
        from routers.sod import CATALOGUE_HEADER
        catalogue_name='sap-lens-sod-catalogue-2026-10-27.csv'
        self.assertTrue(bridge.save_sod_csv('synthetic-capability',catalogue_name,CATALOGUE_HEADER))
        self.assertEqual(target.read_bytes(),CATALOGUE_HEADER.encode('utf-8'))
        with self.assertRaises(ValueError):bridge.save_sod_csv('synthetic-capability',catalogue_name,content)
        self.window.create_file_dialog.return_value=None
        self.assertFalse(bridge.save_sod_csv('synthetic-capability',name,content))
        with self.assertRaises(ValueError):bridge.save_sod_csv('synthetic-capability','sap-lens-sod-arbitrary-findings-2026-10-27.csv',content)

    def test_sod_governance_exports_use_fixed_native_names_and_headers(self):
        import base64
        from routers.sod_governance import native_csv_header
        bridge=desktop.NativeDialogs('synthetic-capability');bridge._window=self.window
        target=self.root/'Synthetic governance export.csv';self.window.create_file_dialog.return_value=[str(target)]
        for stem in ('explorer-user-risk','explorer-user-activity','explorer-access-list','explorer-lookup','review-queue','access-remediation'):
            name=f'sap-lens-sod-{stem}-2026-10-27.csv';header=native_csv_header(name)
            self.assertTrue(header.startswith('\ufeff"'))
            self.assertTrue(bridge.save_sod_csv('synthetic-capability',name,header+'"Synthetic"\r\n'))
            with self.assertRaises(ValueError):bridge.save_sod_csv('synthetic-capability',name,'\ufeff"Other"\r\n')
        self.assertIsNone(native_csv_header('sap-lens-sod-explorer-other-2026-10-27.csv'))
        with self.assertRaises(ValueError):bridge.save_sod_csv('synthetic-capability','sap-lens-sod-explorer-other-2026-10-27.csv','x')
        with self.assertRaises(ValueError):bridge.save_sod_csv('synthetic-capability','../sap-lens-sod-review-queue-2026-10-27.csv',native_csv_header('sap-lens-sod-review-queue-2026-10-27.csv'))
        payload=b'%PDF-1.4\nSynthetic remediation\n%%EOF';encoded=base64.b64encode(payload).decode()
        self.window.create_file_dialog.return_value=[str(self.root/'Synthetic remediation.pdf')]
        for context in ('current','b'*32):
            self.assertTrue(bridge.save_sod_document('synthetic-capability',f'sap-lens-access-remediation-{context}-2026-10-27.pdf',encoded))
        with self.assertRaises(ValueError):bridge.save_sod_document('synthetic-capability','sap-lens-access-remediation-other-2026-10-27.pdf',encoded)

    def test_reference_template_and_repository_native_boundaries(self):
        import base64
        from sod_reference import default_path
        bridge=desktop.NativeDialogs('synthetic-capability');bridge._window=self.window
        target=self.root/'template.xlsx';self.window.create_file_dialog.return_value=[str(target)]
        payload=default_path().with_name('sod-reference-template.xlsx').read_bytes()
        name='sap-lens-sod-reference-template.xlsx'
        self.assertTrue(bridge.save_sod_document('synthetic-capability',name,base64.b64encode(payload).decode()))
        self.assertEqual(target.read_bytes(),payload)
        with self.assertRaises(ValueError):bridge.save_sod_document('synthetic-capability',name,base64.b64encode(b'PKinvalid').decode())
        with patch('webbrowser.open',return_value=True) as opened:
            with self.assertRaises(ValueError):bridge.open_project_repository('wrong')
            opened.assert_not_called()
            self.assertTrue(bridge.open_project_repository('synthetic-capability'))
            opened.assert_called_once_with('https://github.com/OnlyDrey/sap-lens')

    def test_sod_document_save_keeps_fixed_formats_and_capability_boundary(self):
        import base64
        from io import BytesIO
        from zipfile import ZipFile
        bridge=desktop.NativeDialogs('synthetic-capability');bridge._window=self.window
        for kind,payload in [('pdf',b'%PDF-1.4\nSynthetic report\n%%EOF')]:
            name='sap-lens-sod-report-'+'a'*32+'-2026-10-27.'+kind
            encoded=base64.b64encode(payload).decode();target=self.root/('synthetic.'+kind);self.window.create_file_dialog.return_value=[str(target)]
            with self.assertRaises(ValueError):bridge.save_sod_document('wrong',name,encoded)
            with self.assertRaises(ValueError):bridge.save_sod_document('synthetic-capability','../'+name,encoded)
            with self.assertRaises(ValueError):bridge.save_sod_document('synthetic-capability',name,base64.b64encode(b'invalid').decode())
            self.assertTrue(bridge.save_sod_document('synthetic-capability',name,encoded));self.assertEqual(target.read_bytes(),payload)
            self.window.create_file_dialog.return_value=None;self.assertFalse(bridge.save_sod_document('synthetic-capability',name,encoded))
        stream=BytesIO()
        with ZipFile(stream,'w') as archive:
            archive.writestr('[Content_Types].xml','<Types/>');archive.writestr('word/document.xml','<document/>');archive.writestr('_rels/.rels','<Relationships/>')
        name='sap-lens-sod-report-'+'a'*32+'-2026-10-27.docx';target=self.root/'synthetic.docx';self.window.create_file_dialog.return_value=[str(target)]
        self.assertTrue(bridge.save_sod_document('synthetic-capability',name,base64.b64encode(stream.getvalue()).decode()))
        with ZipFile(stream,'a') as archive:archive.writestr('word/vbaProject.bin',b'invalid macro')
        with self.assertRaises(ValueError):bridge.save_sod_document('synthetic-capability',name,base64.b64encode(stream.getvalue()).decode())

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

    def probe_backend(self):
        backend = desktop.ManagedBackend(MagicMock(), desktop.reserve_listener(0))
        self.addCleanup(backend.listener.close)
        backend.worker = MagicMock()
        backend.worker.is_alive.return_value = True
        return backend

    def health_response(self, value=None):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = json.dumps(value or {'app':'sap-lens','instance_id':'synthetic','status':'loading'}).encode()
        return response

    def test_readiness_retries_transient_failures_then_checks_owned_identity(self):
        from urllib.error import URLError
        backend = self.probe_backend()
        canceled = threading.Event()
        with patch('urllib.request.OpenerDirector.open', side_effect=[URLError('synthetic'), TimeoutError(), self.health_response()]) as probe:
            backend.wait_ready('http://127.0.0.1:12345','synthetic',time.monotonic()+2,canceled,MagicMock())
        self.assertEqual(probe.call_count,3)
        self.assertTrue(all(call.kwargs['timeout'] <= .5 for call in probe.call_args_list))

    def test_readiness_rejects_wrong_identity_and_malformed_content(self):
        backend = self.probe_backend()
        for value in ({'app':'other','instance_id':'synthetic'}, {'app':'sap-lens','instance_id':'other'}, ['not-health'], {'app':'sap-lens','instance_id':'synthetic','status':'unexpected'}):
            with self.subTest(value=value), patch('urllib.request.OpenerDirector.open', return_value=self.health_response(value)):
                with self.assertRaises(desktop.StartupFailure) as failure:
                    backend.wait_ready('http://127.0.0.1:12345','synthetic',time.monotonic()+1,threading.Event(),MagicMock())
                self.assertEqual(failure.exception.code,'UNEXPECTED_SERVICE')

    def test_readiness_detects_worker_exit_before_during_and_after_probe(self):
        from urllib.error import URLError
        for alive,response in (([False],self.health_response()),([True,False],URLError('synthetic')),([True,False],self.health_response())):
            backend=self.probe_backend();backend.worker.is_alive.side_effect=alive
            with patch('urllib.request.OpenerDirector.open',side_effect=[response] if isinstance(response,Exception) else None,return_value=response):
                with self.assertRaises(desktop.StartupFailure) as failure:
                    backend.wait_ready('http://127.0.0.1:12345','synthetic',time.monotonic()+1,threading.Event(),MagicMock())
                self.assertEqual(failure.exception.code,'BACKEND_EXITED')

    def test_readiness_never_follows_redirect_to_another_service(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        backend=self.probe_backend()
        with socket.socket() as unrelated:
            unrelated.bind(('127.0.0.1',0));unrelated.listen();unrelated.setblocking(False)
            target=unrelated.getsockname()[1]
            class Redirect(BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(302);self.send_header('Location',f'http://127.0.0.1:{target}/health');self.end_headers()
                def log_message(self,*args):pass
            server=HTTPServer(('127.0.0.1',0),Redirect)
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            try:
                with self.assertRaises(desktop.StartupFailure) as failure:
                    backend.wait_ready(f'http://127.0.0.1:{server.server_port}','synthetic',time.monotonic()+2,threading.Event(),MagicMock())
                self.assertEqual(failure.exception.code,'UNEXPECTED_SERVICE')
                with self.assertRaises(BlockingIOError):unrelated.accept()
            finally:server.shutdown();server.server_close();worker.join(2)

    def test_readiness_deadline_is_bounded_without_real_time_waits(self):
        from urllib.error import URLError
        backend=self.probe_backend();clock=[0.0];canceled=MagicMock();canceled.is_set.return_value=False
        canceled.wait.side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
        with patch.object(desktop.time,'monotonic',side_effect=lambda:clock[0]), patch('urllib.request.OpenerDirector.open',side_effect=URLError('synthetic')) as probe:
            with self.assertRaises(desktop.StartupFailure) as failure:
                backend.wait_ready('http://127.0.0.1:12345','synthetic',.25,canceled,MagicMock())
        self.assertEqual(failure.exception.code,'READINESS_TIMEOUT')
        self.assertEqual(probe.call_count,3)
        self.assertAlmostEqual(clock[0],.25)

    def test_slow_initialization_and_early_exit_are_distinct(self):
        backend=self.probe_backend();backend.server.started=False
        clock=[0.0];canceled=MagicMock();canceled.is_set.return_value=False
        def advance(seconds):
            clock[0]+=seconds
            if clock[0]>=.075:backend.server.started=True
        canceled.wait.side_effect=advance
        with patch.object(desktop.time,'monotonic',side_effect=lambda:clock[0]):backend.start(timeout=1,canceled=canceled)
        self.assertTrue(backend.server.started)
        backend=self.probe_backend();backend.worker.is_alive.return_value=False
        with self.assertRaises(desktop.StartupFailure) as failure:backend.start()
        self.assertEqual(failure.exception.code,'BACKEND_EXITED')

    def test_startup_timeout_configuration_rejects_invalid_values(self):
        for value in ('0','181','nan','inf','text'):
            with self.subTest(value=value),patch.dict(os.environ,{'SAP_LENS_DESKTOP_STARTUP_TIMEOUT':value}):
                with self.assertRaises(desktop.StartupFailure):desktop.startup_timeout()
        with patch.dict(os.environ,{'SAP_LENS_DESKTOP_STARTUP_TIMEOUT':'42'}):self.assertEqual(desktop.startup_timeout(),42)

    def test_retry_stops_old_backend_and_uses_fresh_owned_instance(self):
        failed=threading.Event();real_start=desktop.ManagedBackend.start;attempts=[]
        def start(backend,*args,**kwargs):
            attempts.append(backend)
            if len(attempts)==1:raise desktop.StartupFailure('SYNTHETIC_FAILURE','A recoverable synthetic startup failure.')
            return real_start(backend,*args,**kwargs)
        original=self.window.evaluate_js.side_effect
        def evaluate(script):
            original(script)
            if 'Startup needs attention' in script:failed.set()
        self.window.evaluate_js.side_effect=evaluate
        def session(**kwargs):
            self.assertTrue(failed.wait(5))
            bridge=self.gui.create_window.call_args.kwargs['js_api']
            self.assertTrue(bridge.retry_startup(bridge._token))
            self.assertFalse(bridge.retry_startup(bridge._token))
            wait_until(lambda:self.navigate.called,lambda:'navigation to the fresh backend after retry')
            self.verify_session()
            self.assertEqual(len(attempts),2)
            wait_until(lambda:not attempts[0].worker.is_alive(),lambda:'the failed first backend worker to stop')
        self.gui_session=session
        with patch.object(desktop.ManagedBackend,'start',start):self.assertEqual(desktop.run(),0)
        wait_until(lambda:all(not backend.worker.is_alive() and backend.listener.fileno()==-1 for backend in attempts),
                   lambda:'every owned backend to stop and release its listener: '+repr([(backend.worker.is_alive(),backend.listener.fileno()) for backend in attempts]))

    def test_initialization_failures_are_logged_without_sensitive_values(self):
        import main
        import scheduler
        for target in ('configuration','storage','scheduler'):
            with self.subTest(target=target):
                self.navigate.reset_mock()
                if target=='configuration':boundary=patch.object(config,'get_settings',side_effect=ValueError('synthetic-private-value'))
                elif target=='storage':boundary=patch.object(main,'DataLoader',side_effect=OSError('synthetic-private-value'))
                else:boundary=patch.object(scheduler,'Scheduler',side_effect=RuntimeError('synthetic-private-value'))
                with boundary:self.assertEqual(desktop.run(),1)
                text=(self.root/'sap-lens.log').read_text()
                self.assertIn('desktop_startup',text)
                self.assertNotIn('synthetic-private-value',text)
                self.assertFalse((self.root/'runtime.json').exists())

    def test_stopped_store_recovery_failure_never_starts_a_backend(self):
        with patch('application_backups.startup',side_effect=OSError('synthetic-private-value')), patch.object(desktop,'ManagedBackend') as backend:
            self.assertEqual(desktop.run(),1)
        backend.assert_not_called()
        self.gui.create_window.assert_not_called()
        text=(self.root/'sap-lens.log').read_text()
        self.assertIn('storage_recovery',text)
        self.assertNotIn('synthetic-private-value',text)
        self.assertFalse((self.root/'runtime.json').exists())

    def test_scheduler_lifespan_failure_does_not_report_ready(self):
        async def fail(_scheduler):raise RuntimeError('synthetic-private-value')
        from scheduler import Scheduler
        observed=[]
        app=create_app(startup_observer=lambda *args:observed.append(args))
        with patch.object(Scheduler,'loop',fail):
            with self.assertRaises(RuntimeError):
                with TestClient(app):pass
        self.assertNotIn(('initialization','ready',None),observed)
        self.assertTrue(any(event[0:2]==('initialization','failed') for event in observed))

    def test_retry_is_disabled_when_owned_backend_shutdown_is_incomplete(self):
        stopped=desktop.ManagedBackend.close
        def incomplete(backend):
            stopped(backend)
            return False
        def session(**kwargs):
            bridge=self.gui.create_window.call_args.kwargs['js_api']
            self.assertFalse(bridge.retry_startup(bridge._token))
            script=self.window.evaluate_js.call_args.args[0]
            self.assertIn('retry is disabled',script)
            self.assertTrue(script.endswith(',false)'))
        self.gui_session=session
        with patch.object(desktop.ManagedBackend,'start',side_effect=desktop.StartupFailure('SYNTHETIC','Synthetic failure')), patch.object(desktop.ManagedBackend,'close',incomplete):
            self.assertEqual(desktop.run(),1)

    def test_retry_of_invalid_timeout_stays_recoverable_without_a_backend(self):
        failures=[];second=threading.Event()
        original=self.window.evaluate_js.side_effect
        def evaluate(script):
            original(script)
            if 'INVALID_STARTUP_TIMEOUT' in script:
                failures.append(script)
                if len(failures)==2:second.set()
        self.window.evaluate_js.side_effect=evaluate
        def session(**kwargs):
            bridge=self.gui.create_window.call_args.kwargs['js_api']
            self.assertTrue(bridge.retry_startup(bridge._token))
            self.assertTrue(second.wait(3))
        self.gui_session=session
        with patch.dict(os.environ,{'SAP_LENS_DESKTOP_STARTUP_TIMEOUT':'invalid'}),patch.object(desktop,'ManagedBackend') as backend:
            self.assertEqual(desktop.run(),1)
        backend.assert_not_called()
        self.assertEqual(len(failures),2)

    def test_scheduler_returning_early_never_passes_initialization(self):
        async def stopped(_scheduler):return
        from scheduler import Scheduler
        with patch.object(Scheduler,'loop',stopped):
            with self.assertRaisesRegex(RuntimeError,'Scheduler stopped'):
                with TestClient(create_app()):pass

    def test_retry_bridge_requires_launch_capability(self):
        bridge=desktop.NativeDialogs('synthetic-capability');bridge._retry_startup=MagicMock(return_value=True)
        for method in (bridge.retry_startup,bridge.startup_log_location):
            with self.assertRaises(ValueError):method('wrong')
        bridge._retry_startup.assert_not_called()
        self.assertTrue(bridge.retry_startup('synthetic-capability'))

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
