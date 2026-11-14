"""Phase 0 experiment: headless entry for the existing SAP Lens FastAPI app under an external supervisor (the Go host).

It adds NO business logic and changes no SAP Lens code: it imports the repository's `main.create_app` unchanged, in the same browser-access
mode the desktop application uses, and replaces only the in-process window/thread host.

Contract with the host
  * environment: SAP_LENS_POC_DATA = an isolated experiment directory carrying the marker written by the host (anything else is refused);
  * stdin line 1: {"capability": ..., "instance_id": ...}; the capability is never in arguments, environment or output;
  * stdout line 1: {"event": "listening", "port": N, "pid": P} after the loopback listener was reserved;
  * stdin line "stop" or end of input: graceful shutdown (the host's death closes the pipe, so the backend never outlives it).
"""
import json
import os
import re
import signal
import socket
import sys
import threading
from pathlib import Path

MARKER = '.sap-lens-poc'
MARKER_TEXT = 'sap-lens-poc-v1\n'
EXIT_REFUSED, EXIT_BAD_HANDOFF = 10, 11


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
    root = isolated_data_directory()
    if root is None:
        return refuse(EXIT_REFUSED, 'refused: SAP_LENS_POC_DATA is not an isolated experiment directory')
    config = root / 'config'
    config.mkdir(mode=0o700, exist_ok=True)
    # Every SAP Lens path resolves below the isolated directory; nothing of an installed SAP Lens is read or written.
    os.environ['SAP_LENS_CONFIG_DIR'] = str(config)
    for name in ('SAP_LENS_DATA_DIR', 'SAP_LENS_SOURCE_DIR', 'SAP_LENS_DEPLOYMENT_MODE', 'DATA_CSV_PATH', 'USER_CSV_PATH', 'EMPLOYEE_CSV_PATH', 'SOD_CSV_PATH'):
        os.environ.pop(name, None)
    handoff = read_handoff()
    if handoff is None:
        return refuse(EXIT_BAD_HANDOFF, 'refused: invalid capability handoff')
    capability, instance = handoff
    listener = reserve_loopback_listener()
    port = listener.getsockname()[1]
    print(json.dumps({'event': 'listening', 'port': port, 'pid': os.getpid()}), flush=True)
    import uvicorn
    from main import create_app
    app = create_app(origin=f'http://127.0.0.1:{port}', session_token=capability, instance_id=instance, browser_access=True)
    server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False, timeout_graceful_shutdown=2))

    def request_stop(*_):
        server.should_exit = True

    def watch_stdin():
        while True:
            line = sys.stdin.readline()
            if line == '' or line.strip() == 'stop':
                request_stop()
                # The host's own deadline forces the rest; this is a last resort if graceful shutdown stalls.
                threading.Timer(5, lambda: setattr(server, 'force_exit', True)).start()
                return

    threading.Thread(target=watch_stdin, name='poc-stdin', daemon=True).start()
    for name in ('SIGTERM', 'SIGINT'):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), request_stop)
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
