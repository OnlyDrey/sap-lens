"""Structured, revision-based copy of the validated source snapshots (roles, users, SoD matrix) in SQLite.

Authority: the content-addressed JSON snapshots under `csv-data/snapshots` stay the immutable evidence and the thing the configuration points at.
This store holds the same records as typed columns, *keyed by the snapshot digest*, so every revision is verifiable against its snapshot and
the whole store can be rebuilt from the snapshots. It never decides which data is active: `reconcile` makes it follow the committed
configuration. A revision therefore has no independent life and cannot drift into a second source of truth.

Revisions: each (source, scope) has a monotonically increasing `sequence`. Exactly one revision is `active` (enforced by a partial unique index);
replacing it is one transaction that flips the previous revision to `superseded` and the new one to `active`, so readers see the old or the new
revision, never a mixture. Superseded revisions are kept (bounded by KEEP_SUPERSEDED) for rollback and for the comparison with the previous
approved revision; derived values that depend on a removed revision are invalidated with it."""
import hashlib
import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

import store_db
from store_db import StoreUnavailable, transaction

logger = logging.getLogger('sap-lens')
KEEP_SUPERSEDED = 2
SOURCES = ('roles', 'users', 'sod')
ORPHAN_AGE_SECONDS = 3600
_operations = {}   # live operation id -> set of (source, scope, snapshot) it staged or shares
_operations_lock = threading.Lock()


def begin():
    """A new staging operation. Everything it stages is owned by it; `end` removes only what it still owns."""
    owner = uuid.uuid4().hex
    with _operations_lock:
        _operations[owner] = set()
    return owner


def end(owner):
    """Finish an operation (success, failure or cancellation): its staged-but-never-activated revisions are removed, other operations' are not touched."""
    if not owner:
        return
    try:
        discard_staged(owner)
    finally:
        with _operations_lock:
            _operations.pop(owner, None)


class operation:
    def __enter__(self):
        self.owner = begin()
        return self.owner

    def __exit__(self, kind, value, trace):
        end(self.owner)
        return False


def _claim(owner, key):
    with _operations_lock:
        if owner in _operations:
            _operations[owner].add(key)


def _other_claimant(owner, key):
    with _operations_lock:
        return next((other for other, keys in _operations.items() if other != owner and key in keys), None)


def _digest(rows, columns):
    value = hashlib.sha256()
    for row in rows:
        value.update('\x1f'.join(row[name] for name in columns).encode('utf-8'))
        value.update(b'\x1e')
    return value.hexdigest()


def _entities(source, rows):
    column = store_db.KEY_COLUMN[source]
    return len({row[column].strip().casefold() for row in rows if row[column].strip()})


def stage(source, snapshot, rows, report, fingerprint='', scope='', owner=''):
    """Write the rows of a validated snapshot as a `staged` revision (invisible to readers of the active revision). Idempotent per snapshot.

    Staging is the slow part of an import and happens before the configuration pointer is committed; `activate` is the instant flip afterwards."""
    columns = store_db.source_columns()[source]
    _claim(owner, (source, scope, snapshot))
    with transaction() as connection:
        found = connection.execute('SELECT id, status FROM source_revisions WHERE source=? AND scope=? AND snapshot=?', (source, scope, snapshot)).fetchone()
        if found and connection.execute(f'SELECT 1 FROM rows_{source} WHERE revision_id=? LIMIT 1', (found[0],)).fetchone() or found and not rows:
            if fingerprint:
                connection.execute('UPDATE source_revisions SET fingerprint=? WHERE id=?', (fingerprint, found[0]))
            return found[0]
        if found:
            connection.execute('DELETE FROM source_revisions WHERE id=?', (found[0],))   # a revision without rows is not a revision
        sequence = connection.execute('SELECT COALESCE(MAX(sequence),0) FROM source_revisions WHERE source=? AND scope=?', (source, scope)).fetchone()[0] + 1
        current = connection.execute('SELECT id FROM source_revisions WHERE source=? AND scope=? AND status=\'active\'', (source, scope)).fetchone()
        cursor = connection.execute('INSERT INTO source_revisions (source, scope, sequence, snapshot, row_count, entity_count, rows_digest, report, status, created, supersedes, fingerprint) '
                                    'VALUES (?,?,?,?,?,?,?,?,\'staged\',?,?,?)',
                                    (source, scope, sequence, snapshot, len(rows), _entities(source, rows), _digest(rows, columns), json.dumps(report, separators=(',', ':')),
                                     store_db.now(), current[0] if current else None, fingerprint))
        connection.execute('UPDATE source_revisions SET owner=? WHERE id=?', (owner, cursor.lastrowid))
        revision = cursor.lastrowid
        marks = ','.join('?' * (len(columns) + 2))
        names = ','.join(['revision_id', 'ordinal', *[store_db._identifier(name) for name in columns]])
        connection.executemany(f'INSERT INTO rows_{source} ({names}) VALUES ({marks})',
                               ((revision, ordinal, *[row[name] for name in columns]) for ordinal, row in enumerate(rows)))
        return revision


