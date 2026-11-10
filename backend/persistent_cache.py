"""Rebuildable derived-state cache stored in the application SQLite store (never authoritative).

Deriving the in-memory model (role catalogue, user/assignment indexes) from the source records is the dominant start-up and refresh cost. This
module keeps the *result* of that deterministic work in the `derived` table of the shared store, keyed by everything it depends on, so an
unchanged source revision is loaded instead of derived again. Business records (review decisions, periods, evidence, settings) never live
here. Each entry names the source revisions it was computed from, so replacing or pruning a revision invalidates exactly its dependants.

Safety properties: every entry carries an HMAC with a per-installation secret (store/.key, 0600); the MAC is verified *before* any
deserialization, and deserialization additionally refuses every global outside an allowlist of data containers and this application's own
model classes. Any read problem degrades to "no cache" and a rebuild. Writes are one short transaction, the store is bounded, and the key
includes the digest of the code that produced the value, so a code change can never serve stale structures."""
import hashlib
import hmac
import io
import logging
import pickle
import sqlite3
import threading
from pathlib import Path

import store_db
from store_db import StoreUnavailable

logger = logging.getLogger('sap-lens')
KEEP_PER_KIND = 3
MAX_ENTRY_BYTES = 1024 * 1024 * 1024
_lock = threading.RLock()
_code_digest = {}
ALLOWED_PREFIXES = ('pydantic', 'pydantic_core', 'models', 'user_access', 'cache', 'role_matching', 'module_registry', 'config_models', 'csv_import', 'collections',
                    'datetime', 'decimal', 'copyreg', 'enum', 'typing', 'dataclasses', 'uuid', 'fractions', 'zoneinfo', 'sod_import', 'employee_directory')
ALLOWED_BUILTINS = {'set', 'frozenset', 'dict', 'list', 'tuple', 'bytearray', 'bytes', 'complex', 'range', 'slice', 'object', 'int', 'float', 'str', 'bool'}


class _Restricted(pickle.Unpickler):
    def find_class(self, module, name):
        if module == 'builtins' and name in ALLOWED_BUILTINS or module.split('.')[0] in ALLOWED_PREFIXES and name not in {'eval', 'exec', 'system', 'open', '__import__'}:
            return super().find_class(module, name)
        raise pickle.UnpicklingError('Refusing to load an unexpected object type.')


def _loads(payload):
    return _Restricted(io.BytesIO(payload)).load()


def directory():
    return store_db.directory()


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


def _mac(kind, deps, payload):
    return hmac.new(store_db.key(), kind.encode() + b'\0' + deps.encode() + b'\0' + payload, hashlib.sha256).hexdigest()


def dependency_key(**parts):
    """Stable text key from named dependencies (source digests, settings digest, code digest, algorithm version)."""
    return hashlib.sha256(repr(sorted(parts.items())).encode()).hexdigest()


def get(kind, deps):
    """The cached object, or None. Corrupt, tampered or unreadable entries are discarded and reported as a miss."""
    with _lock:
        try:
            connection = store_db.connect()
        except (OSError, sqlite3.Error, StoreUnavailable):
            return None
        try:
            row = connection.execute('SELECT payload, mac FROM derived WHERE kind=? AND deps=?', (kind, deps)).fetchone()
            if row is None:
                return None
            if not hmac.compare_digest(row[1], _mac(kind, deps, row[0])):
                connection.execute('DELETE FROM derived WHERE kind=? AND deps=?', (kind, deps))
                logger.warning('Derived cache entry %s failed its integrity check and was discarded.', kind)
                return None
            return _loads(row[0])  # authenticated by the installation's HMAC above and restricted to known classes
        except Exception:  # noqa: BLE001 - any cache problem is only a rebuild
            logger.warning('Derived cache entry %s could not be read; it will be rebuilt.', kind)
            return None
        finally:
            connection.close()


def put(kind, deps, value, revisions=()):
    """Store a value (best effort). Returns True when written. Older entries of the kind beyond KEEP_PER_KIND are removed."""
    with _lock:
        try:
            payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
            if len(payload) > MAX_ENTRY_BYTES:
                return False
            with store_db.transaction() as connection:
                connection.execute('INSERT OR REPLACE INTO derived (kind, deps, created, size, revisions, mac, payload) VALUES (?,?,?,?,?,?,?)',
                                   (kind, deps, store_db.now(), len(payload), ','.join(str(int(item)) for item in revisions), _mac(kind, deps, payload), payload))
                connection.execute('DELETE FROM derived WHERE kind=? AND deps NOT IN (SELECT deps FROM derived WHERE kind=? ORDER BY created DESC LIMIT ?)',
                                   (kind, kind, KEEP_PER_KIND))
            return True
        except (OSError, sqlite3.Error, pickle.PicklingError, TypeError, AttributeError, StoreUnavailable):
            return False


def cached(kind, deps, build, revisions=()):
    """Return (value, hit): the stored value for these dependencies, or build() stored for next time."""
    value = get(kind, deps)
    if value is not None:
        return value, True
    value = build()
    put(kind, deps, value, revisions)
    return value, False


def clear():
    """Remove every derived entry (safe: everything is rebuildable)."""
    with _lock:
        try:
            with store_db.transaction() as connection:
                connection.execute('DELETE FROM derived')
        except (OSError, sqlite3.Error, StoreUnavailable):
            pass
