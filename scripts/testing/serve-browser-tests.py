"""Isolated production-asset test server; not an end-user launch command."""
from pathlib import Path
import os
import shutil
import signal
import sys
import tempfile
import threading
import time

PREFIX = 'sap-lens-browser-'
OWNER_FILE = '.owner-pid'
LEGACY_MAX_AGE = 6 * 3600  # directories without an owner marker (older runs) are only removed when this old
# Idle keep-alive connections stay open longer than the 120 s Playwright test timeout. With uvicorn's 5 s default the server closes
# connections that Playwright's API client (a keep-alive agent without an idle timeout) may reuse at the same moment: "socket hang up"
# (ECONNRESET) on a request the server never received. Each test's request context closes its own connections when it is disposed.
KEEP_ALIVE_SECONDS = 150
SLOW_REQUEST_MS = 2000  # requests at least this slow are reported on stderr (kept with the shard log of a failed run)


def request_diagnostics(app, label: str, slow_ms: float, log_path: str | None):
    """ASGI wrapper that reports slow requests, server errors and requests that ended without a response on stderr, and with
    SAP_LENS_TEST_REQUEST_LOG every request to that file. Paths only: query strings can carry test usernames."""
    log = open(log_path, 'a', encoding='utf-8', buffering=1) if log_path else None

    async def wrapper(scope, receive, send):
        if scope['type'] != 'http':
            return await app(scope, receive, send)
        started, status = time.perf_counter(), 0

        async def watch(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
            await send(message)
        try:
            await app(scope, receive, watch)
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            line = f"{scope['method']} {scope['path']} -> {status or 'no response'} in {elapsed:.0f} ms"
            if not status or status >= 500 or elapsed >= slow_ms:
                kind = 'no response' if not status else 'server error' if status >= 500 else 'slow request'
                print(f'[{label}] {kind}: {line}', file=sys.stderr, flush=True)
            if log:
                log.write(f'{time.time():.3f} {line}\n')
    return wrapper


def process_exists(pid: int) -> bool:
    """Whether a process is alive. Never signals it: on Windows os.kill would terminate the process."""
    if sys.platform == 'win32':
        return True  # unknown: keep the directory (the age rule below still applies to marker-less ones)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def sweep_stale(root: Path, now: float | None = None) -> list[str]:
    """Remove temporary directories left by test servers that were killed before they could clean up.

    Only directories of this prefix are touched: those whose recorded owner process no longer exists, and marker-less
    ones older than LEGACY_MAX_AGE. A directory of a running server is never removed and no process is ever signalled.
    """
    now = time.time() if now is None else now
    removed: list[str] = []
    for path in root.glob(f'{PREFIX}*'):
        try:
            if not path.is_dir() or path.is_symlink():
                continue
            marker = path / OWNER_FILE
            if marker.exists():
                stale = not process_exists(int(marker.read_text(encoding='ascii').strip()))
            else:
                stale = now - path.stat().st_mtime > LEGACY_MAX_AGE
            if stale:
                shutil.rmtree(path)
                removed.append(path.name)
        except (OSError, ValueError):
            continue  # unreadable, concurrently removed or malformed: leave it alone
    return removed


def exit_with_parent(poll: float = 0.5) -> None:
    """End the server (through its SIGTERM handler, so the storage directory is removed) when the process that started it is gone.
    Playwright starts the server with `exec`, so its parent is Playwright itself; a SIGKILLed Playwright must not leave a server on the test port."""
    if sys.platform == 'win32':
        return
    parent = os.getppid()
    def watch() -> None:
        while True:
            time.sleep(poll)
            if os.getppid() != parent:
                os.kill(os.getpid(), signal.SIGTERM)
                return
    threading.Thread(target=watch, daemon=True, name='parent-watch').start()


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
    import uvicorn

    # Parallel test processes each own one server (port and configuration directory); the default is the CI port.
    port = int(os.environ.get('SAP_LENS_BROWSER_TEST_PORT', '18745'))
    sweep_stale(Path(tempfile.gettempdir()))
    # Playwright stops the server with SIGTERM (gracefulShutdown), so the directory below is removed. If the process is killed anyway, the owner marker lets the next start sweep it.
    # uvicorn restores the previous handler after its graceful shutdown and re-raises the signal; without a handler of
    # our own that would end the process before the directory below is removed.
    if sys.platform != 'win32':
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    exit_with_parent()
    with tempfile.TemporaryDirectory(prefix=PREFIX) as directory:
        (Path(directory) / OWNER_FILE).write_text(str(os.getpid()), encoding='ascii')
        os.environ['SAP_LENS_CONFIG_DIR'] = directory
        os.environ['DATA_CSV_PATH'] = ''
        from main import create_app
        # browser_access: the same guarded loopback document and stale-session answers as the desktop application, so the start-up recovery is tested end to end.
        application = create_app(origin=f'http://127.0.0.1:{port}', session_token='browser-test-session', instance_id='browser-test', browser_access=True)
        print(f'[test-server {port}] pid {os.getpid()} serving', file=sys.stderr, flush=True)
        uvicorn.run(request_diagnostics(application, f'test-server {port}', float(os.environ.get('SAP_LENS_TEST_SLOW_MS', SLOW_REQUEST_MS)),
                                        os.environ.get('SAP_LENS_TEST_REQUEST_LOG')),
                    host='127.0.0.1', port=port, access_log=False, log_level='warning', timeout_keep_alive=KEEP_ALIVE_SECONDS)
        print(f'[test-server {port}] pid {os.getpid()} stopped', file=sys.stderr, flush=True)


if __name__ == '__main__':
    main()