def activate(source, snapshot, scope=''):
    """Atomically make the staged (or earlier) revision of this snapshot the active one: the previous active revision becomes `superseded` in the same transaction."""
    with transaction() as connection:
        target = connection.execute('SELECT id, status FROM source_revisions WHERE source=? AND scope=? AND snapshot=?', (source, scope, snapshot)).fetchone()
        if not target:
            raise StoreUnavailable('No staged revision for this snapshot.')
        if target[1] == 'active':
            return target[0]
        connection.execute('UPDATE source_revisions SET status=\'superseded\' WHERE source=? AND scope=? AND status=\'active\'', (source, scope))
        sequence = connection.execute('SELECT COALESCE(MAX(sequence),0) FROM source_revisions WHERE source=? AND scope=?', (source, scope)).fetchone()[0] + 1
        connection.execute('UPDATE source_revisions SET status=\'active\', activated=?, sequence=?, owner=\'\' WHERE id=?', (store_db.now(), sequence, target[0]))
        _prune(connection, source, scope)
        return target[0]


def ingest(source, snapshot, rows, report, scope='', fingerprint=''):
    """Stage and activate in two short transactions (used where no commit protocol surrounds the call). Idempotent for an already active snapshot."""
    with operation() as owner:
        stage(source, snapshot, rows, report, fingerprint, scope, owner)
        return activate(source, snapshot, scope)


def discard_staged(owner):
    """Remove the staged revisions that belong to this operation. A revision another live operation also staged (same snapshot) is handed over, not deleted."""
    if not owner:
        return
    try:
        with transaction() as connection:
            for revision, source, scope, snapshot in connection.execute('SELECT id, source, scope, snapshot FROM source_revisions WHERE status=\'staged\' AND owner=?', (owner,)).fetchall():
                other = _other_claimant(owner, (source, scope, snapshot))
                if other:
                    connection.execute('UPDATE source_revisions SET owner=? WHERE id=?', (other, revision))
                else:
                    invalidate(connection, [revision])
                    connection.execute('DELETE FROM source_revisions WHERE id=?', (revision,))
    except (StoreUnavailable, sqlite3.Error):
        pass


def recover_orphans(older_than=ORPHAN_AGE_SECONDS):
    """Remove staged revisions whose operation no longer exists: at start-up (`older_than=0`, nothing is live yet) or, while running, those older than
    an hour that no live operation of this process owns. Active and superseded revisions are never touched. Returns the number removed."""
    removed = 0
    try:
        with transaction() as connection:
            with _operations_lock:
                live = set(_operations)
            now = datetime.now(timezone.utc)
            for revision, owner, created in connection.execute('SELECT id, owner, created FROM source_revisions WHERE status=\'staged\'').fetchall():
                if owner in live:
                    continue
                if older_than and (now - datetime.fromisoformat(created)).total_seconds() < older_than:
                    continue
                invalidate(connection, [revision])
                connection.execute('DELETE FROM source_revisions WHERE id=?', (revision,))
                removed += 1
    except (StoreUnavailable, sqlite3.Error, ValueError):
        pass
    return removed


