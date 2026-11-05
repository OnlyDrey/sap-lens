"""Rebuildable derived-state cache in SQLite (never authoritative).

Parsing the imported CSV sources into the in-memory model is the dominant start-up and refresh cost. This store keeps the *result* of that
deterministic work, keyed by everything it depends on, so an unchanged source is loaded instead of parsed again. Business records (review
decisions, periods, evidence, settings) never live here and the file is excluded from backups: deleting it only costs one rebuild.

Safety properties: every entry carries an HMAC with a per-installation secret (a tampered or foreign file is ignored, never unpickled),
any read problem degrades to "no cache" and a rebuild, writes are one short transaction, the store is bounded, and the key includes the digest
of the code that produced the value so a code change can never serve stale structures."""
import hashlib
import hmac
import logging
import os
import pickle
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from config import config_dir

logger = logging.getLogger('sap-lens')
SCHEMA_VERSION = 1
KEEP_PER_KIND = 3
MAX_ENTRY_BYTES = 1024 * 1024 * 1024
DIRECTORY = 'cache'
_lock = threading.RLock()
_code_digest = {}


def directory():
    return Path(config_dir()) / DIRECTORY


def file_digest(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def code_digest(*names):
    """Digest of the modules that build a cached value: editing them invalidates their cache without a manual version bump."""
    key = tuple(names)
    if key not in _code_digest:
        digest = hashlib.sha256()
        for name in names:
            digest.update((Path(__file__).parent / name).read_bytes())
        _code_digest[key] = digest.hexdigest()
    return _code_digest[key]


def _secret():
    path = directory() / '.cache-key'
    if path.is_file() and path.stat().st_size == 32:
        return path.read_bytes()
    directory().mkdir(parents=True, exist_ok=True)
    value = secrets.token_bytes(32)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(value)
    return value


def _connect():
    directory().mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(directory() / 'derived.sqlite3', timeout=15, isolation_level=None)
    connection.execute('PRAGMA busy_timeout=15000')
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('PRAGMA synchronous=NORMAL')
    connection.execute('PRAGMA foreign_keys=ON')
    version = connection.execute('PRAGMA user_version').fetchone()[0]
    if version > SCHEMA_VERSION:
        connection.close()
        raise sqlite3.DatabaseError('The derived cache was written by a newer SAP Lens version.')
    if version < SCHEMA_VERSION:
        connection.execute('BEGIN IMMEDIATE')
        connection.execute('CREATE TABLE IF NOT EXISTS derived (kind TEXT NOT NULL, deps TEXT NOT NULL, created TEXT NOT NULL, size INTEGER NOT NULL, '
                           'mac TEXT NOT NULL, payload BLOB NOT NULL, PRIMARY KEY (kind, deps)) WITHOUT ROWID')
        connection.execute('CREATE INDEX IF NOT EXISTS derived_created ON derived (kind, created)')
        connection.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
        connection.execute('COMMIT')
    return connection


def _mac(kind, deps, payload):
    return hmac.new(_secret(), kind.encode() + b'\0' + deps.encode() + b'\0' + payload, hashlib.sha256).hexdigest()


def dependency_key(**parts):
    """Stable text key from named dependencies (source digests, settings digest, code digest, algorithm version)."""
    return hashlib.sha256(repr(sorted(parts.items())).encode()).hexdigest()


def get(kind, deps):
    """The cached object, or None. Corrupt, tampered or unreadable entries are discarded and reported as a miss."""
    with _lock:
        try:
            connection = _connect()
        except (OSError, sqlite3.Error):
            return None
        try:
            row = connection.execute('SELECT payload, mac FROM derived WHERE kind=? AND deps=?', (kind, deps)).fetchone()
            if row is None:
                return None
            if not hmac.compare_digest(row[1], _mac(kind, deps, row[0])):
                connection.execute('DELETE FROM derived WHERE kind=? AND deps=?', (kind, deps))
                logger.warning('Derived cache entry %s failed its integrity check and was discarded.', kind)
                return None
            return pickle.loads(row[0])  # noqa: S301 - authenticated by the installation's HMAC above
        except Exception:  # noqa: BLE001 - any cache problem is only a rebuild
            logger.warning('Derived cache entry %s could not be read; it will be rebuilt.', kind)
            return None
        finally:
            connection.close()


def put(kind, deps, value):
    """Store a value (best effort). Returns True when written. Older entries of the kind beyond KEEP_PER_KIND are removed."""
    with _lock:
        try:
            payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
            if len(payload) > MAX_ENTRY_BYTES:
                return False
            connection = _connect()
        except (OSError, sqlite3.Error, pickle.PicklingError, TypeError, AttributeError):
            return False
        try:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('INSERT OR REPLACE INTO derived (kind, deps, created, size, mac, payload) VALUES (?,?,?,?,?,?)',
                               (kind, deps, datetime.now(timezone.utc).isoformat(), len(payload), _mac(kind, deps, payload), payload))
            connection.execute('DELETE FROM derived WHERE kind=? AND deps NOT IN (SELECT deps FROM derived WHERE kind=? ORDER BY created DESC LIMIT ?)',
                               (kind, kind, KEEP_PER_KIND))
            connection.execute('COMMIT')
            return True
        except sqlite3.Error:
            try:
                connection.execute('ROLLBACK')
            except sqlite3.Error:
                pass
            return False
        finally:
            connection.close()


def cached(kind, deps, build):
    """Return (value, hit): the stored value for these dependencies, or build() stored for next time."""
    value = get(kind, deps)
    if value is not None:
        return value, True
    value = build()
    put(kind, deps, value)
    return value, False


def clear():
    """Remove every derived entry (safe: everything is rebuildable)."""
    with _lock:
        try:
            connection = _connect()
            connection.execute('DELETE FROM derived')
            connection.close()
        except (OSError, sqlite3.Error):
            pass
