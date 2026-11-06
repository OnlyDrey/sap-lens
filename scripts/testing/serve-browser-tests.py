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
        uvicorn.run(create_app(origin=f'http://127.0.0.1:{port}', session_token='browser-test-session', instance_id='browser-test', browser_access=True),
                    host='127.0.0.1', port=port, access_log=False, log_level='warning')


if __name__ == '__main__':
    main()
