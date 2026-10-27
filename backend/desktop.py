"""Window-owned WebView2 runtime with no subprocesses or console dependency."""
import hmac
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import time

from config import APP_PORT, config_dir
from instance import WindowsInstance, activate_existing_window
from windows_runtime import webview2_available

logger = logging.getLogger(__name__)


def _save_csv_dialog(owner, token, filename, content, kind):
    """One guarded native CSV save implementation; wrappers select fixed contracts."""
    if not isinstance(token, str) or not hmac.compare_digest(token.encode(), owner._token.encode()):
        raise ValueError('Application request is not authorized.')
    import re
    pattern = (r'sap-lens-refresh-changes-report-\d{4}-\d{2}-\d{2}\.csv' if kind == 'changes' else r'sap-lens-[A-Za-z0-9_-]{1,100}-[a-z]+-\d{4}-\d{2}-\d{2}\.csv')
    if kind == 'sod':
        pattern = r'sap-lens-sod-((users|roles)-findings|reviews|actions|catalogue)-\d{4}-\d{2}-\d{2}\.csv'
    if not isinstance(filename, str) or not re.fullmatch(pattern, filename):
        raise ValueError('Invalid CSV export filename.')
    header = ('\ufeff"Timestamp","Source","Change","Identifier","Field","Before","After"\r\n' if kind == 'changes' else '\ufeff"Username","User group",')
    if kind=='access' and re.fullmatch(r'sap-lens-(user-directory|release-roles)-review-\d{4}-\d{2}-\d{2}\.csv',filename):
        from csv_exports import ASSIGNMENT_HEADER
        header=ASSIGNMENT_HEADER
    if kind == 'sod':
        if filename.startswith('sap-lens-sod-catalogue-'):
            from routers.sod import CATALOGUE_HEADER
            header=CATALOGUE_HEADER
        elif filename.startswith(('sap-lens-sod-reviews-', 'sap-lens-sod-actions-')):
            from routers.sod_reviews import REVIEW_HEADER
            header = REVIEW_HEADER
        else:
            from routers.sod_analysis import EXPORT_HEADER
            header = EXPORT_HEADER
    if not isinstance(content, str) or not content.startswith(header):
        raise ValueError('Invalid CSV export content.')
    if len(content) > 32 * 1024 * 1024:
        raise ValueError('CSV export exceeds the 32 MiB safety limit.')
    payload = content.encode('utf-8')
    if len(payload) > 32 * 1024 * 1024:
        raise ValueError('CSV export exceeds the 32 MiB safety limit.')
    if not owner._window or not owner._picker_lock.acquire(blocking=False):
        return False
    try:
        import webview
        from config import atomic_write
        files = owner._window.create_file_dialog(webview.FileDialog.SAVE, save_filename=filename, file_types=('CSV files (*.csv)',))
        if not files:
            return False
        path = Path(files[0])
        if not path.is_absolute() or path.suffix.lower() != '.csv' or path.is_symlink():
            raise ValueError('Choose an absolute CSV file path.')
        atomic_write(path, payload)
        return True
    finally:
        owner._picker_lock.release()


