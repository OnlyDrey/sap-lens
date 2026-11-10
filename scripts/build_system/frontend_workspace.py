"""Isolated frontend build workspace.

The deployment builder never runs `npm ci` in the developer's `frontend/node_modules` (a running dev server, editor or scanner can hold files there,
and `npm ci` deletes the whole directory first). It builds in `backend/build/frontend-workspace`, a mirror of the paths the frontend tooling reads
(`frontend/`, `scripts/`, `backend/resources`, the build identity), installs from the committed lockfile with `npm ci`, and publishes only the verified
`dist` back to `frontend/dist`. The installation is reused while `package.json`, `package-lock.json` and the Node version are unchanged."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import uuid

NOT_COPIED = {'node_modules', 'dist', 'test-results', 'playwright-report', '__pycache__', '.git'}
BACKEND_NOT_COPIED = {'build', 'dist', 'tests', '__pycache__', '.venv', 'node_modules'}
STAMP = '.dependency-stamp.json'
RETRY_DELAYS = (3, 8)  # two retries at most, only for transient file locks


class WorkspaceError(ValueError):
    pass


def _refuse_links(directory, skip):
    for current, names, files in os.walk(directory):
        names[:] = [name for name in names if name not in skip]
        for name in (*names, *files):
            if (Path(current) / name).is_symlink():
                raise WorkspaceError(f'Refusing to mirror a linked path into the build workspace: {Path(current) / name}')


def _replace(source, destination, skip=()):
    """Copy a tree over a clean destination, keeping nothing of the previous copy except the entries listed in `skip` (for example node_modules)."""
    if destination.exists():
        for entry in destination.iterdir():
            if entry.name in skip: continue
            shutil.rmtree(entry) if entry.is_dir() and not entry.is_symlink() else entry.unlink()
    destination.mkdir(parents=True, exist_ok=True)
    _refuse_links(source, skip)
    for entry in source.iterdir():
        if entry.name in skip: continue
        target = destination / entry.name
        if entry.is_dir(): shutil.copytree(entry, target, ignore=shutil.ignore_patterns(*NOT_COPIED), symlinks=False)
        else: shutil.copy2(entry, target)


def mirror(root, workspace):
    """Refresh the workspace from the checkout. `node_modules` and a previous `dist` of the workspace are kept or rebuilt, never copied from the checkout."""
    root, workspace = Path(root), Path(workspace)
    if workspace.is_symlink() or any(parent.is_symlink() for parent in workspace.parents if parent.exists() and parent != Path(parent.anchor)):
        raise WorkspaceError('The frontend workspace may not be a linked path.')
    workspace.mkdir(parents=True, exist_ok=True)
    _replace(root / 'frontend', workspace / 'frontend', skip=NOT_COPIED)
    _replace(root / 'scripts', workspace / 'scripts', skip={'__pycache__'})
    _replace(root / 'backend', workspace / 'backend', skip=BACKEND_NOT_COPIED)
    # Browser tests read synthetic CSV fixtures from backend/tests/fixtures; only that data directory is mirrored, never the Python tests.
    fixtures = root / 'backend/tests/fixtures'
    if fixtures.is_dir():
        _refuse_links(fixtures, set())
        shutil.rmtree(workspace / 'backend/tests', ignore_errors=True)
        shutil.copytree(fixtures, workspace / 'backend/tests/fixtures', symlinks=False)
    identity = root / 'backend/build/build-version.json'
    if identity.is_file():
        (workspace / 'backend/build').mkdir(parents=True, exist_ok=True)
        shutil.copy2(identity, workspace / 'backend/build/build-version.json')
    shutil.rmtree(workspace / 'frontend/dist', ignore_errors=True)  # a stale previous build can never be published
    return workspace


def dependency_stamp(root, node_version):
    digest = hashlib.sha256()
    for name in ('package.json', 'package-lock.json'):
        digest.update((Path(root) / 'frontend' / name).read_bytes())
    digest.update(str(node_version).split('.')[0].encode())
    return digest.hexdigest()


def is_current(workspace, stamp):
    modules = Path(workspace) / 'frontend/node_modules'
    try:
        saved = json.loads((Path(workspace) / STAMP).read_text())
    except (OSError, ValueError):
        return False
    return saved.get('stamp') == stamp and (modules / '.package-lock.json').is_file()


def remove_modules(workspace):
    """Remove only the workspace's own installation (never the developer's). Raises WorkspaceError if the operating system refuses."""
    modules = Path(workspace) / 'frontend/node_modules'
    if modules.is_symlink(): raise WorkspaceError('The workspace node_modules may not be linked.')
    try:
        shutil.rmtree(modules)
    except FileNotFoundError:
        pass
    except OSError as error:
        raise WorkspaceError(f'Could not remove the previous workspace installation {modules}: {error}. Close programs using it and retry; nothing outside the workspace was changed.') from error


def install(workspace, stamp, run, sleep=time.sleep):
    """`npm ci` in the workspace through `run(label)`, skipped when current and retried at most twice for transient locks only.
    Returns the number of installations performed (0 or 1+)."""
    if is_current(workspace, stamp):
        print('Locked frontend dependencies in the isolated workspace are current; no installation needed.', flush=True)
        return 0
    (Path(workspace) / STAMP).unlink(missing_ok=True)
    attempts = len(RETRY_DELAYS) + 1
    for number in range(1, attempts + 1):
        try:
            run('Install locked frontend dependencies')
            (Path(workspace) / STAMP).write_text(json.dumps(dict(stamp=stamp)))
            return number
        except ValueError as failure:
            lock = getattr(failure, 'lock', None)
            if not (lock and lock['kind'] == 'locked') or number == attempts:
                raise
            delay = RETRY_DELAYS[number - 1]
            print(f'A file in the isolated workspace was locked ({lock["code"]}); retrying in {delay}s (attempt {number + 1} of {attempts}).', flush=True)
            remove_modules(workspace)
            sleep(delay)


def _files(directory):
    return sorted(p.relative_to(directory).as_posix() for p in Path(directory).rglob('*') if p.is_file())


def publish_dist(workspace, root):
    """Replace `frontend/dist` with the verified workspace build. Returns the number of files published."""
    built, target = Path(workspace) / 'frontend/dist', Path(root) / 'frontend/dist'
    if not (built / 'index.html').is_file(): raise WorkspaceError('The isolated frontend build produced no index.html; nothing was published.')
    _refuse_links(built, set())
    staging = target.with_name('dist.' + uuid.uuid4().hex[:8] + '.new')
    previous = target.with_name('dist.' + uuid.uuid4().hex[:8] + '.old')
    try:
        shutil.copytree(built, staging, symlinks=False)
        if _files(staging) != _files(built): raise WorkspaceError('Published frontend assets differ from the verified build.')
        if target.exists(): target.rename(previous)
        staging.rename(target)
    except OSError as error:
        shutil.rmtree(staging, ignore_errors=True)
        if previous.exists() and not target.exists(): previous.rename(target)  # put the old assets back
        raise WorkspaceError(f'Could not publish frontend assets to {target}: {error}. A program may be holding files in it; close it and retry.') from error
    shutil.rmtree(previous, ignore_errors=True)
    return len(_files(target))
