"""Phase 0 experiment: headless entry for the existing SAP Lens FastAPI app under an external supervisor (the Go host).

It adds NO business logic and changes no SAP Lens code: it imports the repository's `main.create_app` unchanged, in the same browser-access
mode the desktop application uses, and replaces only the in-process window/thread host.

Contract with the host
  * environment: SAP_LENS_POC_DATA = an isolated experiment directory carrying the marker written by the host (anything else is refused);
  * stdin line 1: {"capability": ..., "instance_id": ...}; the capability is never in arguments, environment or output;
  * stdout line 1: {"event": "listening", "port": N, "pid": P} after the loopback listener was reserved;
  * stdin line "stop" or end of input: graceful shutdown (the host's death closes the pipe, so the backend never outlives it).

Diagnostics (stderr only, never the capability): `poc: t=<seconds> phase=...` lines for every startup phase; exit codes 10 refused data directory, 11 bad handoff,
12 startup error (traceback printed), 13 frontend assets missing. When SAP_LENS_POC_DUMP_AFTER=<seconds> is set and the server is still not serving after that
long, every thread's stack is written to stderr (faulthandler): it shows where a stalled start is stuck.
"""
import faulthandler
import json
import os
import platform
import re
import signal
import socket
import sys
import threading
import time
import traceback
from pathlib import Path

MARKER = '.sap-lens-poc'
MARKER_TEXT = 'sap-lens-poc-v1\n'
EXIT_REFUSED, EXIT_BAD_HANDOFF, EXIT_STARTUP_ERROR, EXIT_NO_FRONTEND = 10, 11, 12, 13
STARTED = time.perf_counter()


def note(message):
    """One diagnostic line on stderr with the time since this process started. Never put a capability or instance id in a message."""
    print(f'poc: t={time.perf_counter() - STARTED:.2f}s {message}', file=sys.stderr, flush=True)


def refuse(code, message):
    print(message, file=sys.stderr, flush=True)
    return code


def isolated_data_directory():
    value = os.environ.get('SAP_LENS_POC_DATA', '')
    if not value or not os.path.isabs(value):
        return None
    root = Path(value).resolve()
    marker = root / MARKER
    try:
        if marker.is_symlink() or marker.read_text(encoding='utf-8') != MARKER_TEXT:
            return None
    except OSError:
        return None
    return root


def read_handoff():
    line = sys.stdin.readline(4096)
    try:
        value = json.loads(line)
        capability, instance = value['capability'], value['instance_id']
    except (ValueError, KeyError, TypeError):
        return None
    if not (isinstance(capability, str) and len(capability) >= 32 and re.fullmatch(r'[A-Za-z0-9_-]+', capability)):
        return None
    if not (isinstance(instance, str) and re.fullmatch(r'[0-9a-f]{32}', instance)):
        return None
    return capability, instance


def reserve_loopback_listener():
    """OS-assigned port on 127.0.0.1 only; exclusive on Windows so another service can never share the port."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform == 'win32':
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('127.0.0.1', 0))
    return listener


def main():
    note(f'phase=start python={platform.python_version()} executable={sys.executable} cwd={os.getcwd()}')
    note('sys.path=' + os.pathsep.join(sys.path))
    note('env_names=' + ','.join(sorted(os.environ)))
    root = isolated_data_directory()
    if root is None:
        return refuse(EXIT_REFUSED, 'refused: SAP_LENS_POC_DATA is not an isolated experiment directory')
    note('phase=data_directory_ok')
    config = root / 'config'
    config.mkdir(mode=0o700, exist_ok=True)
    # Every SAP Lens path resolves below the isolated directory; nothing of an installed SAP Lens is read or written.
    os.environ['SAP_LENS_CONFIG_DIR'] = str(config)
    for name in ('SAP_LENS_DATA_DIR', 'SAP_LENS_SOURCE_DIR', 'SAP_LENS_DEPLOYMENT_MODE', 'DATA_CSV_PATH', 'USER_CSV_PATH', 'EMPLOYEE_CSV_PATH', 'SOD_CSV_PATH'):
        os.environ.pop(name, None)
    # The React build is part of what this experiment serves: fail fast and say so, instead of a backend that answers /health but cannot show the application.
    frontend = Path(__file__).resolve().parent.parent / 'frontend' / 'dist'
    note(f'phase=frontend_check index_html_exists={(frontend / "index.html").is_file()} dir={frontend}')
    if not (frontend / 'index.html').is_file():
        return refuse(EXIT_NO_FRONTEND, f'refused: frontend assets are missing (no index.html in {frontend})')
    handoff = read_handoff()
    if handoff is None:
        return refuse(EXIT_BAD_HANDOFF, 'refused: invalid capability handoff')
    note('phase=handoff_read')
    capability, instance = handoff
    listener = reserve_loopback_listener()
    port = listener.getsockname()[1]
    print(json.dumps({'event': 'listening', 'port': port, 'pid': os.getpid()}), flush=True)
    note(f'phase=listening port={port}')
    dump_after = os.environ.get('SAP_LENS_POC_DUMP_AFTER', '')
    if dump_after.isdigit() and int(dump_after) > 0:
        faulthandler.dump_traceback_later(int(dump_after), exit=False, file=sys.stderr)
    server = None
    try:
        import uvicorn
        note('phase=imported_uvicorn')
        from main import create_app
        note('phase=imported_main')
        app = create_app(origin=f'http://127.0.0.1:{port}', session_token=capability, instance_id=instance, browser_access=True)
        note('phase=app_created')
        server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False, timeout_graceful_shutdown=2))
    except BaseException:
        faulthandler.cancel_dump_traceback_later()
        traceback.print_exc()
        note('phase=failed_before_serving (traceback above)')
        listener.close()
        return EXIT_STARTUP_ERROR

    def request_stop(*_):
        server.should_exit = True

    def watch_stdin():
        while True:
            line = sys.stdin.readline()
            if line == '' or line.strip() == 'stop':
                note('phase=stop_requested')
                request_stop()
                # The host's own deadline forces the rest; this is a last resort if graceful shutdown stalls.
                threading.Timer(5, lambda: setattr(server, 'force_exit', True)).start()
                return

    def watch_started():
        while not server.started and not server.should_exit:
            time.sleep(0.05)
        if server.started:
            faulthandler.cancel_dump_traceback_later()
            note('phase=serving')

    threading.Thread(target=watch_stdin, name='poc-stdin', daemon=True).start()
    threading.Thread(target=watch_started, name='poc-started', daemon=True).start()
    for name in ('SIGTERM', 'SIGINT'):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), request_stop)
    try:
        server.run(sockets=[listener])
    except BaseException:
        traceback.print_exc()
        note('phase=server_failed (traceback above)')
        return EXIT_STARTUP_ERROR
    finally:
        listener.close()
    note('phase=stopped')
    return 0


if __name__ == '__main__':
    sys.exit(main())