def fingerprint(source, snapshot, scope=''):
    try:
        connection = store_db.connect(create=False)
    except StoreUnavailable:
        return ''
    try:
        row = connection.execute('SELECT fingerprint FROM source_revisions WHERE source=? AND scope=? AND snapshot=? AND status=\'active\'', (source, scope, snapshot)).fetchone()
        return row[0] if row else ''
    except sqlite3.Error:
        return ''
    finally:
        connection.close()


def set_fingerprint(source, snapshot, value, scope=''):
    try:
        with transaction() as connection:
            connection.execute('UPDATE source_revisions SET fingerprint=? WHERE source=? AND scope=? AND snapshot=?', (value, source, scope, snapshot))
    except (StoreUnavailable, sqlite3.Error):
        pass


def _prune(connection, source, scope):
    old = [row[0] for row in connection.execute(
        'SELECT id FROM source_revisions WHERE source=? AND scope=? AND status=\'superseded\' ORDER BY sequence DESC LIMIT -1 OFFSET ?', (source, scope, KEEP_SUPERSEDED))]
    for revision in old:
        invalidate(connection, [revision])
        connection.execute('DELETE FROM source_revisions WHERE id=?', (revision,))  # rows go with it (ON DELETE CASCADE)


def invalidate(connection, revisions):
    """Drop every derived value computed from any of these revisions (dependency-aware invalidation)."""
    for revision in revisions:
        connection.execute('DELETE FROM derived WHERE (\',\' || revisions || \',\') LIKE ?', (f'%,{int(revision)},%',))


def active(source, scope=''):
    try:
        connection = store_db.connect(create=False)
    except StoreUnavailable:
        return None
    try:
        row = connection.execute('SELECT id, snapshot, row_count, entity_count, created, activated, sequence FROM source_revisions '
                                 'WHERE source=? AND scope=? AND status=\'active\'', (source, scope)).fetchone()
        return dict(zip(('id', 'snapshot', 'rows', 'entities', 'created', 'activated', 'sequence'), row)) if row else None
    except sqlite3.Error:
        return None
    finally:
        connection.close()


def revision_id(source, snapshot, scope=''):
    try:
        connection = store_db.connect(create=False)
    except StoreUnavailable:
        return None
    try:
        row = connection.execute('SELECT id FROM source_revisions WHERE source=? AND scope=? AND snapshot=?', (source, scope, snapshot)).fetchone()
        return row[0] if row else None
    except sqlite3.Error:
        return None
    finally:
        connection.close()


def read(source, snapshot, scope=''):
    """(rows, report) of the revision stored for this snapshot, verified against its recorded digest and row count; None when absent or damaged.

    A damaged revision is removed so the next reconcile rebuilds it from the immutable snapshot."""
    columns = store_db.source_columns()[source]
    try:
        connection = store_db.connect(create=False)
    except StoreUnavailable:
        return None
    try:
        head = connection.execute('SELECT id, row_count, rows_digest, report FROM source_revisions WHERE source=? AND scope=? AND snapshot=?', (source, scope, snapshot)).fetchone()
        if not head:
            return None
        names = ','.join(store_db._identifier(name) for name in columns)
        cursor = connection.execute(f'SELECT {names} FROM rows_{source} WHERE revision_id=? ORDER BY ordinal', (head[0],))
        rows, digest = [], hashlib.sha256()
        for values in cursor:
            digest.update('\x1f'.join(values).encode('utf-8'))
            digest.update(b'\x1e')
            rows.append(dict(zip(columns, values)))
        if len(rows) != head[1] or digest.hexdigest() != head[2]:
            logger.warning('A stored %s revision failed its integrity check and will be rebuilt from its snapshot.', source)
            discard(head[0])
            return None
        return rows, json.loads(head[3])
    except (sqlite3.Error, ValueError, TypeError):
        return None
    finally:
        connection.close()