def _save_document_dialog(owner,token,filename,encoded):
    """Fixed SoD report formats only; never accepts a server filesystem path."""
    import base64
    import re
    from io import BytesIO
    from zipfile import ZipFile,BadZipFile
    if not isinstance(token,str) or not hmac.compare_digest(token.encode(),owner._token.encode()):raise ValueError('Application request is not authorized.')
    if not isinstance(filename,str) or not re.fullmatch(r'sap-lens-sod-report-[a-f0-9]{32}-\d{4}-\d{2}-\d{2}\.(pdf|docx)',filename):raise ValueError('Invalid report filename.')
    if not isinstance(encoded,str) or len(encoded)>45*1024*1024:raise ValueError('Report exceeds its size limit.')
    try:payload=base64.b64decode(encoded,validate=True)
    except (ValueError,TypeError):raise ValueError('Invalid report content.') from None
    if len(payload)>32*1024*1024:raise ValueError('Report exceeds 32 MiB.')
    extension=Path(filename).suffix
    if extension=='.pdf':
        if not payload.startswith(b'%PDF-') or not payload.rstrip().endswith(b'%%EOF'):raise ValueError('Invalid PDF report.')
    else:
        try:
            with ZipFile(BytesIO(payload)) as archive:
                entries=archive.infolist();names=set(archive.namelist())
                if len(entries)>500 or sum(entry.file_size for entry in entries)>64*1024*1024 or not {'[Content_Types].xml','word/document.xml','_rels/.rels'}<=names:raise ValueError()
                if any(name.startswith('/') or '\\' in name or '..' in name.split('/') or any(part in name.lower() for part in ('vbaproject','embeddings/','customui/')) for name in names):raise ValueError()
                if b'macroEnabled' in archive.read('[Content_Types].xml') or any(b'TargetMode="External"' in archive.read(name) for name in names if name.endswith('.rels')):raise ValueError()
        except (ValueError,BadZipFile,KeyError):raise ValueError('Invalid editable DOCX report.') from None
    if not owner._window or not owner._picker_lock.acquire(blocking=False):return False
    try:
        import webview
        files=owner._window.create_file_dialog(webview.FileDialog.SAVE,save_filename=filename,file_types=(('PDF files (*.pdf)' if extension=='.pdf' else 'Word documents (*.docx)'),))
        if not files:return False
        path=Path(files[0])
        if not path.is_absolute() or path.suffix.lower()!=extension or path.is_symlink():raise ValueError('Choose an absolute matching report destination.')
        from config import atomic_write
        atomic_write(path,payload);return True
    finally:owner._picker_lock.release()


class AppLogFilter(logging.Filter):
    def filter(self, record):
        # Third-party exceptions can contain WebView URLs or filesystem details.
        # Persist only our own intentionally sanitized diagnostics.
        return record.name in {'__main__', 'desktop', 'cache', 'config', 'data_loader'}


class DesktopStartupError(Exception):
    pass


def is_windows() -> bool:
    return sys.platform == 'win32'


def report_error(message: str) -> None:
    if is_windows():
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, 'SAP Lens', 0x10)
    else:
        print(message, file=sys.stderr)


def reserve_listener(preferred_port: int = APP_PORT) -> socket.socket:
    """Never contact a conflicting listener. Reserve an OS-selected port instead."""
    for port in (preferred_port, 0):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if is_windows():
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('127.0.0.1', port))
            return listener
        except OSError:
            listener.close()
            if port == 0:
                raise
    raise RuntimeError('No loopback listener could be reserved')


