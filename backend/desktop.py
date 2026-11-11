"""Window-owned WebView2 runtime with no subprocesses or console dependency."""
import hmac
from datetime import datetime, timezone
import traceback
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
    if kind == 'package':
        pattern = r'sap-lens-access-package-\d{4}-\d{2}-\d{2}\.csv'
    if kind == 'sod':
        pattern = r'sap-lens-sod-((users|roles)-findings|reviews|actions|catalogue|explorer-(user-risk|user-activity|access-list|lookup)|group-(risk|activity)-heatmap|review-queue|access-remediation)-\d{4}-\d{2}-\d{2}\.csv'
    if not isinstance(filename, str) or not re.fullmatch(pattern, filename):
        raise ValueError('Invalid CSV export filename.')
    header = ('\ufeff"Timestamp","Source","Change","Identifier","Field","Before","After"\r\n' if kind == 'changes' else '\ufeff"Username","User group",')
    if kind=='access' and re.fullmatch(r'sap-lens-(user-directory|release-roles)-review-\d{4}-\d{2}-\d{2}\.csv',filename):
        from csv_exports import ASSIGNMENT_HEADER
        header=ASSIGNMENT_HEADER
    if kind=='access' and re.fullmatch(r'sap-lens-release-role-list-review-\d{4}-\d{2}-\d{2}\.csv',filename):
        from csv_exports import ROLE_LIST_HEADER
        header=ROLE_LIST_HEADER
    if kind == 'package':
        from routers.roles import PACKAGE_HEADER
        header = PACKAGE_HEADER
    if kind == 'sod':
        if filename.startswith('sap-lens-sod-catalogue-'):
            from routers.sod import CATALOGUE_HEADER
            header=CATALOGUE_HEADER
        elif filename.startswith(('sap-lens-sod-reviews-', 'sap-lens-sod-actions-')):
            from routers.sod_reviews import REVIEW_HEADER
            header = REVIEW_HEADER
        elif filename.startswith(('sap-lens-sod-explorer-', 'sap-lens-sod-group-', 'sap-lens-sod-review-queue-', 'sap-lens-sod-access-remediation-')):
            from routers.sod_governance import native_csv_header
            header = native_csv_header(filename)
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
    template=filename=='sap-lens-sod-reference-template.xlsx'
    if not template and (not isinstance(filename,str) or not re.fullmatch(r'sap-lens-(sod-report-[a-f0-9]{32}|access-remediation-(current|[a-f0-9]{32}))-\d{4}-\d{2}-\d{2}\.(pdf|docx)',filename)):raise ValueError('Invalid report filename.')
    if not isinstance(encoded,str) or len(encoded)>45*1024*1024:raise ValueError('Report exceeds its size limit.')
    try:payload=base64.b64decode(encoded,validate=True)
    except (ValueError,TypeError):raise ValueError('Invalid report content.') from None
    if len(payload)>32*1024*1024:raise ValueError('Report exceeds 32 MiB.')
    extension=Path(filename).suffix
    if template:
        from sod_reference import default_path
        if payload!=default_path().with_name('sod-reference-template.xlsx').read_bytes():raise ValueError('Invalid reference template.')
    elif extension=='.pdf':
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
        files=owner._window.create_file_dialog(webview.FileDialog.SAVE,save_filename=filename,file_types=(('PDF files (*.pdf)' if extension=='.pdf' else 'Reference workbook (*.xlsx)' if template else 'Word documents (*.docx)'),))
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


