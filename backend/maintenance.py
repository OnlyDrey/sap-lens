"""Local-only deployment maintenance. Never exposed through the HTTP API.

Backups are private data, not distribution artifacts. Restore stages into empty
operator-selected directories; it never overwrites a live or unknown data store.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

# Maintenance must not mutate an immutable/extracted deployment bundle.
sys.dont_write_bytecode = True

MAX_BYTES = 4 * 1024**3
MAX_FILES = 100000
VOLATILE = {'runtime.json', '.sap-lens-instance.lock'}


class MaintenanceError(ValueError):
    """Controlled operational guidance, without source data or exception paths."""


def version_key(value):
    match = re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-(alpha|beta|rc|dev)[.-]([0-9]+|local)(?:\.([1-9][0-9]*))?)?(?:\+local\.[0-9a-f]{12})?', value)
    if not match: raise MaintenanceError('Unsupported installed version; review upgrade compatibility explicitly.')
    if match[6] and (match[4] != 'dev' or match[5] == 'local'):
        raise MaintenanceError('Only legacy CI development builds have an attempt suffix.')
    return (*map(int, match.group(1, 2, 3)), {'dev': -1, 'alpha': 0, 'beta': 1, 'rc': 2, None: 3}[match[4]], 0 if match[5] in (None, 'local') else int(match[5]), int(match[6] or 1))


def ensure_upgrade(installed, target):
    if version_key(target) < version_key(installed): raise MaintenanceError('Downgrades are not supported. Restore the matching application and a compatible backup explicitly.')


def directory(value):
    value = Path(value).expanduser()
    if not value.is_absolute() or any(part.is_symlink() for part in [value, *value.parents]):
        raise MaintenanceError('Use an absolute dedicated directory without links.')
    value = value.resolve()
    protected = {Path(p).resolve() for p in ('/', '/etc', '/var', '/var/lib', '/usr', '/opt', '/home', '/tmp')}
    protected.add(Path.home().resolve())
    if value == Path(value.anchor) or value in protected:
        raise MaintenanceError('An operating-system or home directory is not an application data directory.')
    if os.name == 'nt' and value in {Path(os.environ.get('WINDIR', 'C:/Windows')).resolve(), Path(os.environ.get('ProgramFiles', 'C:/Program Files')).resolve()}:
        raise MaintenanceError('Use a dedicated application directory.')
    return value


def digest(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def private_file(path):
    if os.name != 'nt':
        path.chmod(0o600)
        return
    sid = subprocess.check_output(['powershell', '-NoProfile', '-Command', '[Security.Principal.WindowsIdentity]::GetCurrent().User.Value'], text=True).strip()
    if not re.fullmatch(r'S-1-[0-9-]+', sid): raise MaintenanceError('Cannot resolve the current backup owner.')
    subprocess.run(['icacls.exe', str(path), '/inheritance:r', '/grant:r', '*' + sid + ':F', '*S-1-5-18:F'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def owned(data, mode, allow_legacy=False):
    marker = data / 'deployment.json'
    if marker.is_file() and not marker.is_symlink():
        if json.loads(marker.read_text(encoding='utf-8')) == {'version': 1, 'mode': mode}: return
    if allow_legacy and mode == 'desktop' and (data / 'settings.json').is_file():
        settings = json.loads((data / 'settings.json').read_text(encoding='utf-8'))
        if isinstance(settings, dict) and ('schema_version' in settings or 'data_csv_path' in settings): return
    raise MaintenanceError('Unrecognized or incompatible data directory; no data was removed.')


@contextmanager
def stopped(data, mode, allow_legacy=False):
    owned(data, mode, allow_legacy)
    if (data / '.sap-lens-instance.lock').is_symlink(): raise MaintenanceError('Storage lock may not be a link.')
    instance = None
    lease = None
    try:
        if mode == 'desktop' and os.name == 'nt':
            from instance import WindowsInstance
            instance = WindowsInstance()
            if not instance.acquire(): raise MaintenanceError('Close SAP Lens before maintenance.')
        from storage_lease import StorageLease
        lease = StorageLease(data, mode).acquire()
        yield
    finally:
        if lease: lease.close()
        if instance: instance.close()


def inventory(root, prefix):
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink(): raise MaintenanceError('Backups cannot follow links to external files.')
        if not path.is_file() or path.name in VOLATILE or '.log' in path.suffixes: continue
        name = prefix + '/' + path.relative_to(root).as_posix()
        safe_member(name)
        stat = path.stat()
        result[name] = (path, stat.st_size, stat.st_mtime_ns, stat.st_ino, digest(path))
    return result


def safe_member(name):
    path = PurePosixPath(name)
    if (not name or '\\' in name or ':' in name or path.is_absolute()
            or any(part in ('', '.', '..') for part in name.split('/'))
            or path.parts[0] not in ('data', 'config') and name != 'manifest.json'):
        raise MaintenanceError('Unsafe backup member.')
    reserved = {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}
    if any(part.endswith((' ','.')) or part.split('.')[0].upper() in reserved for part in path.parts):
        raise MaintenanceError('Backup contains non-portable Windows path names.')
    return path


def backup(data, output, mode, application_version, config=None, allow_legacy=False):
    data, output = directory(data), Path(output).absolute()
    output = directory(output.parent) / output.name
    if not output.name.endswith('.tar.gz'): raise MaintenanceError('Choose a private .tar.gz backup file.')
    version_key(application_version)
    if output.exists() or output.is_symlink() or output.is_relative_to(data):
        raise MaintenanceError('Choose a new backup file outside the application data directory.')
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if config is not None:
        config = directory(config)
        if output.is_relative_to(config) or data.is_relative_to(config) or config.is_relative_to(data):
            raise MaintenanceError('Use separate dedicated data, configuration and backup locations.')
    with stopped(data, mode, allow_legacy):
        members = inventory(data, 'data')
        if config: members.update(inventory(config, 'config'))
        if len(members) > MAX_FILES or sum(row[1] for row in members.values()) > MAX_BYTES:
            raise MaintenanceError('Backup exceeds supported limits (100000 files / 4 GiB).')
        if len({name.casefold() for name in members}) != len(members): raise MaintenanceError('Case-colliding backup paths are not portable.')
        settings = data / 'settings.json'
        schema = json.loads(settings.read_text(encoding='utf-8')).get('schema_version', 1) if settings.exists() else 1
        manifest = dict(schema=1, mode=mode, application_version=application_version, settings_schema=schema,
                        created_at=datetime.now(timezone.utc).isoformat(), files={name: row[4] for name, row in members.items()})
        descriptor, temporary = tempfile.mkstemp(prefix='.sap-lens-backup-', dir=output.parent)
        os.close(descriptor); temporary = Path(temporary)
        try:
            private_file(temporary)
            with temporary.open('wb') as stream:
                with tarfile.open(fileobj=stream, mode='w:gz', compresslevel=1) as archive:
                    for name, (path, size, mtime, inode, _) in members.items():
                        current = path.stat()
                        if (current.st_size, current.st_mtime_ns, current.st_ino) != (size, mtime, inode): raise MaintenanceError('Source changed during backup; no backup was committed.')
                        item = tarfile.TarInfo(name); item.size = size; item.mode = 0o600
                        with path.open('rb') as source: archive.addfile(item, source)
                        current = path.stat()
                        if (current.st_size, current.st_mtime_ns, current.st_ino) != (size, mtime, inode): raise MaintenanceError('Source changed during backup.')
                    payload = (json.dumps(manifest, indent=2) + '\n').encode('utf-8')
                    import io
                    item = tarfile.TarInfo('manifest.json'); item.size = len(payload); item.mode = 0o600
                    archive.addfile(item, io.BytesIO(payload))
                stream.flush(); os.fsync(stream.fileno())
            verify(temporary, mode, application_version)
            # Same-directory hard link commits without overwriting an existing backup.
            os.link(temporary, output)
        finally: temporary.unlink(missing_ok=True)
    return dict(backup=str(output), sha256=digest(output), files=len(members), mode=mode)


def verify(archive, mode, target_version):
    archive = Path(archive)
    if archive.is_symlink(): raise MaintenanceError('Backup archives may not be links.')
    with tarfile.open(archive, 'r:gz') as source:
        members = source.getmembers()
        names = [item.name for item in members]
        if (len(members) > MAX_FILES + 1 or len({name.casefold() for name in names}) != len(names)
                or sum(item.size for item in members) > MAX_BYTES + 16*1024*1024):
            raise MaintenanceError('Backup limits or duplicate paths are invalid.')
        for item in members:
            safe_member(item.name)
            if item.size < 0 or not item.isfile(): raise MaintenanceError('Backup links and non-regular members are forbidden.')
        header = source.getmember('manifest.json')
        if header.size > 16*1024*1024: raise MaintenanceError('Backup manifest is too large.')
        manifest = json.load(source.extractfile(header))
        if not isinstance(manifest,dict) or manifest.get('schema') != 1 or manifest.get('mode') != mode:
            raise MaintenanceError('Backup format/deployment mode is incompatible.')
        ensure_upgrade(manifest['application_version'], target_version)
        from config_models import AppConfig
        if type(manifest.get('settings_schema',1)) is not int or manifest.get('settings_schema',1)<1 or manifest.get('settings_schema', 1) > AppConfig.model_fields['schema_version'].default:
            raise MaintenanceError('Backup settings schema requires a newer application.')
        if not isinstance(manifest.get('files'),dict) or any(not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value) for value in manifest.get('files',{}).values()): raise MaintenanceError('Invalid backup digest manifest.')
        if set(names) != {'manifest.json', *manifest['files']}:
            raise MaintenanceError('Unexpected or missing backup members.')
        for name, expected in manifest['files'].items():
            with source.extractfile(name) as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                    raise MaintenanceError('Backup member checksum mismatch.')
        return manifest


def restore(archive, data, mode, target_version, config=None, confirm=False):
    if not confirm: raise MaintenanceError('Restore requires explicit --confirm-restore.')
    manifest = verify(archive, mode, target_version)
    data = directory(data)
    config = directory(config) if config is not None else None
    has_config = any(name.startswith('config/') for name in manifest['files'])
    if has_config and config is None: raise MaintenanceError('This backup also needs an empty --config-destination.')
    destinations = [data, *([config] if config else [])]
    if config and (data.is_relative_to(config) or config.is_relative_to(data)): raise MaintenanceError('Restore destinations must be separate.')
    for destination in destinations:
        if destination.exists() and any(path != data / '.sap-lens-instance.lock' for path in destination.iterdir()): raise MaintenanceError('Restore only into empty directories. Existing state is preserved; stop the application and review a directory switch explicitly.')
    for destination in destinations: destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    created = []
    with empty_store_lock(data, mode):
        try:
            with tarfile.open(archive, 'r:gz') as source:
                for name, expected in manifest['files'].items():
                    if name in ('data/runtime.json', 'data/.sap-lens-instance.lock'): raise MaintenanceError('Volatile runtime state cannot be restored.')
                    parts = safe_member(name).parts
                    root = data if parts[0] == 'data' else config
                    path = root.joinpath(*parts[1:]); path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    with path.open('xb') as output:
                        created.append(path)
                        private_file(path)
                        with source.extractfile(name) as incoming: shutil.copyfileobj(incoming, output)
                    if digest(path) != expected: raise MaintenanceError('Restored member changed after backup verification.')
            owned(data, mode)
        except Exception:
            # Cleanup stays inside the runtime lease. Original stores were never
            # touched, and a new process cannot consume partially restored data.
            for path in reversed(created): path.unlink(missing_ok=True)
            raise

    return dict(restored=True, files=len(created), mode=mode, application_version=manifest['application_version'])


@contextmanager
def empty_store_lock(data, mode):
    if (data / '.sap-lens-instance.lock').is_symlink(): raise MaintenanceError('Storage lock may not be a link.')
    from storage_lease import StorageLease
    instance = None
    lease = None
    try:
        if mode == 'desktop' and os.name == 'nt':
            from instance import WindowsInstance
            instance = WindowsInstance()
            if not instance.acquire(): raise MaintenanceError('Close SAP Lens before restore.')
        # Hold the actual runtime lease without creating a marker which would
        # conflict with the verified backup's deployment marker.
        lease = StorageLease(data, mode, initialize=False).acquire()
        yield
    finally:
        if lease: lease.close()
        if instance: instance.close()


def purge(data, mode, confirm=False):
    if not confirm: raise MaintenanceError('Data removal requires explicit --confirm-purge. Back up first.')
    data = directory(data)
    with stopped(data, mode):
        paths = list(data.rglob('*'))
        if any(path.is_symlink() or not (path.is_file() or path.is_dir()) for path in paths):
            raise MaintenanceError('Unrecognized links or file types; no private data was removed.')
        files = [path for path in paths if path.is_file() and path != data / '.sap-lens-instance.lock']
        for path in files: path.unlink()
        for path in sorted((path for path in paths if path.is_dir()), key=lambda path: len(path.parts), reverse=True): path.rmdir()
    # Retain the nonprivate lock stub/root: never remove files after releasing
    # the lease, when another process could have legitimately started afresh.
    return dict(purged=True, files=len(files), directory_retained=True)


def cli(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['backup', 'verify', 'restore', 'version-check', 'purge'])
    parser.add_argument('--data', type=Path); parser.add_argument('--config-dir', type=Path)
    parser.add_argument('--output', type=Path); parser.add_argument('--archive', type=Path)
    parser.add_argument('--mode', choices=['desktop', 'server'], default='server')
    parser.add_argument('--application-version'); parser.add_argument('--target-version')
    parser.add_argument('--config-destination', type=Path)
    parser.add_argument('--allow-legacy', action='store_true'); parser.add_argument('--confirm-restore', action='store_true')
    parser.add_argument('--confirm-purge', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(arguments)
    from version import VERSION
    try:
        if args.action == 'backup':
            if args.data is None or args.output is None: raise MaintenanceError('Backup needs --data and --output.')
            result = backup(args.data, args.output, args.mode, args.application_version or VERSION, args.config_dir, args.allow_legacy)
        elif args.action == 'purge':
            if args.data is None: raise MaintenanceError('Data removal needs --data.')
            result = purge(args.data, args.mode, args.confirm_purge)
        elif args.action == 'version-check':
            ensure_upgrade(args.application_version, args.target_version); result = dict(compatible=True)
        elif args.action == 'verify': result = verify(args.archive, args.mode, args.target_version or VERSION); result = dict(verified=True, files=len(result['files']))
        else: result = restore(args.archive, args.data, args.mode, args.target_version or VERSION, args.config_destination, args.confirm_restore)
        if args.report: args.report.write_text(json.dumps(dict(status='passed', **result)) + '\n', encoding='utf-8')
        if sys.stdout: print(json.dumps(result))
        return 0
    except Exception as error:
        result = dict(status='failed', action=args.action, category=type(error).__name__, message=str(error) if isinstance(error,MaintenanceError) else 'Operation failed safely; inspect permissions, application state and backup compatibility.',
                      recovery='Stop the application, verify directory ownership/version/permissions and the backup. Existing stores are never overwritten by restore.')
        if args.report: args.report.write_text(json.dumps(result) + '\n', encoding='utf-8')
        if sys.stderr: print(json.dumps(result), file=sys.stderr)
        return 1


if __name__ == '__main__': raise SystemExit(cli())
