"""The SQLite source store: typed revisions, atomic replacement, integrity, schema versions, permissions, signed derived values, concurrency."""
import hashlib
import hmac
import os
import pickle
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import persistent_cache as derived
import source_store
import store_db
from config_models import USER_FIELDS


def user_rows(count, prefix='U'):
    return [{**{name: '' for name in USER_FIELDS}, 'USERNAME': f'{prefix}{n:04d}', 'ROLE_NAME': f'Z:R{n % 7}', 'USER_GROUP': f'G{n % 3}'} for n in range(count)]


class Case(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        patcher = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(Path(self.temp.name) / 'private')}); patcher.start(); self.addCleanup(patcher.stop)


class Revisions(Case):
    def test_round_trip_is_exact_and_typed(self):
        rows = user_rows(50)
        source_store.ingest('users', 'a' * 64, rows, {'note': 'x'})
        self.assertEqual(source_store.read('users', 'a' * 64), (rows, {'note': 'x'}))
        state = source_store.active('users')
        self.assertEqual((state['rows'], state['entities'], state['snapshot']), (50, 50, 'a' * 64))
        connection = store_db.connect()
        self.assertEqual(connection.execute('SELECT COUNT(DISTINCT USERNAME) FROM rows_users').fetchone()[0], 50)  # queryable without materializing
        connection.close()

    def test_replacement_is_atomic_and_keeps_one_active_revision(self):
        source_store.ingest('users', 'a' * 64, user_rows(10), {})
        source_store.ingest('users', 'b' * 64, user_rows(12, 'V'), {})
        statuses = {item['snapshot'][0]: item['status'] for item in source_store.revisions()}
        self.assertEqual(statuses, {'a': 'superseded', 'b': 'active'})
        self.assertEqual(source_store.read('users', 'a' * 64)[0], user_rows(10))      # the previous approved revision stays comparable
        connection = store_db.connect()
        with self.assertRaises(sqlite3.IntegrityError):                                # the database itself forbids a second active revision
            connection.execute("UPDATE source_revisions SET status='active' WHERE snapshot=?", ('a' * 64,))
        connection.close()

    def test_failed_ingest_changes_nothing(self):
        source_store.ingest('users', 'a' * 64, user_rows(5), {})
        bad = user_rows(5, 'W'); del bad[3]['EMAIL']
        with self.assertRaises(KeyError):
            source_store.ingest('users', 'b' * 64, bad, {})
        self.assertEqual([item['snapshot'][0] for item in source_store.revisions()], ['a'])
        self.assertEqual(source_store.active('users')['snapshot'], 'a' * 64)
        self.assertEqual(source_store.read('users', 'a' * 64)[0], user_rows(5))

    def test_same_snapshot_is_idempotent_and_reverting_reuses_the_rows(self):
        first = source_store.ingest('users', 'a' * 64, user_rows(5), {})
        self.assertEqual(source_store.ingest('users', 'a' * 64, user_rows(5), {}), first)
        source_store.ingest('users', 'b' * 64, user_rows(6, 'V'), {})
        self.assertEqual(source_store.ingest('users', 'a' * 64, user_rows(5), {}), first)
        self.assertEqual(source_store.active('users')['snapshot'], 'a' * 64)
        self.assertEqual(len(source_store.revisions()), 2)

    def test_pruning_removes_old_revisions_and_exactly_their_derived_values(self):
        first = source_store.ingest('users', '1' * 64, user_rows(3), {})
        derived.put('users', 'depends-on-first', {'v': 1}, revisions=(first,))
        derived.put('users', 'independent', {'v': 2})
        for index in range(2, 2 + source_store.KEEP_SUPERSEDED + 1):
            source_store.ingest('users', f'{index:x}' * 64, user_rows(3, f'P{index}'), {})
        self.assertIsNone(source_store.read('users', '1' * 64))
        self.assertIsNone(derived.get('users', 'depends-on-first'))
        self.assertEqual(derived.get('users', 'independent'), {'v': 2})
        connection = store_db.connect()
        self.assertEqual(connection.execute('SELECT COUNT(*) FROM rows_users WHERE revision_id=?', (first,)).fetchone()[0], 0)
        connection.close()

    def test_tampered_rows_are_detected_and_the_revision_is_discarded(self):
        source_store.ingest('users', 'a' * 64, user_rows(8), {})
        connection = store_db.connect(); connection.execute("UPDATE rows_users SET ROLE_NAME='Z:EVIL' WHERE ordinal=3"); connection.close()
        with self.assertLogs('sap-lens', 'WARNING'):
            self.assertIsNone(source_store.read('users', 'a' * 64))
        self.assertIsNone(source_store.active('users'))

    def test_a_truncated_revision_is_not_current(self):
        source_store.ingest('users', 'a' * 64, user_rows(8), {})
        connection = store_db.connect(); connection.execute('DELETE FROM rows_users WHERE ordinal=7'); connection.close()
        self.assertFalse(source_store.read_health('users', source_store.active('users')))
        self.assertIsNone(source_store.read('users', 'a' * 64))