def discard(revision):
    try:
        with transaction() as connection:
            invalidate(connection, [revision])
            was_active = connection.execute('SELECT source, scope FROM source_revisions WHERE id=? AND status=\'active\'', (revision,)).fetchone()
            connection.execute('DELETE FROM source_revisions WHERE id=?', (revision,))
            return was_active is not None
    except (StoreUnavailable, sqlite3.Error):
        return False


def reconcile(settings, fresh=None):
    """Make the store follow the committed configuration: every source with a snapshot reference has that snapshot as its active revision.

    `fresh` maps source -> (snapshot, rows, report) for data the caller just validated, which avoids reading the snapshot back. Returns a summary;
    never raises, because the JSON snapshots remain the authority and the store is only an accelerator and a queryable copy."""
    summary = dict(ingested=[], current=[], failed=[])
    try:
        from csv_lifecycle import read_source
        for source in SOURCES:
            reference = settings.data_lifecycle.sources.get(source)
            if not reference:
                continue
            try:
                state = active(source)
                if state and state['snapshot'] == reference.snapshot and read_health(source, state):
                    summary['current'].append(source)
                    continue
                supplied = (fresh or {}).get(source)
                if supplied and supplied[0] == reference.snapshot:
                    rows, report = supplied[1], supplied[2]
                else:
                    rows, report = read_source(source, reference)
                ingest(source, reference.snapshot, rows, report, fingerprint=supplied[3] if supplied and len(supplied) > 3 else '')
                summary['ingested'].append(source)
            except Exception as error:  # noqa: BLE001 - one damaged source must not stop the others or startup
                logger.warning('Could not mirror the %s snapshot into the SQLite store (%s).', source, type(error).__name__)
                summary['failed'].append(source)
    except StoreUnavailable:
        summary['failed'] = list(SOURCES)
    return summary


def read_health(source, state):
    """The active revision still has all its rows (cheap count; full digest verification happens when the rows are read)."""
    try:
        connection = store_db.connect(create=False)
    except StoreUnavailable:
        return False
    try:
        return connection.execute(f'SELECT COUNT(*) FROM rows_{source} WHERE revision_id=?', (state['id'],)).fetchone()[0] == state['rows']
    except sqlite3.Error:
        return False
    finally:
        connection.close()


def revisions():
    try:
        connection = store_db.connect(create=False)
    except StoreUnavailable:
        return []
    try:
        return [dict(zip(('id', 'source', 'scope', 'sequence', 'snapshot', 'rows', 'entities', 'status', 'created', 'activated'), row)) for row in connection.execute(
            'SELECT id, source, scope, sequence, snapshot, row_count, entity_count, status, created, activated FROM source_revisions ORDER BY source, scope, sequence')]
    except sqlite3.Error:
        return []
    finally:
        connection.close()


def remove_snapshot(snapshot):
    """Delete the non-active revisions (rows, derived values) built from a snapshot that is being retired. The active revision is never removed. Returns the count."""
    try:
        with transaction() as connection:
            rows = connection.execute('SELECT id FROM source_revisions WHERE snapshot=? AND status<>\'active\'', (snapshot,)).fetchall()
            for (revision,) in rows:
                invalidate(connection, [revision])
                connection.execute('DELETE FROM source_revisions WHERE id=?', (revision,))
            return len(rows)
    except (StoreUnavailable, sqlite3.Error):
        return 0


def drop_missing(exists):
    """Remove non-active revisions whose snapshot file no longer exists (completes an interrupted cleanup). `exists(snapshot)` answers for the file."""
    try:
        with transaction() as connection:
            gone = [(revision, snapshot) for revision, snapshot in connection.execute('SELECT id, snapshot FROM source_revisions WHERE status=\'superseded\'').fetchall() if not exists(snapshot)]
            for revision, _ in gone:
                invalidate(connection, [revision])
                connection.execute('DELETE FROM source_revisions WHERE id=?', (revision,))
            return len(gone)
    except (StoreUnavailable, sqlite3.Error):
        return 0
