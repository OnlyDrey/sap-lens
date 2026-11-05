"""Staged source revisions belong to the operation that wrote them: cleanup never touches another loader's work, orphans are recovered."""
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cache
import config
import csv_lifecycle
import source_store
import store_db
from config_models import USER_FIELDS

HEADER = 'USERNAME,ROLE_NAME,EMAIL,USER_GROUP,USER_VALID_FROM,USER_VALID_TO,ROLE_VALID_FROM,ROLE_VALID_TO'.split(',')


def rows(count, prefix='U'):
    return [{**{name: '' for name in USER_FIELDS}, 'USERNAME': f'{prefix}{n:03d}', 'ROLE_NAME': 'Z:R'} for n in range(count)]


def staged():
    return sorted((item['snapshot'][0], item['status']) for item in source_store.revisions() if item['status'] == 'staged')


class Case(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        patcher = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(Path(self.temp.name) / 'private'), 'DATA_CSV_PATH': ''}); patcher.start(); self.addCleanup(patcher.stop)
        config.get_settings.cache_clear(); self.addCleanup(config.get_settings.cache_clear)
        self.addCleanup(lambda: [source_store.end(owner) for owner in list(source_store._operations)])


class Ownership(Case):
    def test_a_failed_operation_removes_only_its_own_staged_revisions(self):
        first, second = source_store.begin(), source_store.begin()
        source_store.stage('users', 'a' * 64, rows(5), {}, owner=first)
        source_store.stage('users', 'b' * 64, rows(6, 'V'), {}, owner=second)
        source_store.end(first)                                                      # the first loader failed
        self.assertEqual(staged(), [('b', 'staged')])                                # the second loader's work is intact
        source_store.activate('users', 'b' * 64)
        self.assertEqual(source_store.read('users', 'b' * 64)[0], rows(6, 'V'))
        source_store.end(second)
        self.assertEqual(source_store.active('users')['snapshot'], 'b' * 64)         # ending never touches an activated revision

    def test_a_snapshot_staged_by_two_operations_survives_until_the_last_one_lets_go(self):
        first, second = source_store.begin(), source_store.begin()
        source_store.stage('users', 'c' * 64, rows(4), {}, owner=first)
        source_store.stage('users', 'c' * 64, rows(4), {}, owner=second)             # identical content: one row set, shared
        source_store.end(first)
        self.assertEqual(staged(), [('c', 'staged')])                                # handed to the other claimant, not deleted
        source_store.activate('users', 'c' * 64)                                     # still activatable by the surviving operation
        source_store.end(second)
        self.assertEqual(source_store.active('users')['snapshot'], 'c' * 64)

    def test_the_last_operation_to_end_without_activating_removes_the_shared_revision(self):
        first, second = source_store.begin(), source_store.begin()
        source_store.stage('users', 'c' * 64, rows(4), {}, owner=first)
        source_store.stage('users', 'c' * 64, rows(4), {}, owner=second)
        source_store.end(first); source_store.end(second)
        self.assertEqual(staged(), [])

    def test_cancellation_inside_an_operation_discards_exactly_its_work(self):
        survivor = source_store.begin()
        source_store.stage('users', 'd' * 64, rows(3), {}, owner=survivor)
        with self.assertRaises(KeyboardInterrupt):
            with source_store.operation() as owner:
                source_store.stage('users', 'e' * 64, rows(3, 'W'), {}, owner=owner)
                raise KeyboardInterrupt()                                            # cancellation is not an Exception
        self.assertEqual(staged(), [('d', 'staged')])

    def test_activation_clears_ownership_so_a_later_failure_cannot_remove_it(self):
        owner = source_store.begin()
        source_store.stage('users', 'f' * 64, rows(3), {}, owner=owner)
        source_store.activate('users', 'f' * 64)
        source_store.end(owner)
        self.assertEqual(source_store.active('users')['snapshot'], 'f' * 64)
        self.assertIsNotNone(source_store.read('users', 'f' * 64))

    def test_overlapping_threads_stage_and_fail_independently(self):
        results, barrier = {}, threading.Barrier(4)
        def work(number):
            owner = source_store.begin()
            snapshot = f'{number:x}' * 64
            source_store.stage('users', snapshot, rows(30, f'T{number}'), {}, owner=owner)
            barrier.wait(timeout=30)                                                 # all four are staged at the same time
            if number % 2:
                source_store.end(owner)                                              # odd loaders fail
                results[number] = 'failed'
            else:
                source_store.activate('users', snapshot)
                source_store.end(owner)
                results[number] = 'activated'
        threads = [threading.Thread(target=work, args=(n,)) for n in range(4)]
        for item in threads: item.start()
        for item in threads: item.join(timeout=60)
        self.assertEqual(sorted(results.values()), ['activated', 'activated', 'failed', 'failed'])
        self.assertEqual(staged(), [])
        revisions = [item for item in source_store.revisions() if item['source'] == 'users']
        self.assertEqual(sum(item['status'] == 'active' for item in revisions), 1)
        self.assertEqual({item['snapshot'][0] for item in revisions}, {'0', '2'})     # both even loaders' revisions exist, none of the odd ones
        self.assertEqual(store_db.health(), [])