class Schema(Case):
    def test_new_database_gets_the_current_schema_and_private_permissions(self):
        store_db.connect().close()
        connection = sqlite3.connect(store_db.path())
        self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], store_db.SCHEMA_VERSION)
        self.assertEqual(connection.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        connection.close()
        self.assertTrue({'meta', 'source_revisions', 'rows_roles', 'rows_users', 'rows_sod', 'derived', 'migrations'} <= names)
        if os.name != 'nt':
            self.assertEqual(store_db.path().stat().st_mode & 0o077, 0)
            self.assertEqual(store_db.directory().stat().st_mode & 0o077, 0)
            store_db.key()
            self.assertEqual((store_db.directory() / '.key').stat().st_mode & 0o077, 0)

    def test_an_older_database_is_upgraded_in_place_without_losing_rows(self):
        store_db.connect().close()
        connection = sqlite3.connect(store_db.path()); connection.execute('PRAGMA user_version=0'); connection.close()   # as if written before the ladder began
        source_store.ingest('users', 'a' * 64, user_rows(4), {})
        self.assertEqual(source_store.read('users', 'a' * 64)[0], user_rows(4))

    def test_a_newer_database_is_refused_and_never_modified(self):
        store_db.connect().close()
        connection = sqlite3.connect(store_db.path()); connection.execute('PRAGMA user_version=99'); connection.close()
        before = hashlib.sha256(store_db.path().read_bytes()).hexdigest()
        with self.assertRaises(store_db.SchemaTooNew):
            store_db.connect()
        self.assertIsNone(source_store.active('users'))
        self.assertFalse(source_store.reconcile(type('S', (), {'data_lifecycle': type('D', (), {'sources': {'users': object()}})()})())['ingested'])
        self.assertEqual(hashlib.sha256(store_db.path().read_bytes()).hexdigest(), before)

    def test_a_failing_step_rolls_back_and_leaves_the_previous_version(self):
        store_db.connect().close()
        connection = sqlite3.connect(store_db.path()); connection.execute('PRAGMA user_version=0'); connection.close()
        def broken(connection):
            connection.execute('CREATE TABLE half_done (x)')
            raise sqlite3.OperationalError('step failed')
        with patch.dict(store_db.LADDER, {1: broken}):
            with self.assertRaises(store_db.StoreUnavailable):
                store_db.connect()
        connection = sqlite3.connect(store_db.path())
        self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 0)
        self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='half_done'").fetchone())
        connection.close()

    def test_garbage_is_unavailable_not_an_exception_for_readers(self):
        store_db.private_directory(); store_db.path().write_bytes(b'garbage' * 100)
        self.assertIsNone(source_store.active('users'))
        self.assertIsNone(source_store.read('users', 'a' * 64))
        self.assertTrue(store_db.health())


