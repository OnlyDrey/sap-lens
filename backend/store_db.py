"""Connection, schema ladder, permissions and signing key of the application SQLite store.

One database file (`store/sap-lens.sqlite3`) holds everything SQLite is used for: source revisions, the derived-state cache and migration
records. Review decisions, periods and frozen evidence stay in their validated JSON stores. The database is *rebuildable* from the immutable
JSON snapshots, is excluded from application backups, and is never required: every consumer falls back to the JSON snapshots when it is
unavailable (`StoreUnavailable`).

Concurrency model: WAL journal, a short-lived connection per operation (no connection is shared between threads), `BEGIN IMMEDIATE` for every
write transaction, a generous `busy_timeout`, and the storage lease guarantees a single application process per data directory.
Schema versioning: `PRAGMA user_version` plus an ordered ladder of idempotent steps. A database written by a newer SAP Lens is left untouched
and reported (never downgraded or deleted)."""
import hashlib
import logging
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from config import config_dir

logger = logging.getLogger('sap-lens')
DIRECTORY = 'store'
FILE = 'sap-lens.sqlite3'
KEY_FILE = '.key'
BUSY_MS = 15000
lock = threading.RLock()


class StoreUnavailable(Exception):
    """The store cannot be used right now (corrupt, newer schema, unwritable). Callers fall back to the JSON snapshots."""


class SchemaTooNew(StoreUnavailable):
    pass


def directory():
    return Path(config_dir()) / DIRECTORY


def path():
    return directory() / FILE


def now():
    return datetime.now(timezone.utc).isoformat()


def private_directory():
    target = directory()
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != 'nt':
        target.chmod(0o700)  # the directory may pre-exist with the process umask
    return target


def key():
    """Per-installation signing secret for serialized derived values (0600, never part of a backup)."""
    target = private_directory() / KEY_FILE
    if target.is_file() and target.stat().st_size == 32:
        return target.read_bytes()
    value = secrets.token_bytes(32)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(value)
    return value


def source_columns():
    from config_models import FIELDS, USER_FIELDS
    from sod_import import HEADERS
    return {'roles': tuple(FIELDS), 'users': tuple(USER_FIELDS), 'sod': tuple(HEADERS)}


KEY_COLUMN = {'roles': 'AGR_NAME', 'users': 'USERNAME', 'sod': 'RISK'}


def _identifier(name):
    if not name.replace('_', '').isalnum():
        raise ValueError('Unsafe identifier.')
    return '"' + name + '"'


def _v1(connection):
    connection.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID')
    connection.execute(
        'CREATE TABLE IF NOT EXISTS source_revisions (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, scope TEXT NOT NULL DEFAULT \'\', '
        'sequence INTEGER NOT NULL, snapshot TEXT NOT NULL, row_count INTEGER NOT NULL, entity_count INTEGER NOT NULL, rows_digest TEXT NOT NULL, '
        'report TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN (\'staged\',\'active\',\'superseded\')), created TEXT NOT NULL, activated TEXT, '
        'supersedes INTEGER REFERENCES source_revisions(id) ON DELETE SET NULL, '
        'UNIQUE (source, scope, sequence), UNIQUE (source, scope, snapshot))')
    # Exactly one active revision per (source, scope): the database itself rejects a second one, so a replacement is one atomic status flip.
    connection.execute('CREATE UNIQUE INDEX IF NOT EXISTS one_active_revision ON source_revisions (source, scope) WHERE status=\'active\'')
    for source, columns in source_columns().items():
        body = ', '.join(f'{_identifier(name)} TEXT NOT NULL DEFAULT \'\'' for name in columns)
        connection.execute(f'CREATE TABLE IF NOT EXISTS rows_{source} (revision_id INTEGER NOT NULL REFERENCES source_revisions(id) ON DELETE CASCADE, '
                           f'ordinal INTEGER NOT NULL, {body}, PRIMARY KEY (revision_id, ordinal)) WITHOUT ROWID')
        connection.execute(f'CREATE INDEX IF NOT EXISTS rows_{source}_entity ON rows_{source} (revision_id, {_identifier(KEY_COLUMN[source])})')
    # `revisions` lists the source revisions a derived value was computed from, so superseding or pruning a revision invalidates exactly its dependants.
    connection.execute('CREATE TABLE IF NOT EXISTS derived (kind TEXT NOT NULL, deps TEXT NOT NULL, created TEXT NOT NULL, size INTEGER NOT NULL, '
                       'revisions TEXT NOT NULL DEFAULT \'\', mac TEXT NOT NULL, payload BLOB NOT NULL, PRIMARY KEY (kind, deps)) WITHOUT ROWID')
    connection.execute('CREATE INDEX IF NOT EXISTS derived_created ON derived (kind, created)')
    connection.execute('CREATE TABLE IF NOT EXISTS migrations (id TEXT PRIMARY KEY, started TEXT NOT NULL, finished TEXT, from_version INTEGER NOT NULL, '
                       'to_version INTEGER NOT NULL, backup_id TEXT, backup_sha256 TEXT, status TEXT NOT NULL, confirmed_at TEXT, confirmed_by TEXT) WITHOUT ROWID')