class NativeDialogs:
    def __init__(self, token: str):
        self._token = token
        self._window = None
        self._desktop = None
        self._picker_lock = threading.Lock()

    def desktop_runtime(self, token: str):
        if not isinstance(token, str) or not hmac.compare_digest(token.encode(), self._token.encode()):
            raise ValueError('Application request is not authorized.')
        return dict(windows=is_windows(), startup_supported=is_windows() and bool(getattr(sys,'frozen',False)),
                    tray_available=bool(self._desktop and self._desktop.tray and self._desktop.tray.alive),
                    warning=self._desktop.last_error if self._desktop else None)

    def desktop_frontend_ready(self, token: str):
        if not isinstance(token, str) or not hmac.compare_digest(token.encode(), self._token.encode()):
            raise ValueError('Application request is not authorized.')
        if self._desktop: self._desktop.frontend_loaded()
        return True

    def close_application(self, token: str):
        if not isinstance(token, str) or not hmac.compare_digest(token.encode(), self._token.encode()):
            raise ValueError('Application request is not authorized.')
        if self._desktop: self._desktop.exit()
        elif self._window: self._window.destroy()

    def choose_csv(self, token: str):
        if not isinstance(token, str) or not hmac.compare_digest(token.encode(), self._token.encode()):
            raise ValueError('Application request is not authorized.')
        if not self._window or not self._picker_lock.acquire(blocking=False):
            return None
        try:
            import webview
            files = self._window.create_file_dialog(
                webview.FileDialog.OPEN, allow_multiple=False,
                file_types=('CSV files (*.csv)',))
            return str(files[0]) if files else None
        finally:
            self._picker_lock.release()


    def choose_logo(self, token: str):
        if not isinstance(token,str) or not hmac.compare_digest(token.encode(),self._token.encode()):
            raise ValueError('Application request is not authorized.')
        if not self._window or not self._picker_lock.acquire(blocking=False): return None
        try:
            import webview
            files = self._window.create_file_dialog(webview.FileDialog.OPEN,allow_multiple=False,
                                                    file_types=('Images (*.png;*.jpg;*.jpeg;*.webp)',))
            return str(files[0]) if files else None
        finally: self._picker_lock.release()

    def open_configuration_folder(self, token: str):
        if not isinstance(token,str) or not hmac.compare_digest(token.encode(),self._token.encode()):
            raise ValueError('Application request is not authorized.')
        if not is_windows(): return False
        directory = config_dir(); directory.mkdir(parents=True,exist_ok=True)
        os.startfile(str(directory))
        return True

    def open_logs(self, token: str):
        if not isinstance(token, str) or not hmac.compare_digest(token.encode(), self._token.encode()):
            raise ValueError('Application request is not authorized.')
        if not is_windows(): return False
        path = config_dir() / 'sap-lens.log'
        if not path.is_file(): raise ValueError('No application log has been created yet.')
        os.startfile(str(path))
        return True

    def export_diagnostics(self, token: str):
        if not isinstance(token, str) or not hmac.compare_digest(token.encode(), self._token.encode()):
            raise ValueError('Application request is not authorized.')
        if not self._window or not self._picker_lock.acquire(blocking=False): return False
        try:
            import webview
            from config import atomic_write
            from diagnostics import diagnostics_snapshot
            files = self._window.create_file_dialog(webview.FileDialog.SAVE, save_filename='SAP-Lens-diagnostics.json', file_types=('Diagnostics (*.json)',))
            if not files: return False
            path = Path(files[0])
            if not path.is_absolute() or path.suffix.lower() != '.json': raise ValueError('Choose an absolute JSON file path.')
            atomic_write(path, json.dumps(diagnostics_snapshot(), indent=2).encode())
            return True
        finally: self._picker_lock.release()

    def save_user_access_csv(self, token: str, filename: str, content: str):
        return _save_csv_dialog(self, token, filename, content, 'access')

    def save_sod_document(self, token, filename, content_base64):
        return _save_document_dialog(self, token, filename, content_base64)

    def save_sod_csv(self, token: str, filename: str, content: str):
        return _save_csv_dialog(self, token, filename, content, 'sod')

    def save_refresh_changes_csv(self, token: str, filename: str, content: str):
        return _save_csv_dialog(self, token, filename, content, 'changes')

    def export_configuration(self, token: str, include_private: bool = False):
        if not isinstance(token,str) or not hmac.compare_digest(token.encode(),self._token.encode()):
            raise ValueError('Application request is not authorized.')
        if not isinstance(include_private,bool): raise ValueError('Invalid export option.')
        if not self._window or not self._picker_lock.acquire(blocking=False): return False
        try:
            import webview
            from config import get_settings,atomic_write
            from portable_config import export_configuration
            files = self._window.create_file_dialog(webview.FileDialog.SAVE,save_filename='SAP-Lens.sap-lens.json',
                                                    file_types=('Configuration (*.json)',))
            if not files: return False
            path = Path(files[0])
            if not path.is_absolute() or path.suffix.lower() != '.json': raise ValueError('Choose an absolute JSON file path.')
            atomic_write(path,json.dumps(export_configuration(get_settings(),include_private),indent=2).encode())
            return True
        finally: self._picker_lock.release()


