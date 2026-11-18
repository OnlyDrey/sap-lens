"""Source-specific refresh: unchanged sources are never parsed, compared or rebuilt; changed ones rebuild only what depends on them; activation is atomic."""
import csv
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cache
import config
import csv_lifecycle
import source_store
import store_db
import user_access

HEADER = 'USERNAME,ROLE_NAME,EMAIL,USER_GROUP,USER_VALID_FROM,USER_VALID_TO,ROLE_VALID_FROM,ROLE_VALID_TO'.split(',')
ROLES = 'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT\nFI,Z:FI,Finance,Z:FI:READ,Read,FB03,Display\n'


class Refresh(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(self.root / 'private'), 'DATA_CSV_PATH': ''}); patcher.start(); self.addCleanup(patcher.stop)
        config.get_settings.cache_clear(); cache.clear_cache(); self.addCleanup(cache.clear_cache); self.addCleanup(config.get_settings.cache_clear)
        (self.root / 'roles.csv').write_text(ROLES)
        self.write(40)
        settings = config.get_settings().model_copy(deep=True)
        settings.data_csv_path, settings.user_csv_path = str(self.root / 'roles.csv'), str(self.root / 'users.csv')
        config.save_configuration(settings, settings.revision)
        csv_lifecycle.load(config.get_settings(), operation='refresh', strict=True)       # first import
        cache.clear_cache()
        csv_lifecycle.load(config.get_settings(), operation='startup', strict=True)       # the running application

    def write(self, users, domain='example.test'):
        with (self.root / 'users.csv').open('w', newline='') as stream:
            writer = csv.writer(stream); writer.writerow(HEADER)
            writer.writerows([f'U{u:03d}', f'Z:FI:{r}', f'u{u}@{domain}', 'FIN', '20200101', '99991231', '20200101', '99991231'] for u in range(users) for r in range(2))

    def refresh(self, operation='refresh'):
        return csv_lifecycle.load(config.get_settings(), operation=operation, strict=True)

    def statuses(self, report):
        return {row['source']: (row['status'], row.get('fast_path', False)) for row in report['sources'] if row['source'] in {'roles', 'users'}}

    def counted(self):
        return (patch.object(cache, '_build_catalog', wraps=cache._build_catalog), patch.object(user_access.UserCsvImport, 'records', autospec=True, side_effect=user_access.UserCsvImport.records),
                patch.object(csv_lifecycle, 'diff_records', wraps=csv_lifecycle.diff_records), patch.object(cache, 'build_users', wraps=cache.build_users))

    def test_unchanged_sources_skip_parsing_diffing_and_rebuilding(self):
        before = cache.get_snapshot()
        with self.counted()[0] as catalogue, self.counted()[1] as parse, self.counted()[3] as users:
            with patch.object(csv_lifecycle, 'diff_records', wraps=csv_lifecycle.diff_records) as diff:
                report = self.refresh()
        self.assertEqual(self.statuses(report), {'roles': ('unchanged', True), 'users': ('unchanged', True)})
        self.assertEqual((catalogue.call_count, parse.call_count, users.call_count), (0, 0, 0))
        self.assertEqual([call.args[1] for call in diff.call_args_list if call.args[1]], [])  # only the empty zero-delta helper, never a real comparison
        self.assertIs(cache.get_snapshot().users, before.users)                              # same objects: nothing was rebuilt or replaced
        self.assertEqual(report['unchanged'], 2)

    def test_touching_a_file_without_changing_content_stays_on_the_fast_path_but_content_changes_never_do(self):
        os.utime(self.root / 'users.csv', (1, 1))
        self.assertEqual(self.statuses(self.refresh())['users'], ('unchanged', True))
        self.write(40, domain='example.org')                                                 # identical size and row count, different content
        report = self.refresh()
        self.assertEqual(self.statuses(report)['users'], ('updated', False))
        self.assertIn('u0@example.org', {e for user in cache.get_snapshot().users.users.values() for e in user['emails']})

    def test_only_the_changed_source_is_parsed_and_users_are_mapped_once(self):
        self.write(40, domain='example.org')
        with patch.object(cache, '_build_catalog', wraps=cache._build_catalog) as catalogue, patch.object(cache, 'build_users', wraps=cache.build_users) as users:
            report = self.refresh()
        self.assertEqual(self.statuses(report), {'roles': ('unchanged', True), 'users': ('updated', False)})
        self.assertEqual(catalogue.call_count, 0)
        self.assertEqual(users.call_count, 1)                                                # parsed once, not parsed and then rebuilt again

    def test_a_changed_catalogue_remaps_the_unchanged_users_exactly_once(self):
        (self.root / 'roles.csv').write_text(ROLES.replace('FB03', 'FB04'))
        with patch.object(user_access.UserCsvImport, 'records', autospec=True, side_effect=user_access.UserCsvImport.records) as parse, \
                patch.object(user_access, 'build_users', wraps=user_access.build_users) as users:
            report = self.refresh()
        self.assertEqual(self.statuses(report), {'roles': ('updated', False), 'users': ('unchanged', True)})
        self.assertEqual((parse.call_count, users.call_count), (0, 1))                       # the users file was not read, only re-mapped
        self.assertIn('FB04', cache.get_snapshot().tcode_index)

    def test_unknown_or_stale_fingerprints_take_the_full_path_once_and_are_then_recorded(self):
        snapshot = config.get_settings().data_lifecycle.sources['users'].snapshot
        source_store.set_fingerprint('users', snapshot, '')                                  # as left by the previous version
        self.assertEqual(self.statuses(self.refresh())['users'], ('unchanged', False))
        self.assertEqual(self.statuses(self.refresh())['users'], ('unchanged', True))
        source_store.set_fingerprint('users', snapshot, 'f' * 64)                            # a different parser or profile than the one that built the revision
        self.assertEqual(self.statuses(self.refresh())['users'], ('unchanged', False))

    def test_activation_observes_assignment_lifecycle_and_a_failure_never_fails_the_load(self):
        import assignment_lifecycle
        self.write(41)
        with patch.object(assignment_lifecycle, 'observe') as observe:
            self.refresh()
        observe.assert_called_once()
        self.write(42)
        with patch.object(assignment_lifecycle, 'observe', side_effect=RuntimeError('unreadable')), self.assertLogs('sap-lens', 'WARNING'):
            report = self.refresh()
        self.assertEqual(self.statuses(report)['users'], ('updated', False))
        self.assertEqual(len(cache.get_snapshot().users.users), 42)

    def test_a_missing_store_still_refreshes_correctly(self):
        import shutil
        shutil.rmtree(store_db.directory())
        self.assertEqual(self.statuses(self.refresh())['users'], ('unchanged', False))
        self.write(41)
        self.assertEqual(self.statuses(self.refresh())['users'], ('updated', False))
        self.assertEqual(len(cache.get_snapshot().users.users), 41)

    def test_a_held_suspicious_import_is_still_held_and_the_fast_path_is_not_used(self):
        self.write(10)
        import import_checks
        with self.assertRaises(import_checks.ImportHeld):
            self.refresh()
        self.assertEqual(len(cache.get_snapshot().users.users), 40)

    def test_failed_activation_leaves_neither_a_visible_revision_nor_staged_leftovers(self):
        active = source_store.active('users')
        self.write(41)
        with patch.object(csv_lifecycle, 'save_configuration', side_effect=RuntimeError('lost the compare-and-swap')):
            with self.assertRaises(RuntimeError):
                self.refresh()
        self.assertEqual(source_store.active('users')['snapshot'], active['snapshot'])
        self.assertEqual([item for item in source_store.revisions() if item['status'] == 'staged'], [])
        self.assertEqual(len(cache.get_snapshot().users.users), 40)
        self.assertEqual(config.get_settings().data_lifecycle.sources['users'].snapshot, active['snapshot'])

    def test_successful_activation_flips_the_store_in_step_with_the_configuration(self):
        self.write(41)
        self.refresh()
        reference = config.get_settings().data_lifecycle.sources['users']
        active = source_store.active('users')
        self.assertEqual((active['snapshot'], active['rows']), (reference.snapshot, 82))
        self.assertEqual(sum(item['status'] == 'active' for item in source_store.revisions() if item['source'] == 'users'), 1)
        self.assertNotEqual(source_store.fingerprint('users', reference.snapshot), '')

    def test_readers_never_observe_a_partially_activated_dataset(self):
        problems, stop, samples = [], threading.Event(), [0, 0, 0]
        def reader(index):
            try:
                while not stop.is_set():
                    state = cache.get_snapshot()
                    users = state.users
                    # A dataset is internally consistent: the user index, the records and the report describe the same revision.
                    if len(users.source_records) != users.report.get('parsed_rows', len(users.source_records)) or len({r['USERNAME'] for r in users.source_records}) != len(users.users):
                        problems.append('torn users')
                    if users.source_records and not state.roles:
                        problems.append('users without catalogue')
                    samples[index] += 1
                    # Yield the GIL between samples: three busy loops otherwise starve the refresh being observed (27-30 s instead of
                    # well under a second) without sampling any finer, because a reader only runs while it holds the GIL anyway.
                    time.sleep(0)
            except Exception as error:  # noqa: BLE001 - a dead reader must fail the test, never pass it silently
                problems.append(f'reader {index} failed: {type(error).__name__}: {error}')
        threads = [threading.Thread(target=reader, args=(index,)) for index in range(3)]
        for item in threads: item.start()
        try:
            for count, role_text in ((41, ROLES), (42, ROLES.replace('FB03', 'FB04')), (43, ROLES)):
                self.write(count); (self.root / 'roles.csv').write_text(role_text)
                self.refresh()
        finally:
            stop.set()
            for item in threads: item.join(timeout=30)
        self.assertEqual(problems, [])
        self.assertTrue(all(count >= 100 for count in samples), f'every reader sampled throughout the refreshes: {samples}')
        self.assertEqual(len(cache.get_snapshot().users.users), 43)

    def test_concurrent_loaders_never_leave_two_active_revisions_or_a_corrupt_store(self):
        self.write(41)
        errors = []
        def run():
            try:
                for _ in range(3):
                    csv_lifecycle.load(config.get_settings(), operation='refresh')          # non-strict: a lost compare-and-swap is reported, not raised
            except Exception as error:  # noqa: BLE001
                errors.append(error)
        threads = [threading.Thread(target=run) for _ in range(3)]
        for item in threads: item.start()
        for item in threads: item.join(timeout=120)
        self.assertEqual(errors, [])
        self.assertEqual(store_db.health(), [])
        self.assertEqual(sum(item['status'] == 'active' for item in source_store.revisions() if item['source'] == 'users'), 1)
        self.assertEqual(source_store.active('users')['snapshot'], config.get_settings().data_lifecycle.sources['users'].snapshot)


class SchemaLadder(unittest.TestCase):
    def test_a_version_1_store_from_the_previous_release_is_upgraded_in_place(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': folder}):
            store_db.private_directory()
            connection = sqlite3.connect(store_db.path()); connection.execute('PRAGMA foreign_keys=ON'); store_db._v1(connection); connection.execute('PRAGMA user_version=1')
            connection.execute("INSERT INTO source_revisions (source, scope, sequence, snapshot, row_count, entity_count, rows_digest, report, status, created) VALUES ('users','',1,?,0,0,'d','{}','active','now')", ('a' * 64,))
            connection.commit(); connection.close()
            connection = store_db.connect()
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], store_db.SCHEMA_VERSION)
            self.assertEqual(connection.execute('SELECT snapshot, fingerprint FROM source_revisions').fetchone(), ('a' * 64, ''))
            connection.close()


if __name__ == '__main__':
    unittest.main()
