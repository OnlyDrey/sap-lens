"""Upgrade of an existing installation to the SQLite source store: detection, verified backup, idempotent migration, recovery and confirmation.

Invariants
* The JSON stores (settings, review decisions, periods, frozen evidence, content-addressed snapshots) are never modified, moved or deleted by the
  migration. The SQLite store is derived from them, so the migration cannot lose or alter business data and an older SAP Lens keeps working on
  the same directory.
* An existing installation is backed up first with the same verified archive engine as manual backups. If that backup cannot be created and
  verified, the migration does not run: the store is not created and the application keeps running from the JSON snapshots.
* The backup is retained until an administrator explicitly confirms that the upgraded installation works. It is never removed by age or by the
  scheduled-backup retention (it lives in its own folder, outside the numbered operation folders that retention manages).
* Every step is idempotent: an interrupted migration is resumed on the next start, a damaged database is moved aside and rebuilt, a database from a
  newer version is left untouched and simply not used.
Runs under the storage lease (single process), before the application serves requests, and never raises into startup."""
import json
import logging
import shutil
import uuid
from pathlib import Path

import application_backups as backups
import maintenance as engine
import source_store
import store_db
from config import atomic_write, config_dir
from version import VERSION

logger = logging.getLogger('sap-lens')
FOLDER = Path('.application-backups') / 'migration'
ARCHIVE = 'pre-migration.tar.gz'
RECORD = 'record.json'


def _root(data):
    return Path(data) / FOLDER


def _records(data):
    root = _root(data)
    if not root.is_dir():
        return []
    result = []
    for folder in sorted(root.iterdir()):
        path = folder / RECORD
        try:
            if backups.ID.fullmatch(folder.name) and not engine.linked(folder) and path.is_file() and not engine.linked(path) and path.stat().st_size < 64000:
                value = json.loads(path.read_text(encoding='utf-8'))
                if isinstance(value, dict) and value.get('id') == folder.name:
                    result.append(value)
        except (OSError, ValueError):
            continue
    return sorted(result, key=lambda item: item.get('created', ''))