class ManagedBackend:
    def __init__(self, app, listener):
        import uvicorn
        self.listener = listener
        self._lifecycle_lock = threading.Lock()
        self._closed = False
        self.server = uvicorn.Server(uvicorn.Config(
            app, log_config=None, access_log=False, timeout_graceful_shutdown=2))
        self.worker = threading.Thread(target=self.server.run,
                                       kwargs={'sockets': [listener]},
                                       name='sap-lens-api', daemon=True)

    def start(self, timeout: float = 15, canceled=None):
        with self._lifecycle_lock:
            if self._closed or (canceled and canceled.is_set()): return
            self.worker.start()
        deadline = time.monotonic() + timeout
        while not self.server.started:
            if canceled and canceled.is_set(): return
            if not self.worker.is_alive() or time.monotonic() > deadline:
                raise RuntimeError('The local application service did not become ready.')
            time.sleep(0.025)

    def close(self):
        with self._lifecycle_lock:
            self._closed = True
            self.server.should_exit = True
        if self.worker.ident:
            self.worker.join(timeout=4)
            if self.worker.is_alive():
                self.server.force_exit = True
                self.worker.join(timeout=1)
        self.listener.close()
        # API and loader threads are daemon threads inside this process. No
        # orphan child process remains even when a network filesystem stalls.


def resource_path(name: str) -> Path:
    base = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent
    return base / name