class Orphans(Case):
    def test_start_up_recovers_what_an_interrupted_process_left_behind_and_nothing_else(self):
        source_store.ingest('users', '1' * 64, rows(3), {})                          # active
        code = ('import sys; sys.path.insert(0, %r); import os, source_store; from test_staging_ownership import rows; '
                "o = source_store.begin(); source_store.stage('users', %r, rows(4, 'X'), {}, owner=o); os._exit(0)"
                % (str(Path(__file__).resolve().parents[1]), '2' * 64))
        done = subprocess.run([sys.executable, '-c', code], cwd=str(Path(__file__).resolve().parent), capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 0, done.stderr[-500:])
        self.assertEqual(staged(), [('2', 'staged')])                                # a crashed loader left its staging behind
        self.assertEqual(source_store.recover_orphans(0), 1)
        self.assertEqual(staged(), [])
        self.assertEqual(source_store.active('users')['snapshot'], '1' * 64)

    def test_while_running_only_old_unowned_revisions_are_recovered(self):
        live = source_store.begin()
        source_store.stage('users', 'a' * 64, rows(3), {}, owner=live)
        source_store.stage('users', 'b' * 64, rows(3, 'V'), {}, owner='dead-operation')
        source_store.stage('users', 'c' * 64, rows(3, 'W'), {}, owner='dead-operation')
        old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        with store_db.transaction() as connection:
            connection.execute("UPDATE source_revisions SET created=? WHERE snapshot=?", (old, 'b' * 64))
        self.assertEqual(source_store.recover_orphans(), 1)                          # recent revisions of unknown owners might belong to another process
        self.assertEqual(staged(), [('a', 'staged'), ('c', 'staged')])
        self.assertEqual(source_store.recover_orphans(0), 1)                         # at start-up the unknown one goes too; the live one never does
        self.assertEqual(staged(), [('a', 'staged')])

    def test_v2_stores_are_upgraded_with_an_empty_owner(self):
        store_db.private_directory()
        import sqlite3
        connection = sqlite3.connect(store_db.path()); connection.execute('PRAGMA foreign_keys=ON'); store_db._v1(connection); store_db._v2(connection); connection.execute('PRAGMA user_version=2')
        connection.execute("INSERT INTO source_revisions (source, scope, sequence, snapshot, row_count, entity_count, rows_digest, report, status, created) VALUES ('users','',1,?,0,0,'d','{}','staged','now')", ('9' * 64,))
        connection.commit(); connection.close()
        connection = store_db.connect()
        self.assertEqual(connection.execute('SELECT owner FROM source_revisions').fetchone(), ('',))
        connection.close()
        self.assertEqual(source_store.recover_orphans(0), 1)                         # ownerless staging from the previous release is an orphan