class StartupFailure(DesktopStartupError):
    """Authored failure classification; exception details never enter the startup page."""
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class StartupAttempt:
    def __init__(self):
        self.identity = secrets.token_hex(8)
        self.started = time.monotonic()
        self.phase = 'initialization'

    def event(self, stage, result, error=None, **context):
        self.phase = stage
        details = dict(attempt=self.identity, timestamp=datetime.now(timezone.utc).isoformat(),
                       elapsed_ms=round((time.monotonic()-self.started)*1000), stage=stage, result=result,
                       pid=os.getpid(), **context)
        if error is not None:
            details['exception'] = type(error).__name__
            # Traceback locations only: no exception values, source lines, paths or locals.
            chain = []
            current = error
            while current is not None and len(chain) < 5:
                chain.append(dict(exception=type(current).__name__, locations=[f'{Path(frame.filename).name}:{frame.lineno}:{frame.name}' for frame in traceback.extract_tb(current.__traceback__)]))
                current = current.__cause__
            details['traceback'] = chain
        logger.log(logging.ERROR if error is not None or result == 'failed' else logging.INFO,
                   'desktop_startup %s', json.dumps(details, sort_keys=True))


def startup_timeout():
    try:
        value = float(os.environ.get('SAP_LENS_DESKTOP_STARTUP_TIMEOUT', '15'))
        if not 1 <= value <= 180:
            raise ValueError()
        return value
    except ValueError:
        raise StartupFailure('INVALID_STARTUP_TIMEOUT', 'Startup timeout must be between 1 and 180 seconds. Check the desktop environment configuration.') from None


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
        self._retry_startup = None

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

    def retry_startup(self, token: str):
        if not isinstance(token, str) or not hmac.compare_digest(token.encode(), self._token.encode()):
            raise ValueError('Application request is not authorized.')
        return bool(self._retry_startup and self._retry_startup())

    def startup_log_location(self, token: str):
        if not isinstance(token, str) or not hmac.compare_digest(token.encode(), self._token.encode()):
            raise ValueError('Application request is not authorized.')
        return str(config_dir() / 'sap-lens.log')

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

    def save_application_backup(self, token, identity, kind='backup'):
        if not isinstance(token,str) or not hmac.compare_digest(token.encode(),self._token.encode()): raise ValueError('Application request is not authorized.')
        from application_backups import download
        source=download(identity,kind)
        if not self._window or not self._picker_lock.acquire(blocking=False): return False
        try:
            import webview
            import shutil
            import tempfile
            from maintenance import private_file
            files=self._window.create_file_dialog(webview.FileDialog.SAVE,save_filename=f'SAP-Lens-{kind}-{identity}.tar.gz',file_types=('Gzip archives (*.tar.gz)',))
            if not files: return False
            target=Path(files[0])
            if not target.is_absolute() or not target.name.endswith('.tar.gz') or target.is_symlink(): raise ValueError('Choose an absolute .tar.gz destination without links.')
            fd,temporary=tempfile.mkstemp(dir=target.parent,suffix='.tmp')
            try:
                private_file(Path(temporary))
                with os.fdopen(fd,'wb') as output, source.open('rb') as incoming:
                    shutil.copyfileobj(incoming,output);output.flush();os.fsync(output.fileno())
                os.replace(temporary,target)
            finally: Path(temporary).unlink(missing_ok=True)
            return True
        finally: self._picker_lock.release()

    def open_project_repository(self, token):
        if not isinstance(token,str) or not hmac.compare_digest(token.encode(),self._token.encode()):
            raise ValueError('Application request is not authorized.')
        import webbrowser
        return bool(webbrowser.open('https://github.com/OnlyDrey/sap-lens'))

    def save_sod_document(self, token, filename, content_base64):
        return _save_document_dialog(self, token, filename, content_base64)

    def save_sod_csv(self, token: str, filename: str, content: str):
        return _save_csv_dialog(self, token, filename, content, 'sod')

    def save_role_package_csv(self, token: str, filename: str, content: str):
        return _save_csv_dialog(self, token, filename, content, 'package')

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