class Signing(Case):
    def test_a_validly_signed_but_dangerous_pickle_is_still_refused(self):
        class Evil:
            def __reduce__(self):
                return (os.system, ('echo pwned',))
        payload = pickle.dumps(Evil())
        mac = hmac.new(store_db.key(), b'users\0evil\0' + payload, hashlib.sha256).hexdigest()    # even someone holding the key cannot smuggle a global
        with store_db.transaction() as connection:
            connection.execute('INSERT INTO derived (kind, deps, created, size, revisions, mac, payload) VALUES (?,?,?,?,?,?,?)', ('users', 'evil', 'now', len(payload), '', mac, payload))
        self.assertIsNone(derived.get('users', 'evil'))

    def test_unsigned_or_foreign_signed_payloads_are_never_deserialized(self):
        marker = Path(self.temp.name) / 'ran'
        class Probe:
            def __reduce__(self):
                return (marker.write_text, ('x',))
        payload = pickle.dumps(Probe())
        for mac in ('', 'f' * 64):
            with store_db.transaction() as connection:
                connection.execute('INSERT OR REPLACE INTO derived (kind, deps, created, size, revisions, mac, payload) VALUES (?,?,?,?,?,?,?)', ('users', 'probe', 'now', len(payload), '', mac, payload))
            self.assertIsNone(derived.get('users', 'probe'))
        self.assertFalse(marker.exists())


def writer(root, source, number, count):
    os.environ['SAP_LENS_CONFIG_DIR'] = root
    for step in range(count):
        snapshot = hashlib.sha256(f'{source}{number}{step}'.encode()).hexdigest()
        source_store.ingest(source, snapshot, user_rows(60, f'{number}{step}'), {'n': number}) if source == 'users' else \
            source_store.ingest(source, snapshot, [{**{n: '' for n in store_db.source_columns()[source]}, 'AGR_NAME': f'R{k}', 'RISK': f'R{k}'} for k in range(30)], {})


def reader(root, rounds):
    os.environ['SAP_LENS_CONFIG_DIR'] = root
    bad = 0
    for _ in range(rounds):
        state = source_store.active('users')
        if state:
            found = source_store.read('users', state['snapshot'])
            # The active revision may be superseded between the two calls; a stored revision is never half-written.
            if found is not None and len(found[0]) != 60:
                bad += 1
    print(bad)


def worker(*arguments):
    """Independent OS process (not multiprocessing: other suites patch it), running writer() or reader() from this module."""
    code = ('import sys; sys.path.insert(0, %r); sys.path.insert(0, %r); import test_source_store as t; t.%s(*%r)'
            % (str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent), arguments[0], tuple(arguments[1:])))
    return subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


class Concurrency(Case):
    def test_processes_replacing_sources_while_others_read_never_see_partial_data(self):
        root = str(Path(self.temp.name) / 'private')
        store_db.connect().close()
        writers = [worker('writer', root, 'users', n, 6) for n in range(3)] + [worker('writer', root, 'roles', 9, 6)]
        readers = [worker('reader', root, 60) for _ in range(2)]
        outputs = []
        for item in writers + readers:
            out, err = item.communicate(timeout=240)
            self.assertEqual(item.returncode, 0, err[-800:])
            outputs.append(out.strip())
        self.assertEqual(outputs[-2:], ['0', '0'])                                  # no reader ever saw a partial revision
        revisions = source_store.revisions()
        self.assertEqual(sum(item['status'] == 'active' for item in revisions if item['source'] == 'users'), 1)
        self.assertEqual(sum(item['status'] == 'active' for item in revisions if item['source'] == 'roles'), 1)
        self.assertEqual(store_db.health(), [])
        for item in revisions:
            if item['status'] == 'active':
                self.assertIsNotNone(source_store.read(item['source'], item['snapshot']))

    def test_threads_share_the_store_safely(self):
        import threading
        errors = []
        def work(number):
            try:
                for step in range(8):
                    snapshot = hashlib.sha256(f't{number}{step}'.encode()).hexdigest()
                    source_store.ingest('users', snapshot, user_rows(20, f'{number}{step}'), {})
                    derived.put('users', f'd{number}', {'step': step})
                    derived.get('users', f'd{number}')
            except Exception as error:  # noqa: BLE001
                errors.append(error)
        threads = [threading.Thread(target=work, args=(n,)) for n in range(4)]
        for item in threads: item.start()
        for item in threads: item.join(timeout=120)
        self.assertEqual(errors, [])
        self.assertEqual(store_db.health(), [])


if __name__ == '__main__':
    unittest.main()
