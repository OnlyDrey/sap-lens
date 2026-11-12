"""Stopped identity migration never mutates old credentials or frozen evidence."""
from contextlib import closing
from pathlib import Path
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import backup_crypto as crypto
import config
from config_models import AppConfig
from auth_store import AuthStore,AuthError
from auth_provisioning import complete,state
from identity_migration import migrate,records,confirm
from server_access import manage_user
from storage_lease import StorageLease

PASSWORD='Synthetic old password æ 123!'


class IdentityMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.data=self.root/'data';self.data.mkdir()
        self.env=patch.dict(os.environ,{'SAP_LENS_CONFIG_DIR':str(self.data),'SAP_LENS_DATA_DIR':str(self.data),'SAP_LENS_DEPLOYMENT_MODE':'server','SAP_LENS_BACKUP_KEY_FILE':str(self.root/'host.key')})
        self.env.start();self.addCleanup(self.env.stop);config.get_settings.cache_clear();self.addCleanup(config.get_settings.cache_clear)
        self.lease=StorageLease(self.data,'server').acquire();self.addCleanup(self.lease.close)
        (self.data/'settings.json').write_text(AppConfig().model_dump_json())
        (self.data/'historical-evidence.txt').write_bytes(b'Synthetic immutable evidence\n')
        crypto.create_key(self.root/'host.key',self.data)
        self.accounts=self.root/'private/users.json'
        for name,role,enabled in [('old-admin','administrator',True),('old-viewer','read-only',True),('disabled','reviewer',False)]:
            manage_user(self.accounts,dict(username=name,password=PASSWORD,role=role,enabled=enabled))
        self.original=self.accounts.read_bytes()

    def test_pbkdf_users_roles_disabled_state_uuid_and_evidence_survive_idempotently(self):
        before=(self.data/'historical-evidence.txt').read_bytes()
        result=migrate(self.lease,'users',str(self.accounts))
        self.assertEqual(result['state'],'migrated')
        store=AuthStore(self.data/'security/accounts.sqlite3')
        with store.connection() as db:
            old=list(db.execute('SELECT id,username,verifier FROM users'))
            self.assertTrue(all(row['verifier'].startswith('pbkdf2:') for row in old))
        actor=store.login('old-admin',PASSWORD,'migration-test')[0]
        viewer=store.login('old-viewer',PASSWORD,'migration-test')[0]
        self.assertEqual(viewer.role,'viewer')
        with self.assertRaises(AuthError):store.login('disabled',PASSWORD,'migration-test')
        with store.connection() as db:self.assertTrue(db.execute('SELECT verifier FROM users WHERE id=?',(actor.id,)).fetchone()[0].startswith('$argon2id$'))
        self.assertEqual(migrate(self.lease,'users','missing.json')['state'],'existing')
        with store.connection() as db:self.assertEqual({row['id'] for row in db.execute('SELECT id FROM users')},{row['id'] for row in old})
        self.assertEqual(self.accounts.read_bytes(),self.original)
        self.assertEqual((self.data/'historical-evidence.txt').read_bytes(),before)
        self.assertFalse(state(store)['setup_required'])
        row=records(self.data)[0];archive=self.data/'.application-backups/identity-migration'/row['id']/'pre-identity.slbak'
        self.assertTrue(archive.read_bytes().startswith(crypto.MAGIC))
        with self.assertRaises(AuthError):confirm(self.data,row['id'],actor,delete=True)
        confirm(self.data,row['id'],actor)
        self.assertTrue(archive.exists())
        confirm(self.data,row['id'],actor,delete=True)
        self.assertFalse(archive.exists())

    def test_failed_activation_rolls_back_and_retry_preserves_legacy_accounts(self):
        original=os.replace
        def fail(source,target):
            if Path(target)==self.data/'security':raise OSError('Synthetic activation failure')
            return original(source,target)
        with patch('identity_migration.os.replace',side_effect=fail):
            with self.assertRaises(OSError):migrate(self.lease,'users',str(self.accounts))
        self.assertFalse((self.data/'security').exists())
        self.assertEqual(records(self.data)[0]['status'],'failed')
        self.assertEqual(self.accounts.read_bytes(),self.original)
        self.assertEqual(migrate(self.lease,'users',str(self.accounts))['state'],'migrated')

    def test_missing_key_or_invalid_legacy_credentials_do_not_create_account_storage(self):
        with patch.dict(os.environ,{'SAP_LENS_BACKUP_KEY_FILE':''}):
            with self.assertRaises(crypto.BackupCryptoError):migrate(self.lease,'users',str(self.accounts))
        self.assertFalse((self.data/'security').exists())
        self.accounts.write_bytes(b'invalid')
        with self.assertRaises(ValueError):migrate(self.lease,'users',str(self.accounts))
        self.assertFalse((self.data/'security').exists())

    def test_shared_access_needs_explicit_local_recovery_not_public_first_run(self):
        with self.assertRaises(AuthError):migrate(self.lease,'basic')
        self.assertFalse((self.data/'security').exists())
        result=migrate(self.lease,'basic',new_administrator='controlled-admin')
        store=AuthStore(self.data/'security/accounts.sqlite3')
        self.assertFalse(state(store)['setup_required'])
        self.assertEqual(result['recovery']['purpose'],'recovery')
        with self.assertRaises(AuthError):store.login('controlled-admin',PASSWORD,'guess')
        user=complete(store,result['recovery']['code'],'','',PASSWORD,recovery=True)
        self.assertEqual(store.login('controlled-admin',PASSWORD,'recovered')[0].id,user['id'])
        with self.assertRaises(AuthError):complete(store,result['recovery']['code'],'','',PASSWORD,recovery=True)

    def test_crash_after_activation_is_reconciled_but_corruption_never_reinitializes(self):
        result=migrate(self.lease,'users',str(self.accounts));identifier=result['id']
        record=records(self.data)[0];record['status']='backup_verified'
        path=self.data/'.application-backups/identity-migration'/identifier/'record.json';path.write_text(json.dumps(record))
        migrate(self.lease,'users',str(self.accounts))
        self.assertEqual(records(self.data)[0]['status'],'migrated')
        target=self.data/'security/accounts.sqlite3'
        with closing(sqlite3.connect(target)) as db:db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        target.write_bytes(b'corrupt')
        with self.assertRaises(AuthError):migrate(self.lease,'users',str(self.accounts))
        self.assertEqual(target.read_bytes(),b'corrupt')

    def test_process_interruption_before_activation_resumes_the_same_verified_mapping(self):
        import subprocess
        self.lease.close()
        source=Path(__file__).resolve().parents[1]
        script='''import json,os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from storage_lease import StorageLease
import identity_migration as migration
p=json.load(sys.stdin);data=Path(p['data'])
lease=StorageLease(data,'server').acquire()
original=migration.os.replace
def interrupted(source,target):
    if Path(target)==data/'security':os._exit(99)
    return original(source,target)
migration.os.replace=interrupted
migration.migrate(lease,'users',p['accounts'])
'''
        done=subprocess.run([sys.executable,'-c',script,str(source)],input=json.dumps(dict(data=str(self.data),accounts=str(self.accounts))),text=True,capture_output=True,timeout=20)
        self.assertEqual(done.returncode,99,done.stderr)
        pending=records(self.data);self.assertEqual(len(pending),1)
        record=pending[0];self.assertEqual(record['status'],'backup_verified')
        staged=self.data/'.application-backups/identity-migration'/record['id']/'new-security/accounts.sqlite3'
        with closing(sqlite3.connect(staged)) as db:identities={row[0] for row in db.execute('SELECT id FROM users')}
        lease=StorageLease(self.data,'server').acquire()
        try:result=migrate(lease,'users',str(self.accounts))
        finally:lease.close()
        self.assertEqual(result['id'],record['id'])
        self.assertEqual(len(records(self.data)),1)
        with AuthStore(self.data/'security/accounts.sqlite3').connection() as db:self.assertEqual({row['id'] for row in db.execute('SELECT id FROM users')},identities)
        self.assertEqual(self.accounts.read_bytes(),self.original)