def _v2(connection):
    # Fingerprint of the exact input that produced a revision (file content + the settings and code that shape parsing): lets a dynamic source
    # that has not changed skip parsing, diffing and rebuilding. Empty means unknown, which always takes the full path.
    if 'fingerprint' not in {row[1] for row in connection.execute('PRAGMA table_info(source_revisions)')}:
        connection.execute('ALTER TABLE source_revisions ADD COLUMN fingerprint TEXT NOT NULL DEFAULT \'\'')


def _v3(connection):
    # Staging ownership: the operation that staged a revision. Cleanup only ever removes revisions owned by its own operation; revisions of
    # operations that no longer exist are recovered by age or at start-up. Activation clears the owner.
    if 'owner' not in {row[1] for row in connection.execute('PRAGMA table_info(source_revisions)')}:
        connection.execute('ALTER TABLE source_revisions ADD COLUMN owner TEXT NOT NULL DEFAULT \'\'')


LADDER = {1: _v1, 2: _v2, 3: _v3}
SCHEMA_VERSION = max(LADDER)


def connect(*, create=True):
    """A new connection with the schema brought up to date. Raises StoreUnavailable; never repairs or deletes anything by itself."""
    target = path()
    if not create and not target.exists():
        raise StoreUnavailable('The SQLite store does not exist.')
    try:
        private_directory()
        if not target.exists():
            os.close(os.open(target, os.O_WRONLY | os.O_CREAT, 0o600))  # created private; SQLite copies the mode to -wal/-shm
        connection = sqlite3.connect(target, timeout=BUSY_MS / 1000, isolation_level=None)
    except (OSError, sqlite3.Error) as error:
        raise StoreUnavailable('The SQLite store cannot be opened.') from error
    try:
        connection.execute(f'PRAGMA busy_timeout={BUSY_MS}')
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA synchronous=NORMAL')
        connection.execute('PRAGMA foreign_keys=ON')
        version = connection.execute('PRAGMA user_version').fetchone()[0]
        if version > SCHEMA_VERSION:
            raise SchemaTooNew(f'The store was written by a newer SAP Lens (schema {version}).')
        while version < SCHEMA_VERSION:
            version += 1
            connection.execute('BEGIN IMMEDIATE')
            try:
                LADDER[version](connection)
                connection.execute(f'PRAGMA user_version={version}')
                connection.execute('COMMIT')
            except BaseException:
                connection.execute('ROLLBACK')
                raise
        return connection
    except StoreUnavailable:
        connection.close()
        raise
    except sqlite3.Error as error:
        connection.close()
        raise StoreUnavailable('The SQLite store is unreadable.') from error


class transaction:
    """`with transaction() as connection:` one short write transaction (BEGIN IMMEDIATE, commit or roll back, always closed)."""

    def __enter__(self):
        lock.acquire()
        try:
            self.connection = connect()
            self.connection.execute('BEGIN IMMEDIATE')
        except BaseException:
            lock.release()
            raise
        return self.connection

    def __exit__(self, kind, value, trace):
        try:
            try:
                self.connection.execute('ROLLBACK' if kind else 'COMMIT')
            except sqlite3.Error as error:
                if not kind:
                    raise StoreUnavailable('The SQLite transaction failed.') from error
            finally:
                self.connection.close()
        finally:
            lock.release()
        return False


def health():
    """Cheap structural check: SQLite's own quick_check (page level) plus a foreign-key check. Returns a list of problems."""
    try:
        connection = connect(create=False)
    except StoreUnavailable as error:
        return [str(error)]
    try:
        problems = [row[0] for row in connection.execute('PRAGMA quick_check') if row[0] != 'ok']
        problems += [f'foreign key violation in {row[0]}' for row in connection.execute('PRAGMA foreign_key_check')]
        return problems
    except sqlite3.Error as error:
        return [f'{type(error).__name__}']
    finally:
        connection.close()


def quarantine():
    """Move an unusable database aside (kept for diagnosis) so a fresh one can be rebuilt from the JSON snapshots."""
    with lock:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        moved = None
        for suffix in ('', '-wal', '-shm'):
            source = Path(str(path()) + suffix)
            if source.exists():
                target = source.with_name(f'{source.name}.corrupt-{stamp}')
                os.replace(source, target)
                moved = moved or target
        return moved


def digest(parts):
    value = hashlib.sha256()
    for part in parts:
        value.update(part)
    return value.hexdigest()