def run() -> int:
    instance = None
    backend = None
    listener = None
    handler = None
    runtime_file = None
    identity = None
    storage_lease = None
    background = None
    startup_lock = threading.Lock()
    closing = threading.Event()
    crashed = threading.Event()
    stage = 'initialization'
    try:
        if is_windows():
            instance = WindowsInstance()
            if not instance.acquire():
                if not activate_existing_window():
                    report_error('SAP Lens is already starting or running. Switch to its application window.')
                return 0
        if is_windows() and not webview2_available():
            raise DesktopStartupError(
                'Microsoft Edge WebView2 Runtime is required. Install the Evergreen WebView2 Runtime '
                'from Microsoft, or ask your IT administrator, then reopen SAP Lens. No Python or Node.js installation is needed.')
        directory = config_dir()
        directory.mkdir(parents=True, exist_ok=True)
        from storage_lease import StorageLease
        storage_lease = StorageLease(directory,'desktop').acquire()
        handler = RotatingFileHandler(directory / 'sap-lens.log', maxBytes=2_000_000,
                                      backupCount=2, encoding='utf-8')
        handler.addFilter(AppLogFilter())
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)
        stage = 'application resources'
        import webview
        from startup_screen import startup_html, state_script, palette_script
        listener = reserve_listener(APP_PORT)
        port = listener.getsockname()[1]
        origin = f'http://127.0.0.1:{port}'
        token = secrets.token_urlsafe(32)
        identity = secrets.token_hex(16)
        dialogs = NativeDialogs(token)
        stage = 'WebView2 window initialization'
        logo = resource_path('frontend/dist/sap-lens.png')
        if not logo.is_file(): logo = resource_path('assets/sap-lens.png')
        window = webview.create_window('SAP Lens', html=startup_html(logo, token),
                                       js_api=dialogs, width=1280, height=850,
                                       min_size=(900, 650), background_color='#0d0d1a')
        dialogs._window = window

        if is_windows():
            from windows_tray import DesktopBackground
            from config import get_settings
            from urllib.request import Request, build_opener, ProxyHandler
            def tray_refresh():
                request = Request(origin+'/api/refresh', data=b'{}', headers={'X-SAP-Lens':token,'Content-Type':'application/json'})
                with build_opener(ProxyHandler({})).open(request,timeout=60) as response:
                    result=json.load(response)
                if any(source.get('status')=='failed' or source.get('error') for source in result.get('refresh',{}).get('sources',[])):
                    raise RuntimeError('One or more sources could not refresh')
            background = DesktopBackground(window, resource_path('assets/sap-lens.ico'),
                lambda:get_settings().desktop, origin, tray_refresh)
            dialogs._desktop = background
            window.events.closing += background.on_closing

        def watch_backend():
            nonlocal backend, runtime_file
            try:
                # This callback runs off the GUI thread, so slow service startup
                # cannot block painting, closing or moving the startup window.
                deadline = time.monotonic() + 15
                while not window.events.loaded.wait(.1):
                    if closing.is_set(): return
                    if time.monotonic() >= deadline: raise RuntimeError('Startup window was not ready.')
                if closing.is_set(): return
                if background:
                    try:
                        background.attach_native_session_end()
                        background.loaded()
                    except Exception:
                        background.last_error='Windows tray unavailable; normal closing is active.'
                        background.restore()
                        logger.warning('Tray unavailable; normal desktop shutdown retained')
                from main import create_app, frontend_dir
                if not frontend_dir.is_dir(): raise RuntimeError('Frontend resources are missing.')
                app = create_app(origin=origin, session_token=token, instance_id=identity, browser_access=True, desktop_preferences=background.preferences_change if background else None)
                from config import get_settings
                window.evaluate_js(palette_script(get_settings()))
                with startup_lock:
                    if closing.is_set(): return
                    backend = ManagedBackend(app, listener)
                backend.start(canceled=closing)
                if closing.is_set(): return
                window.evaluate_js(state_script('Connecting to local service…'))
                from urllib.request import build_opener, ProxyHandler
                with build_opener(ProxyHandler({})).open(origin + '/health', timeout=5) as response:
                    health = json.load(response)
                if health.get('instance_id') != identity:
                    raise RuntimeError('Local instance readiness check failed.')
                logger.info('Local application service ready')
                if background: background.ready_backend()
                with startup_lock:
                    if closing.is_set(): return
                    runtime_file = directory / 'runtime.json'
                    runtime_file.write_text(json.dumps({'pid': os.getpid(), 'origin': origin,
                                                       'instance_id': identity}), encoding='utf-8')
                window.evaluate_js(state_script('Loading configuration…'))
                if closing.is_set(): return
                # Replace the bootstrap entry: Back must never revisit initialization.
                window.evaluate_js('window.location.replace(' + json.dumps(f'{origin}/#session={token}') + ')')
            except Exception:
                if closing.is_set(): return
                crashed.set()
                if background: background.failed_backend()
                logger.error('Desktop local service startup unsuccessful')
                try:
                    window.evaluate_js(state_script('Startup needs attention',
                        'The local service did not become ready. Close and reopen SAP Lens. If it happens again, review the local application log or contact IT.'))
                except Exception:
                    report_error('SAP Lens could not display its startup screen. Close and reopen the application; saved settings are retained.')
                    window.destroy()
                return
            while not closing.wait(0.5):
                if background: background.check_tray()
                if not backend.worker.is_alive():
                    crashed.set()
                    logger.error('Local service stopped unexpectedly')
                    if background: background.failed_backend()
                    report_error('The local SAP Lens service stopped. Reopen SAP Lens to continue; your settings are retained.')
                    if not background or not background.tray: window.destroy()
                    return
        window.events.closed += closing.set
        webview.settings['ALLOW_DOWNLOADS'] = False
        webview.settings['ALLOW_FILE_URLS'] = False
        # No auxiliary HTTP server is enabled; all app resources use our listener.
        webview.start(func=watch_backend, gui='edgechromium' if is_windows() else None,
                      debug=False, private_mode=True, icon=str(resource_path('assets/sap-lens.ico')))
        return 1 if crashed.is_set() else 0
    except DesktopStartupError as exc:
        report_error(str(exc))
        return 1
    except Exception as exc:
        # Avoid logging URL fragments, native bridge state or CSV contents.
        logger.error('Desktop failure during %s (%s)', stage, type(exc).__name__)
        report_error('SAP Lens could not start. Check that Microsoft Edge WebView2 Runtime is installed, '
                     'then try again. If the problem continues, check the local SAP Lens log and your profile permissions.')
        return 1
    finally:
        with startup_lock:
            closing.set()
        if background:
            background.shutdown()
        if backend:
            backend.close()
        elif listener:
            listener.close()
        if runtime_file:
            try:
                if json.loads(runtime_file.read_text(encoding='utf-8')).get('instance_id') == identity:
                    runtime_file.unlink()
            except (OSError, ValueError):
                pass
        if instance:
            instance.close()
        if handler:
            logging.getLogger().removeHandler(handler)
            handler.close()
        if storage_lease:
            storage_lease.close()


if __name__ == '__main__':
    if sys.argv[1:2] == ['--maintenance']:
        from maintenance import cli
        raise SystemExit(cli(sys.argv[2:]))
    raise SystemExit(run())
