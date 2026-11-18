"""Upgrade of an existing installation: verified backup first, JSON stores untouched, idempotent resume, recovery, explicit confirmation."""
import csv
import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cache
import config
import csv_lifecycle
import maintenance as engine
import source_store
import storage_migration as migration
import store_db
from storage_lease import StorageLease
from version import VERSION

HEADER = 'USERNAME,ROLE_NAME,EMAIL,USER_GROUP,USER_VALID_FROM,USER_VALID_TO,ROLE_VALID_FROM,ROLE_VALID_TO'.split(',')
ROLES = 'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT\nFI,Z:FI,Finance,Z:FI:READ,Read,FB03,Display\n'


def digests(root, skip=('store', '.application-backups', 'cache', 'runtime.json', '.sap-lens-instance.lock', 'deployment.json')):
    result = {}
    for path in sorted(Path(root).rglob('*')):
        relative = path.relative_to(root)
        if path.is_file() and relative.parts[0] not in skip and '.log' not in path.suffixes:
            result[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


class Installation(unittest.TestCase):
    """An installation as the previous version left it: JSON stores and snapshots, no SQLite store."""

    def setUp(self):
        from windows_test_instance import isolate_desktop_instance
        isolate_desktop_instance(self)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'private'
        import backup_crypto as crypto
        key=self.root/'host.key';crypto.create_key(key,self.data)
        patcher = patch.dict(os.environ, {'SAP_LENS_BACKUP_KEY_FILE':str(key),'SAP_LENS_CONFIG_DIR': str(self.data), 'DATA_CSV_PATH': ''}); patcher.start(); self.addCleanup(patcher.stop)
        config.get_settings.cache_clear(); cache.clear_cache(); self.addCleanup(cache.clear_cache); self.addCleanup(config.get_settings.cache_clear)
        (self.root / 'roles.csv').write_text(ROLES)
        with (self.root / 'users.csv').open('w', newline='') as stream:
            writer = csv.writer(stream); writer.writerow(HEADER)
            writer.writerows([f'U{u:03d}', f'Z:FI:{r}', f'u{u}@example.test', 'FIN', '20200101', '99991231', '20200101', '99991231'] for u in range(30) for r in range(2))
        settings = config.get_settings().model_copy(deep=True)
        settings.data_csv_path, settings.user_csv_path = str(self.root / 'roles.csv'), str(self.root / 'users.csv')
        config.save_configuration(settings, settings.revision)
        csv_lifecycle.load(config.get_settings(), operation='refresh', strict=True)
        self.legacy()

    def legacy(self):
        shutil.rmtree(store_db.directory(), ignore_errors=True)
        shutil.rmtree(self.data / 'cache', ignore_errors=True)
        shutil.rmtree(self.data / '.application-backups', ignore_errors=True)

    def lease(self):
        lease = StorageLease(self.data, 'desktop').acquire(); self.addCleanup(lease.close)
        return lease

    def run_migration(self):
        lease = self.lease()
        try:
            return migration.run(lease)
        finally:
            lease.close()


class Migrate(Installation):
    def test_existing_installation_is_backed_up_verified_and_migrated_without_touching_json(self):
        before = digests(self.data)
        self.assertTrue(before)
        self.assertEqual(self.run_migration()['state'], 'migrated')
        self.assertEqual(digests(self.data), before)                                  # settings, snapshots, every JSON store: byte-identical
        status = migration.status()
        self.assertTrue(status['requires_confirmation'])
        archive = self.data / migration.FOLDER / status['backup']['id'] / migration.ARCHIVE
        self.assertEqual(engine.digest(archive), status['backup']['sha256'])
        from portable_backups import readable
        with readable(archive,self.data) as (canonical,encrypted):manifest=engine.verify(canonical,'desktop',VERSION)
        self.assertTrue(encrypted)
        self.assertIn('data/settings.json', manifest['files'])
        self.assertFalse(any(name.startswith('data/store/') or name.startswith('data/cache/') for name in manifest['files']))
        settings = config.get_settings()
        for source, reference in settings.data_lifecycle.sources.items():
            self.assertEqual(source_store.active(source)['snapshot'], reference.snapshot)
            self.assertIsNotNone(source_store.read(source, reference.snapshot))

    def test_fresh_installation_needs_no_backup(self):
        shutil.rmtree(self.data)
        self.assertEqual(self.run_migration()['state'], 'fresh')
        self.assertTrue(store_db.path().exists())
        self.assertFalse((self.data / migration.FOLDER).exists())

    def test_running_again_is_a_no_op_and_the_backup_is_never_aged_out(self):
        self.run_migration()
        record = migration.status()['backup']
        archive = self.data / migration.FOLDER / record['id'] / migration.ARCHIVE
        os.utime(archive, (1, 1))                                                     # ancient
        import backup_schedule
        for _ in range(2):
            self.assertEqual(self.run_migration()['state'], 'current')
            backup_schedule.retention(self.data)
        self.assertTrue(archive.is_file())
        self.assertEqual(migration.status()['backup']['id'], record['id'])
        self.assertEqual(len(migration._records(self.data)), 1)

    def test_backup_failure_prevents_the_migration_and_is_retried(self):
        with patch.object(engine, 'backup', side_effect=engine.MaintenanceError('disk full')):
            self.assertEqual(self.run_migration()['state'], 'backup_failed')
        self.assertFalse(store_db.path().exists())                                    # no store without a verified backup
        self.assertEqual(migration._records(self.data), [])
        self.assertEqual(self.run_migration()['state'], 'migrated')

    def test_interrupted_migration_resumes_with_the_same_verified_backup(self):
        with patch.object(migration, '_mirror_all', side_effect=RuntimeError('power loss')):
            self.assertEqual(self.run_migration()['state'], 'failed')
        (record,) = migration._records(self.data)
        self.assertEqual(record['status'], 'migrating')
        self.assertTrue((self.data / migration.FOLDER / record['id'] / migration.ARCHIVE).is_file())
        self.assertEqual(self.run_migration()['state'], 'migrated')
        (resumed,) = migration._records(self.data)
        self.assertEqual((resumed['id'], resumed['backup']['sha256']), (record['id'], record['backup']['sha256']))

    def test_an_unreadable_snapshot_leaves_the_migration_incomplete_and_the_backup_in_place(self):
        settings = config.get_settings()
        snapshot = settings.data_lifecycle.sources['users'].snapshot
        path = csv_lifecycle.private_path('snapshots', snapshot)
        original = path.read_bytes()
        path.write_bytes(original[:-20])
        result = self.run_migration()
        path.write_bytes(original)
        self.assertIn(result['state'], {'incomplete', 'backup_failed'})
        if result['state'] == 'incomplete':
            self.assertEqual(self.run_migration()['state'], 'migrated')               # repaired snapshot completes the same migration


class Confirm(Installation):
    def setUp(self):
        super().setUp()
        self.run_migration()
        self.identity = migration.status()['backup']['id']
        self.archive = self.data / migration.FOLDER / self.identity / migration.ARCHIVE

    def test_confirmation_keeps_the_backup_and_deleting_it_is_a_separate_explicit_step(self):
        with self.assertRaises(migration.NotReady):
            migration.delete_backup(self.identity, 'admin')                        # never before confirmation
        result = migration.confirm(self.identity, 'admin@example.test')
        self.assertTrue(self.archive.is_file())                                     # confirmation does not delete
        self.assertFalse(result['requires_confirmation'])
        self.assertEqual((result['retained']['id'], result['confirmed'][0]['confirmed_by']), (self.identity, 'admin@example.test'))
        self.assertEqual(self.run_migration()['state'], 'current')                    # confirmation is durable
        import backup_schedule
        os.utime(self.archive, (1, 1))
        backup_schedule.retention(self.data)                                          # no retention rule touches it
        self.assertTrue(self.archive.is_file())
        after = migration.delete_backup(self.identity, 'admin@example.test')
        self.assertFalse(self.archive.exists())
        self.assertIsNone(after['retained'])
        record = next(item for item in migration._records(self.data) if item['id'] == self.identity)
        self.assertEqual((record['status'], record['backup_deleted_by']), ('confirmed', 'admin@example.test'))
        with self.assertRaises(migration.NotReady):
            migration.delete_backup(self.identity, 'admin')                        # nothing left to delete

    def test_an_unhealthy_store_cannot_release_the_backup(self):
        store_db.path().write_bytes(b'garbage' * 100)
        with self.assertRaises(migration.NotReady):
            migration.confirm(self.identity, 'admin')
        self.assertTrue(self.archive.is_file())
        with self.assertRaises(migration.NotReady):
            migration.confirm('0' * 32, 'admin')


class Recovery(Installation):
    def test_corrupt_database_is_moved_aside_and_rebuilt_from_the_snapshots(self):
        self.run_migration()
        for suffix in ('-wal', '-shm'):
            Path(str(store_db.path()) + suffix).unlink(missing_ok=True)
        store_db.path().write_bytes(b'SQLite format 3\x00' + os.urandom(4000))
        self.assertEqual(self.run_migration()['state'], 'rebuilt')                     # no second backup: the JSON stores were never at risk
        self.assertEqual(len(migration._records(self.data)), 1)
        self.assertEqual(store_db.health(), [])
        self.assertTrue(list(store_db.directory().glob('sap-lens.sqlite3.corrupt-*')))
        for source, reference in config.get_settings().data_lifecycle.sources.items():
            self.assertIsNotNone(source_store.read(source, reference.snapshot))

    def test_a_newer_database_is_left_alone_and_the_application_still_loads_from_json(self):
        store_db.connect().close()
        connection = sqlite3.connect(store_db.path()); connection.execute('PRAGMA user_version=99'); connection.close()
        before = hashlib.sha256(store_db.path().read_bytes()).hexdigest()
        self.assertEqual(self.run_migration()['state'], 'newer')
        self.assertEqual(hashlib.sha256(store_db.path().read_bytes()).hexdigest(), before)
        state = csv_lifecycle.restore(config.get_settings())
        self.assertEqual(len(state.users.users), 30)

    def test_restoring_the_pre_migration_backup_reproduces_the_previous_installation(self):
        original = digests(self.data)
        self.run_migration()
        status = migration.status()
        archive = self.data / migration.FOLDER / status['backup']['id'] / migration.ARCHIVE
        target = self.root / 'restored'
        from portable_backups import readable
        with readable(archive,self.data) as (canonical,encrypted):engine.restore(canonical,target,'desktop',VERSION,confirm=True)
        self.assertTrue(encrypted)
        restored=digests(target)
        self.assertEqual(restored.pop('backup-schedule.json'),hashlib.sha256((target/'backup-schedule.json').read_bytes()).hexdigest())
        self.assertEqual(restored,original)
        with patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(target)}):
            config.get_settings.cache_clear()
            lease = StorageLease(target, 'desktop').acquire()
            try:
                self.assertEqual(migration.run(lease)['state'], 'migrated')            # the restored installation upgrades again, from scratch
            finally:
                lease.close()
            self.assertEqual(len(csv_lifecycle.restore(config.get_settings()).users.users), 30)
        config.get_settings.cache_clear()

    def test_a_damaged_snapshot_is_still_reported_when_the_store_and_the_derived_cache_are_populated(self):
        self.run_migration()
        state = csv_lifecycle.restore(config.get_settings())             # populates the store and the derived cache
        self.assertTrue(state.users.users)
        reference = config.get_settings().data_lifecycle.sources['users']
        csv_lifecycle.private_path('snapshots', reference.snapshot).write_bytes(b'corrupt')
        cache.clear_cache()
        damaged = csv_lifecycle.restore(config.get_settings())
        self.assertIn('users', damaged.restore_errors)                    # the copies never mask damaged authoritative evidence
        self.assertFalse(damaged.users.users)

    def test_results_are_identical_with_and_without_the_store(self):
        self.run_migration()
        cache.clear_cache()
        with_store = csv_lifecycle.restore(config.get_settings())
        shutil.rmtree(store_db.directory())
        without = csv_lifecycle.restore(config.get_settings())
        again = csv_lifecycle.restore(config.get_settings())
        for other in (without, again):
            self.assertEqual(with_store.users.source_records, other.users.source_records)
            self.assertEqual(sorted(with_store.roles), sorted(other.roles))
            self.assertEqual(with_store.users.assignments, other.users.assignments)
            self.assertEqual({k: v.model_dump() for k, v in with_store.roles.items()}, {k: v.model_dump() for k, v in other.roles.items()})