class Loaders(Case):
    def setUp(self):
        super().setUp()
        root = Path(self.temp.name)
        (root / 'roles.csv').write_text('FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT\nFI,Z:FI,Finance,Z:FI:READ,Read,FB03,Display\n')
        self.users = root / 'users.csv'
        self.write(40)
        settings = config.get_settings().model_copy(deep=True)
        settings.data_csv_path, settings.user_csv_path = str(root / 'roles.csv'), str(self.users)
        config.save_configuration(settings, settings.revision)
        cache.clear_cache(); self.addCleanup(cache.clear_cache)
        csv_lifecycle.load(config.get_settings(), operation='refresh', strict=True)

    def write(self, count):
        import csv
        with self.users.open('w', newline='') as stream:
            writer = csv.writer(stream); writer.writerow(HEADER)
            writer.writerows([f'U{u:03d}', f'Z:FI:{r}', f'u{u}@example.test', 'FIN', '20200101', '99991231', '20200101', '99991231'] for u in range(count) for r in range(2))

    def test_a_failing_loader_does_not_remove_a_concurrent_loaders_staged_revision(self):
        bystander = source_store.begin()
        source_store.stage('users', '7' * 64, rows(5, 'B'), {}, owner=bystander)       # another loader is mid-import
        self.write(41)
        with patch.object(csv_lifecycle, 'save_configuration', side_effect=RuntimeError('compare-and-swap lost')):
            with self.assertRaises(RuntimeError):
                csv_lifecycle.load(config.get_settings(), operation='refresh', strict=True)
        self.assertEqual(staged(), [('7', 'staged')])                                # only this loader's own staging was removed
        source_store.activate('users', '7' * 64)                                     # and the bystander can still finish
        self.assertEqual(source_store.active('users')['snapshot'], '7' * 64)

    def test_cancellation_before_commit_cleans_up_only_its_own_staging(self):
        bystander = source_store.begin()
        source_store.stage('users', '8' * 64, rows(5, 'B'), {}, owner=bystander)
        self.write(41)
        def cancelled(): raise csv_lifecycle.__dict__.get('Cancelled', KeyboardInterrupt)()
        with self.assertRaises(BaseException):
            csv_lifecycle.load(config.get_settings(), operation='refresh', strict=True, before_commit=cancelled)
        self.assertEqual(staged(), [('8', 'staged')])

    def test_overlapping_refreshes_with_one_lost_commit_leave_one_consistent_active_revision(self):
        self.write(41)
        gate = threading.Barrier(2)
        calls = []
        original = csv_lifecycle.save_configuration
        def contested(settings, expected):
            calls.append(1)
            try: gate.wait(timeout=5)                                                # both loaders reach the commit together
            except threading.BrokenBarrierError: pass
            if len(calls) == 1:
                raise RuntimeError('lost the compare-and-swap')
            return original(settings, expected)
        outcomes = []
        def run():
            try:
                with patch.object(csv_lifecycle, 'save_configuration', contested):
                    csv_lifecycle.load(config.get_settings(), operation='refresh', strict=True)
                outcomes.append('ok')
            except RuntimeError:
                outcomes.append('lost')
        threads = [threading.Thread(target=run) for _ in range(2)]
        for item in threads: item.start()
        for item in threads: item.join(timeout=120)
        self.assertEqual(sorted(outcomes), ['lost', 'ok'])
        self.assertEqual(staged(), [])
        self.assertEqual(source_store.active('users')['snapshot'], config.get_settings().data_lifecycle.sources['users'].snapshot)
        self.assertIsNotNone(source_store.read('users', config.get_settings().data_lifecycle.sources['users'].snapshot))
        self.assertEqual(store_db.health(), [])

    def test_the_unchanged_fast_path_still_applies(self):
        report = csv_lifecycle.load(config.get_settings(), operation='refresh', strict=True)
        self.assertTrue(all(row.get('fast_path') for row in report['sources'] if row['source'] in {'roles', 'users'}))


if __name__ == '__main__':
    unittest.main()
