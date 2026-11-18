"""The derived-state cache is rebuildable, authenticated, bounded and never changes what a load returns."""
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cache
import config
import persistent_cache as store
import store_db


class CacheCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(self.root / 'private'), 'DATA_CSV_PATH': ''})
        patcher.start(); self.addCleanup(patcher.stop)
        config.get_settings.cache_clear(); self.addCleanup(config.get_settings.cache_clear)
        self.addCleanup(cache.clear_cache)


class StoreTests(CacheCase):
    def test_hit_miss_and_dependency_change(self):
        calls = []
        build = lambda: calls.append(1) or {'rows': [1, 2, 3]}
        deps = store.dependency_key(file='a', code='c')
        self.assertEqual(store.cached('users', deps, build), ({'rows': [1, 2, 3]}, False))
        self.assertEqual(store.cached('users', deps, build), ({'rows': [1, 2, 3]}, True))
        self.assertEqual(len(calls), 1)
        store.cached('users', store.dependency_key(file='b', code='c'), build)   # a changed dependency is a different entry
        self.assertEqual(len(calls), 2)
        self.assertEqual(store.cached('roles', deps, build)[1], False)           # kinds never share entries

    def test_tampered_entries_are_discarded_not_unpickled(self):
        deps = store.dependency_key(x=1)
        store.put('users', deps, {'ok': True})
        connection = sqlite3.connect(store.directory() / 'sap-lens.sqlite3')
        connection.execute('UPDATE derived SET payload=?', (b'not a trusted pickle',)); connection.commit(); connection.close()
        with self.assertLogs('sap-lens', 'WARNING'):
            self.assertIsNone(store.get('users', deps))
        connection = sqlite3.connect(store.directory() / 'sap-lens.sqlite3')
        self.assertEqual(connection.execute('SELECT COUNT(*) FROM derived').fetchone()[0], 0)   # removed, so the next load rebuilds
        connection.close()

    def test_a_foreign_secret_invalidates_every_entry(self):
        deps = store.dependency_key(x=1)
        store.put('users', deps, {'ok': True})
        (store.directory() / '.key').write_bytes(b'k' * 32)
        self.assertIsNone(store.get('users', deps))

    def test_corrupt_database_file_is_only_a_miss(self):
        store.put('users', 'd', {'ok': True})
        (store.directory() / 'sap-lens.sqlite3').write_bytes(b'garbage' * 50)
        for suffix in ('-wal', '-shm'):
            (store.directory() / ('sap-lens.sqlite3' + suffix)).unlink(missing_ok=True)
        self.assertIsNone(store.get('users', 'd'))
        self.assertFalse(store.put('users', 'd', {'ok': True}))   # failing to cache never fails the load
        self.assertEqual(store.cached('users', 'd', lambda: 7)[0], 7)

    def test_newer_schema_is_refused_and_older_data_is_untouched(self):
        store.put('users', 'd', 1)
        connection = sqlite3.connect(store.directory() / 'sap-lens.sqlite3'); connection.execute('PRAGMA user_version=99'); connection.close()
        self.assertIsNone(store.get('users', 'd'))

    def test_store_is_bounded_per_kind(self):
        for number in range(store.KEEP_PER_KIND + 3):
            store.put('users', f'd{number}', number)
        connection = sqlite3.connect(store.directory() / 'sap-lens.sqlite3')
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM derived WHERE kind='users'").fetchone()[0], store.KEEP_PER_KIND)
        connection.close()
        self.assertEqual(store.get('users', f'd{store.KEEP_PER_KIND + 2}'), store.KEEP_PER_KIND + 2)  # the newest survive

    @unittest.skipIf(os.name == 'nt', 'POSIX permission bits')
    def test_secret_is_private(self):
        store.put('users', 'd', 1)
        self.assertEqual((store.directory() / '.key').stat().st_mode & 0o077, 0)

    def test_pragmas_and_schema(self):
        store.put('users', 'd', 1)
        connection = sqlite3.connect(store.directory() / 'sap-lens.sqlite3')
        self.assertEqual(connection.execute('PRAGMA journal_mode').fetchone()[0], 'wal')  # persistent in the file header
        self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], store_db.SCHEMA_VERSION)
        self.assertTrue(connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok')
        connection.close()

    def test_concurrent_writers_and_readers_do_not_corrupt_or_raise(self):
        errors = []
        def work(number):
            try:
                for step in range(15):
                    store.put('users', f'd{number % 3}', {'n': number, 'step': step})
                    store.get('users', f'd{number % 3}')
            except Exception as error:  # noqa: BLE001
                errors.append(error)
        threads = [threading.Thread(target=work, args=(n,)) for n in range(6)]
        [t.start() for t in threads]; [t.join() for t in threads]
        self.assertEqual(errors, [])

    def test_code_digest_follows_the_producing_modules(self):
        store._code_digest.clear()
        first = store.code_digest('cache.py')
        self.assertEqual(first, store.code_digest('cache.py'))
        self.assertNotEqual(first, store.code_digest('csv_import.py'))

    def test_frozen_digest_uses_loader_code_and_ignores_extraction_path(self):
        store._code_digest.clear()
        self.addCleanup(store._code_digest.clear)
        def fingerprint(filename, body):
            code = compile(body, filename, 'exec')
            spec = SimpleNamespace(name='synthetic', loader=SimpleNamespace(get_code=lambda name: code))
            store._code_digest.clear()
            with patch.object(sys, 'frozen', True, create=True), patch.object(store.importlib.util, 'find_spec', return_value=spec), patch.object(Path, 'read_bytes', side_effect=AssertionError('no loose sources')):
                return store.code_digest('synthetic.py')
        first = fingerprint('C:/extract-one/synthetic.py', 'def nested():\n return 1\n')
        self.assertEqual(first, fingerprint('D:/extract-two/synthetic.py', 'def nested():\n return 1\n'))
        self.assertNotEqual(first, fingerprint('D:/extract-two/synthetic.py', 'def nested():\n return 2\n'))

    def test_frozen_missing_code_never_uses_a_constant_fingerprint(self):
        store._code_digest.clear()
        self.addCleanup(store._code_digest.clear)
        with patch.object(sys, 'frozen', True, create=True), patch.object(store.importlib.util, 'find_spec', return_value=None):
            with self.assertRaisesRegex(OSError, 'Packaged module code is unavailable'):
                store.code_digest('missing.py')


class LoadIntegration(CacheCase):
    ROLES = 'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT\nFI,Z:FI,Finance,Z:FI:READ,Read,FB03,Display\n'
    USERS = 'USERNAME,ROLE_NAME,EMAIL,USER_GROUP,USER_VALID_FROM,USER_VALID_TO,ROLE_VALID_FROM,ROLE_VALID_TO\nU1,Z:FI,u1@example.test,G,20200101,99991231,20200101,99991231\n'

    def configure(self, users=None):
        (self.root / 'roles.csv').write_text(self.ROLES); (self.root / 'users.csv').write_text(users or self.USERS)
        settings = config.get_settings().model_copy(deep=True)
        settings.data_csv_path = str(self.root / 'roles.csv'); settings.user_csv_path = str(self.root / 'users.csv')
        config.save_configuration(settings, settings.revision)

    def test_unchanged_sources_are_loaded_without_parsing_and_results_are_identical(self):
        self.configure()
        cache.load_cache(); first = cache.get_snapshot()
        with patch.object(cache, 'build_users') as parse, patch.object(cache, '_build_catalog') as catalogue:
            cache.load_cache(); second = cache.get_snapshot()
        parse.assert_not_called(); catalogue.assert_not_called()
        self.assertEqual(sorted(second.roles), sorted(first.roles))
        self.assertEqual(second.users.users, first.users.users)
        self.assertIsNot(second.users, first.users)   # a fresh object: callers can never share mutable cached state

    def test_a_changed_source_is_reparsed_and_only_that_source(self):
        self.configure(); cache.load_cache()
        changed = self.USERS.replace('U1', 'U2')
        (self.root / 'users.csv').write_text(changed)
        with patch.object(cache, '_build_catalog', wraps=cache._build_catalog) as catalogue:
            cache.load_cache()
        catalogue.assert_not_called()                                   # the unchanged catalogue still comes from the cache
        self.assertIn('U2', {u['username'] for u in cache.get_snapshot().users.users.values()})
        self.assertNotIn('U1', {u['username'] for u in cache.get_snapshot().users.users.values()})

    def test_a_changed_catalogue_remaps_users(self):
        self.configure(); cache.load_cache()
        (self.root / 'roles.csv').write_text(self.ROLES.replace('FB03', 'FB04'))
        with patch.object(cache, 'build_users', wraps=cache.build_users) as parse:
            cache.load_cache()
        parse.assert_called_once()   # users were mapped against the old catalogue, so they are rebuilt

    def test_invalid_csv_still_fails_and_leaves_the_previous_load_available(self):
        self.configure(); cache.load_cache()
        (self.root / 'users.csv').write_text('NOT,THE,EXPECTED,HEADER\n1,2,3,4\n')
        with self.assertRaises(Exception):
            cache.load_cache()
        self.assertTrue(cache.get_snapshot().users.users)

    def test_corrupt_cache_is_rebuilt_transparently(self):
        self.configure(); cache.load_cache()
        (store.directory() / 'sap-lens.sqlite3').write_bytes(b'broken')
        cache.load_cache()
        self.assertTrue(cache.get_snapshot().users.users)

    def test_the_cache_directory_is_not_part_of_application_backups(self):
        import application_backups as backups
        self.configure(); cache.load_cache()
        self.assertIn('store', backups.protected(store.directory().parent))


if __name__ == '__main__':
    unittest.main()


class StoreConnectionLifecycleTests(CacheCase):
    """A connection the caller never receives is closed where it was opened; on Windows an open handle keeps the store file locked."""
    def recorded(self):
        opened, connect = [], sqlite3.connect
        def recording(*args, **kwargs):
            connection = connect(*args, **kwargs); opened.append(connection); return connection
        return opened, patch.object(store_db.sqlite3, 'connect', recording)

    def assert_closed(self, opened):
        self.assertTrue(opened)
        for connection in opened:
            with self.assertRaises(sqlite3.ProgrammingError): connection.execute('SELECT 1')

    def test_a_failed_schema_step_or_newer_schema_closes_the_connection(self):
        store_db.connect().close()
        opened, recording = self.recorded()
        def broken(connection): raise KeyError('not an sqlite error')          # anything a migration step can raise
        with recording, patch.dict(store_db.LADDER, {store_db.SCHEMA_VERSION + 1: broken}), patch.object(store_db, 'SCHEMA_VERSION', store_db.SCHEMA_VERSION + 1):
            with self.assertRaises(KeyError): store_db.connect()
        self.assert_closed(opened)
        opened, recording = self.recorded()
        with recording, patch.object(store_db, 'SCHEMA_VERSION', store_db.SCHEMA_VERSION - 1):
            with self.assertRaises(store_db.StoreUnavailable): store_db.connect()   # written by a "newer" version
        self.assert_closed(opened)

    def test_a_transaction_that_cannot_begin_closes_its_connection_and_releases_the_lock(self):
        store_db.connect().close()
        opened, recording = self.recorded()
        class Refusing:
            def __init__(self, real): self.real = real
            def execute(self, sql, *args):
                if sql == 'BEGIN IMMEDIATE': raise sqlite3.OperationalError('database is locked')
                return self.real.execute(sql, *args)
            def close(self): self.real.close()
        original = store_db.connect
        with recording, patch.object(store_db, 'connect', lambda **kwargs: Refusing(original(**kwargs))):
            with self.assertRaises(sqlite3.OperationalError):
                with store_db.transaction(): self.fail('the block must not run')
        self.assert_closed(opened)
        with store_db.transaction() as connection:                              # the store lock was released
            self.assertEqual(connection.execute('SELECT 1').fetchone()[0], 1)
