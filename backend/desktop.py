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
        self._picker_lock = threading.Lock()

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


class ManagedBackend:
    def __init__(self, app, listener):
        import uvicorn
        self.listener = listener
        self.server = uvicorn.Server(uvicorn.Config(
            app, log_config=None, access_log=False, timeout_graceful_shutdown=2))
        self.worker = threading.Thread(target=self.server.run,
                                       kwargs={'sockets': [listener]},
                                       name='sap-lens-api', daemon=True)

    def start(self, timeout: float = 15):
        self.worker.start()
        deadline = time.monotonic() + timeout
        while not self.server.started:
            if not self.worker.is_alive() or time.monotonic() > deadline:
                raise RuntimeError('The local application service did not become ready.')
            time.sleep(0.025)

    def close(self):
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
        handler = RotatingFileHandler(directory / 'sap-lens.log', maxBytes=2_000_000,
                                      backupCount=2, encoding='utf-8')
        handler.addFilter(AppLogFilter())
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)
        stage = 'application resources'
        import webview
        from main import create_app, frontend_dir
        if not frontend_dir.is_dir():
            raise RuntimeError('Frontend resources are missing from the application.')
        listener = reserve_listener(APP_PORT)
        port = listener.getsockname()[1]
        origin = f'http://127.0.0.1:{port}'
        token = secrets.token_urlsafe(32)
        identity = secrets.token_hex(16)
        app = create_app(origin=origin, session_token=token, instance_id=identity)
        dialogs = NativeDialogs(token)
        backend = ManagedBackend(app, listener)
        stage = 'local service startup'
        backend.start()
        logger.info('Local application service ready')
        # Non-secret discovery record for diagnostics; never persist the session token.
        runtime_file = directory / 'runtime.json'
        runtime_file.write_text(json.dumps({'pid': os.getpid(), 'origin': origin,
                                           'instance_id': identity}), encoding='utf-8')
        stage = 'WebView2 window initialization'
        window = webview.create_window('SAP Lens', f'{origin}/#session={token}',
                                       js_api=dialogs, width=1280, height=850,
                                       min_size=(900, 650), background_color='#1A003B')
        dialogs._window = window
        webview.settings['ALLOW_DOWNLOADS'] = False
        webview.settings['ALLOW_FILE_URLS'] = False
        # No auxiliary HTTP server is enabled; all app resources use our listener.
        webview.start(gui='edgechromium' if is_windows() else None,
                      debug=False, private_mode=True, icon=str(resource_path('assets/sap-lens.ico')))
        return 0
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


if __name__ == '__main__':
    raise SystemExit(run())