def _write(data, record):
    folder = _root(data) / record['id']
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_write(folder / RECORD, (json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n').encode())
    engine.private_file(folder / RECORD)


def installation_present(data):
    """An existing installation has configuration or imported data; an empty directory is a fresh install."""
    data = Path(data)
    return (data / 'settings.json').is_file() or (data / 'csv-data').is_dir()


def _mirror_all(data, record=None):
    """Bring the store in line with the committed configuration and prove every active revision reads back with a valid digest."""
    from config import get_settings
    settings = get_settings()
    summary = source_store.reconcile(settings)
    problems = list(summary['failed'])
    for source in source_store.SOURCES:
        reference = settings.data_lifecycle.sources.get(source)
        if reference and source not in problems and source_store.read(source, reference.snapshot) is None:
            problems.append(source)
    return summary, problems


def _legacy_cache(data):
    """The first derived cache lived in a separate file; its content is rebuildable and now lives in the store."""
    folder = Path(data) / 'cache'
    for name in ('derived.sqlite3', 'derived.sqlite3-wal', 'derived.sqlite3-shm', '.cache-key'):
        (folder / name).unlink(missing_ok=True)
    try:
        folder.rmdir()
    except OSError:
        pass


def run(lease, server=None):
    """Detect, back up, migrate. Returns a small status dict; every failure degrades to "store not in use", never to a startup failure."""
    data = Path(lease.directory).resolve()
    try:
        if not installation_present(data) and not store_db.path().exists():
            store_db.connect().close()
            return dict(state='fresh')
        if store_db.path().exists():
            source_store.recover_orphans(0)  # nothing is live at start-up: revisions staged by an interrupted operation are orphans
        pending = [item for item in _records(data) if item.get('status') in {'backup_verified', 'migrating'}]
        if store_db.path().exists():
            problems = store_db.health()
            if problems:
                try:
                    store_db.connect(create=False).close()
                except store_db.SchemaTooNew:
                    logger.warning('The SQLite store was written by a newer SAP Lens and is not used by this version.')
                    return dict(state='newer')
                except store_db.StoreUnavailable:
                    pass
                moved = store_db.quarantine()
                logger.warning('The SQLite store failed its integrity check and was moved aside (%s); it is rebuilt from the JSON snapshots.', moved.name if moved else '')
                if _records(data):  # already upgraded once (backup exists or was confirmed): the JSON stores are untouched, so just rebuild
                    store_db.connect().close()
                    summary, _ = _mirror_all(data)
                    return dict(state='rebuilt', **summary)
            elif not pending:
                summary, _ = _mirror_all(data)
                _legacy_cache(data)
                return dict(state='current', **summary)
        return _migrate(lease, server, data, pending[-1] if pending else None)
    except store_db.SchemaTooNew:
        return dict(state='newer')
    except Exception as error:  # noqa: BLE001 - the JSON stores remain fully usable without the SQLite store
        logger.warning('SQLite store migration did not complete (%s). SAP Lens continues from its JSON stores.', type(error).__name__)
        return dict(state='failed')


def _migrate(lease, server, data, record):
    record = record or dict(id=uuid.uuid4().hex, created=store_db.now(), app_version=VERSION, from_schema=0, to_schema=store_db.SCHEMA_VERSION, status='new')
    if record['status'] == 'new':
        exclusions = backups.protected(data, server) - {'deployment.json'}
        from backup_schedule import check_space
        try:
            check_space(data, exclusions)
            archive = _root(data) / record['id'] / ARCHIVE
            archive.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            result = engine.backup(data, archive, lease.mode, VERSION, _lease=lease, _exclude=exclusions)
        except Exception as error:  # noqa: BLE001
            # Application-authored messages (MaintenanceError/ValueError) are static and safe; anything else is reported by type and OS error code only.
            reason = str(error) if isinstance(error, ValueError) else f'{type(error).__name__} errno={getattr(error, "errno", None)} winerror={getattr(error, "winerror", None)}'
            logger.warning('The pre-migration backup could not be created or verified (%s); the SQLite store is not created yet.', reason)
            shutil.rmtree(_root(data) / record['id'], ignore_errors=True)
            return dict(state='backup_failed')
        record.update(status='backup_verified', backup=dict(file=ARCHIVE, sha256=result['sha256'], files=result['files'], size=archive.stat().st_size, verified=True))
        _write(data, record)
    record['status'] = 'migrating'
    _write(data, record)
    store_db.connect().close()
    summary, problems = _mirror_all(data)
    if problems:
        record.update(status='backup_verified', problems=problems)  # resume on the next start; the verified backup is kept
        _write(data, record)
        return dict(state='incomplete', problems=problems)
    with store_db.transaction() as connection:
        connection.execute('INSERT OR REPLACE INTO migrations (id, started, finished, from_version, to_version, backup_id, backup_sha256, status) VALUES (?,?,?,?,?,?,?,\'migrated\')',
                           (record['id'], record['created'], store_db.now(), record['from_schema'], record['to_schema'], record['id'], record['backup']['sha256']))
        connection.execute('INSERT OR REPLACE INTO meta (key, value) VALUES (\'migrated_from\', ?)', (VERSION,))
    record.update(status='migrated', migrated_at=store_db.now(), summary=summary, problems=[])
    _write(data, record)
    _legacy_cache(data)
    return dict(state='migrated', backup_id=record['id'], **summary)


def status(data=None):
    """Public status for the administrator: store health and the pre-migration backup that still waits for confirmation."""
    data = Path(data or config_dir())
    records = _records(data)
    held = [item for item in records if item.get('status') == 'migrated' and (data / FOLDER / item['id'] / ARCHIVE).is_file()]
    current = held[-1] if held else None
    kept = [item for item in records if item.get('status') == 'confirmed' and (data / FOLDER / item['id'] / ARCHIVE).is_file()]
    try:
        size = sum(path.stat().st_size for path in store_db.directory().glob('sap-lens.sqlite3*') if path.is_file())
    except OSError:
        size = 0
    revisions = source_store.revisions()
    problems = store_db.health() if store_db.path().exists() else ['The SQLite store does not exist.']
    state = 'newer' if any('newer' in item for item in problems) else 'ready' if not problems else 'unavailable'
    result = dict(state=state, schema_version=store_db.SCHEMA_VERSION, size_bytes=size, revisions=[item for item in revisions if item['status'] == 'active'],
                  requires_confirmation=bool(current), backup=None, confirmed=[dict(id=item['id'], confirmed_at=item.get('confirmed_at'), confirmed_by=item.get('confirmed_by'))
                                                                              for item in records if item.get('confirmed_at')])
    result['retained'] = None if not kept else dict(id=kept[-1]['id'], created=kept[-1]['created'], confirmed_at=kept[-1].get('confirmed_at'), confirmed_by=kept[-1].get('confirmed_by'),
                                                     size_bytes=kept[-1]['backup']['size'], sha256=kept[-1]['backup']['sha256'])
    if current:
        result['backup'] = dict(id=current['id'], created=current['created'], sha256=current['backup']['sha256'], size_bytes=current['backup']['size'],
                                app_version=current.get('app_version'), files=current['backup']['files'])
    return result


class NotReady(ValueError):
    pass


def confirm(identity, actor='', data=None):
    """An administrator states that the upgraded installation works. The archive is NOT removed by this: it stays until an administrator deletes it explicitly
    (`delete_backup`), and the automatic backup retention never applies to it."""
    data = Path(data or config_dir())
    record = next((item for item in _records(data) if item['id'] == identity), None)
    if not record or record.get('status') != 'migrated':
        raise NotReady('There is no completed migration with this identifier.')
    problems = store_db.health()
    summary, failed = _mirror_all(data)
    if problems or failed:
        raise NotReady('The upgraded store is not healthy yet, so the backup is kept: ' + '; '.join(problems or failed))
    record.update(status='confirmed', confirmed_at=store_db.now(), confirmed_by=actor or 'administrator')
    _write(data, record)
    with store_db.transaction() as connection:
        connection.execute('UPDATE migrations SET status=\'confirmed\', confirmed_at=?, confirmed_by=? WHERE id=?', (record['confirmed_at'], record['confirmed_by'], identity))
    return status(data)


def delete_backup(identity, actor='', data=None):
    """Explicit administrative deletion of a confirmed migration backup (never automatic, never before confirmation)."""
    data = Path(data or config_dir())
    record = next((item for item in _records(data) if item['id'] == identity), None)
    if not record or record.get('status') != 'confirmed':
        raise NotReady('Only the backup of a confirmed migration can be deleted.')
    archive = _root(data) / identity / ARCHIVE
    if archive.is_symlink() or not archive.is_file():
        raise NotReady('The migration backup is not present.')
    archive.unlink()
    record.update(backup_deleted_at=store_db.now(), backup_deleted_by=actor or 'administrator')
    _write(data, record)
    return status(data)


def rebuild(data=None):
    """Discard the store and rebuild it from the JSON snapshots (recovery and support operation; business data is untouched)."""
    store_db.quarantine()
    store_db.connect().close()
    return _mirror_all(Path(data or config_dir()))[0]