def local_http_opener():
    """Only HTTP on the owned loopback listener; no proxy, TLS, file or FTP setup.

    build_opener() eagerly loads the Windows certificate store through its default
    HTTPSHandler, outside the HTTP request timeout. Desktop startup never uses TLS.
    Keep redirects fail-closed instead of contacting another service.
    """
    from urllib.request import (OpenerDirector, HTTPHandler, HTTPDefaultErrorHandler,
                                HTTPErrorProcessor, HTTPRedirectHandler, UnknownHandler)

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise StartupFailure('UNEXPECTED_SERVICE', 'The local service redirected its readiness check. No other service will be used.')

    opener = OpenerDirector()
    for handler in (HTTPHandler(), HTTPDefaultErrorHandler(), HTTPErrorProcessor(), NoRedirect(), UnknownHandler()):
        opener.add_handler(handler)
    return opener


class ManagedBackend:
    def __init__(self, app, listener):
        import uvicorn
        self.listener = listener
        self._lifecycle_lock = threading.Lock()
        self._closed = False
        self.server = uvicorn.Server(uvicorn.Config(
            app, log_config=None, access_log=False, timeout_graceful_shutdown=2))
        self.error = None
        self.exit_code = None
        self.worker = threading.Thread(target=self._run,
                                       name='sap-lens-api', daemon=True)

    def _run(self):
        try:
            self.server.run(sockets=[self.listener])
            self.exit_code = 0 if self.server.started else 1
        except BaseException as error:
            # Uvicorn may use SystemExit for startup errors; preserve it for diagnostics.
            self.error = error
            self.exit_code = error.code if isinstance(error, SystemExit) and isinstance(error.code, int) else 1

    def start(self, timeout: float = 15, canceled=None):
        with self._lifecycle_lock:
            if self._closed or (canceled and canceled.is_set()): return
            self.worker.start()
        deadline = time.monotonic() + timeout
        while not self.server.started:
            if canceled and canceled.is_set(): return
            if not self.worker.is_alive():
                raise StartupFailure('BACKEND_EXITED', 'The local backend stopped during initialization. Review the startup log and retry.') from self.error
            if time.monotonic() >= deadline:
                raise StartupFailure('INITIALIZATION_TIMEOUT', 'Backend initialization exceeded the startup deadline. Review the startup log before retrying.')
            if canceled: canceled.wait(.025)
            else: time.sleep(.025)

    def wait_ready(self, origin, identity, deadline, canceled, attempt):
        from urllib.error import URLError
        opener = local_http_opener()
        probes = 0
        while not canceled.is_set():
            if not self.worker.is_alive():
                raise StartupFailure('BACKEND_EXITED', 'The local backend stopped before readiness. Review the startup log and retry.') from self.error
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise StartupFailure('READINESS_TIMEOUT', 'The local backend did not answer its readiness checks. Review the startup log and retry.')
            probes += 1
            try:
                with opener.open(origin + '/health', timeout=min(.5, remaining)) as response:
                    if response.status != 200:
                        raise ValueError('Unexpected health status')
                    body = response.read(8193)
                    if len(body) > 8192: raise ValueError('Unexpected health size')
                    health = json.loads(body)
                if not isinstance(health, dict) or health.get('app') != 'sap-lens' or health.get('instance_id') != identity or health.get('status') not in {'ok','loading','needs_configuration'}:
                    raise ValueError('Unexpected service identity')
                if not self.worker.is_alive():
                    raise StartupFailure('BACKEND_EXITED', 'The local backend stopped during readiness. Review the startup log and retry.')
                attempt.event('readiness', 'ready', probe=probes)
                return
            except (URLError, TimeoutError, ConnectionError, OSError) as error:
                attempt.event('readiness', 'unavailable', probe=probes, category=type(error).__name__)
            except (ValueError, TypeError) as error:
                raise StartupFailure('UNEXPECTED_SERVICE', 'The local service returned an unexpected readiness response. No other service will be used.') from error
            canceled.wait(min(.1, max(0, deadline-time.monotonic())))

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
        return not self.worker.is_alive()


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
    attempt = StartupAttempt()
    try:
        if is_windows():
            instance = WindowsInstance()
            if not instance.acquire():
                if not activate_existing_window():
                    report_error('SAP Lens is already starting or running. Switch to its application window.')
                return 0
        stage = 'application data directory'
        directory = config_dir()
        directory.mkdir(parents=True, exist_ok=True)
        try:
            handler = RotatingFileHandler(directory / 'sap-lens.log', maxBytes=2_000_000,
                                          backupCount=2, encoding='utf-8')
            handler.addFilter(AppLogFilter())
            handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
            logging.getLogger().addHandler(handler)
            logging.getLogger().setLevel(logging.INFO)
        except OSError:
            logger.warning('Desktop file logging unavailable; check application data permissions')
        if is_windows() and not webview2_available():
            raise DesktopStartupError('Microsoft Edge WebView2 Runtime is required. Install the Evergreen WebView2 Runtime from Microsoft, or ask your IT administrator, then reopen SAP Lens. No Python or Node.js installation is needed.')
        attempt.event('storage_recovery', 'starting')
        stage = 'storage_recovery'
        from storage_lease import StorageLease
        storage_lease = StorageLease(directory,'desktop').acquire()
        attempt.event('instance', 'owned', stale_runtime=(directory/'runtime.json').exists())
        from application_backups import startup
        startup(storage_lease)
        attempt.event('storage_recovery', 'ready', database='stopped_store_recovery_complete')
        from config import get_settings
        get_settings.cache_clear()
        from storage_migration import run as migrate_storage
        attempt.event('storage_upgrade', migrate_storage(storage_lease).get('state', 'unknown'))
        stage = 'application resources'
        import webview
        from startup_screen import startup_html, state_script, palette_script
        listener = reserve_listener(APP_PORT)
        port = listener.getsockname()[1]
        attempt.event('listener', 'reserved', host='127.0.0.1', port=port)
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

        retry_requested = threading.Event()
        retry_allowed = threading.Event()
        def request_retry():
            with startup_lock:
                if closing.is_set() or not retry_allowed.is_set(): return False
                retry_allowed.clear()
                retry_requested.set()
                return True
        dialogs._retry_startup = request_retry

        def watch_backend():
            nonlocal backend, listener, origin, identity, runtime_file, attempt
            try:
                deadline = time.monotonic() + 15
                while not window.events.loaded.wait(.1):
                    if closing.is_set(): return
                    if time.monotonic() >= deadline:
                        raise StartupFailure('WINDOW_TIMEOUT', 'The startup window did not finish loading. Close SAP Lens and check WebView2.')
                if closing.is_set(): return
                if background:
                    try:
                        background.attach_native_session_end()
                        background.loaded()
                    except Exception:
                        background.last_error='Windows tray unavailable; normal closing is active.'
                        background.restore()
                        logger.warning('Tray unavailable; normal desktop shutdown retained')
            except Exception as error:
                attempt.event('window', 'failed', error, code=getattr(error,'code','WINDOW_FAILED'))
                crashed.set()
                report_error('The SAP Lens startup window could not initialize. Check WebView2 and the application log.')
                window.destroy()
                return

            while not closing.is_set():
                stage = 'configuration'
                try:
                    if listener.fileno() < 0:
                        listener = reserve_listener(APP_PORT)
                        origin = f'http://127.0.0.1:{listener.getsockname()[1]}'
                        identity = secrets.token_hex(16)
                        if background: background.origin = origin
                    timeout = startup_timeout()
                    deadline = time.monotonic() + timeout
                    attempt.event('attempt', 'starting', host='127.0.0.1', port=listener.getsockname()[1])
                    window.evaluate_js(state_script('Starting backend…'))
                    attempt.event('configuration', 'starting')
                    from config import get_settings
                    settings = get_settings()
                    attempt.event('configuration', 'ready')
                    window.evaluate_js(palette_script(settings))
                    stage = 'application'
                    from main import create_app, frontend_dir
                    if not frontend_dir.is_dir():
                        raise StartupFailure('ASSETS_MISSING', 'Compiled frontend files are missing. Rebuild or reinstall the application package.')
                    app = create_app(origin=origin, session_token=token, instance_id=identity, browser_access=True,
                                     desktop_preferences=background.preferences_change if background else None,
                                     startup_observer=lambda phase,result,error=None,owner=attempt:owner.event(phase,result,error))
                    with startup_lock:
                        if closing.is_set(): return
                        backend = ManagedBackend(app, listener)
                    stage = 'backend'
                    backend.start(timeout=max(.001, deadline-time.monotonic()), canceled=closing)
                    if closing.is_set(): return
                    window.evaluate_js(state_script('Connecting to local service…'))
                    stage = 'readiness'
                    backend.wait_ready(origin, identity, deadline, closing, attempt)
                    if closing.is_set(): return
                    if background: background.ready_backend()
                    with startup_lock:
                        if closing.is_set(): return
                        runtime_file = directory / 'runtime.json'
                        from config import atomic_write
                        atomic_write(runtime_file, json.dumps({'pid': os.getpid(), 'origin': origin,
                                                              'instance_id': identity}).encode())
                    window.evaluate_js(state_script('Loading configuration…'))
                    if closing.is_set(): return
                    window.evaluate_js('window.location.replace(' + json.dumps(f'{origin}/#session={token}') + ')')
                    attempt.event('startup', 'ready', host='127.0.0.1', port=listener.getsockname()[1])
                    crashed.clear()
                    break
                except Exception as error:
                    if closing.is_set(): return
                    crashed.set()
                    if background: background.failed_backend()
                    code = getattr(error,'code', {'configuration':'CONFIGURATION_FAILED','application':'APPLICATION_INIT_FAILED'}.get(stage,'STARTUP_FAILED'))
                    attempt.event(stage, 'failed', error, code=code,
                                  worker_exit_code=backend.exit_code if backend else None)
                    stopped = backend.close() if backend else True
                    if not backend: listener.close()
                    attempt.event('cleanup', 'stopped' if stopped else 'incomplete')
                    if stopped:
                        retry_allowed.set()
                    message = str(error) if isinstance(error, StartupFailure) else 'Initialization could not complete. Review the startup log and check configuration and storage permissions.'
                    if not stopped:
                        message = 'Backend shutdown is incomplete. Close SAP Lens fully before starting it again; retry is disabled to prevent duplicate writers.'
                    try:
                        window.evaluate_js(state_script('Startup needs attention', message, code, stopped))
                    except Exception:
                        report_error('SAP Lens could not display its startup screen. Close the application; saved settings are retained.')
                        window.destroy()
                        return
                    while not closing.is_set() and not retry_requested.wait(.1): pass
                    if closing.is_set(): return
                    retry_requested.clear()
                    backend = None
                    # Reserve the next socket inside the guarded attempt, never outside its error path.
                    attempt = StartupAttempt()
                    from config import get_settings as reload_settings
                    reload_settings.cache_clear()
            while not closing.wait(0.5):
                if background: background.check_tray()
                if not backend.worker.is_alive():
                    crashed.set()
                    attempt.event('runtime','failed',backend.error,code='BACKEND_EXITED',worker_exit_code=backend.exit_code)
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
        attempt.event(stage,'failed',exc,code=getattr(exc,'code','DESKTOP_PREREQUISITE'))
        report_error(str(exc))
        return 1
    except Exception as exc:
        # Avoid logging URL fragments, native bridge state or CSV contents.
        attempt.event(stage,'failed',exc,code='DESKTOP_INITIALIZATION_FAILED')
        report_error('SAP Lens could not complete ' + stage + '. No new backend was started. '
                     'Check the local application log and application-data permissions; keep saved data and recovery files intact.')
        return 1
    finally:
        attempt.event('shutdown','starting')
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