class Interfaces(Installation):
    def test_application_backups_exclude_the_derived_store_and_the_migration_archive(self):
        import application_backups as backups
        self.run_migration()
        roots = backups.protected(self.data)
        self.assertTrue({'store', 'cache', '.application-backups'} <= roots)

    def test_status_and_confirm_endpoints(self):
        from fastapi.testclient import TestClient
        from main import create_app
        self.run_migration()
        client = TestClient(create_app(session_token='1'), base_url='http://127.0.0.1:18743'); headers = {'X-SAP-Lens': '1'}
        status = client.get('/api/storage/status', headers=headers).json()
        self.assertTrue(status['requires_confirmation'])
        self.assertEqual(status['state'], 'ready')
        identity = status['backup']['id']
        self.assertEqual(client.post('/api/storage/migration/confirm', headers=headers, json={'migration_id': identity, 'confirm': False}).status_code, 422)
        self.assertEqual(client.post('/api/storage/migration/confirm', headers=headers, json={'migration_id': '1' * 32, 'confirm': True}).status_code, 409)
        done = client.post('/api/storage/migration/confirm', headers=headers, json={'migration_id': identity, 'confirm': True})
        self.assertEqual(done.status_code, 200)
        self.assertFalse(done.json()['requires_confirmation'])
        self.assertEqual(done.json()['retained']['id'], identity)                      # kept after confirmation
        self.assertEqual(client.post('/api/storage/migration/delete-backup', headers=headers, json={'migration_id': identity, 'confirm': False}).status_code, 422)
        gone = client.post('/api/storage/migration/delete-backup', headers=headers, json={'migration_id': identity, 'confirm': True})
        self.assertEqual((gone.status_code, gone.json()['retained']), (200, None))
        self.assertEqual(client.post('/api/storage/migration/delete-backup', headers=headers, json={'migration_id': identity, 'confirm': True}).status_code, 409)


if __name__ == '__main__':
    unittest.main()
