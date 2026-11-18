"""Complete encrypted logical restore, with explicit credential rollback and no sessions."""
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
import config
import application_backups as backups
import backup_crypto as crypto
from auth_store import AuthStore,AuthError
from storage_lease import StorageLease
from branding import stage_image
from review_identity import profile

PASSWORD='Synthetic portable password æ 123!'


class PortableBackupTests(unittest.TestCase):
    def setUp(self):
        from windows_test_instance import isolate_desktop_instance
        isolate_desktop_instance(self)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name);self.data=root/'data';self.data.mkdir()
        self.key=root/'host.key';crypto.create_key(self.key,self.data)
        env=patch.dict(os.environ,{'SAP_LENS_CONFIG_DIR':str(self.data),'SAP_LENS_BACKUP_KEY_FILE':str(self.key),'SAP_LENS_DEPLOYMENT_MODE':'desktop'})
        env.start();self.addCleanup(env.stop)
        config.get_settings.cache_clear();self.addCleanup(config.get_settings.cache_clear)
        self.lease=StorageLease(self.data,'desktop').acquire();self.addCleanup(self.lease.close)
        image=BytesIO();Image.new('RGB',(64,64),'blue').save(image,format='PNG')
        self.logo=stage_image(image.getvalue())['logo_id']
        settings=config.get_settings().model_copy(deep=True);settings.organization.name='Synthetic portable organization';settings.logo_id=self.logo
        config.save_configuration(settings,settings.revision)
        (self.data/'report-branding.json').write_text(json.dumps(dict(logo_id=self.logo,filename='synthetic.png')))
        profile('Synthetic local reviewer',0)
        (self.data/'tls.key').write_text('Synthetic host key: excluded')
        self.store=AuthStore(self.data/'security/accounts.sqlite3');self.store.initialize()
        self.admin=self.store.create_user(None,'admin','Portable administrator','administrator',PASSWORD,bootstrap=True)
        self.actor,self.token,_=self.store.login('admin',PASSWORD,'fixture')

    def make(self):
        requested=backups.request_backup(self.data,passphrase=PASSWORD)
        backups.startup(self.lease)
        state=backups.read(self.data)
        self.assertEqual(state['status'],'ready',state)
        path=backups.download(requested['id'],data=self.data)
        self.assertEqual(path.suffix,'.slbak')
        return path

    def preview(self,path,secret=PASSWORD):
        with backups.uploaded(self.data) as (identifier,incoming):
            shutil.copyfile(path,incoming)
            return backups.register_upload(identifier,data=self.data,secret=secret)

    def test_complete_encrypted_restore_keeps_branding_accounts_identity_and_host_exclusions(self):
        path=self.make();key_before=self.key.read_bytes()
        self.assertNotIn(b'Portable administrator',path.read_bytes())
        self.store.change_password(self.actor,PASSWORD,PASSWORD+'changed')
        current=config.get_settings().model_copy(deep=True);current.organization.name='Changed destination';config.save_configuration(current,current.revision)
        profile('Changed local reviewer',1)
        preview=self.preview(path)
        self.assertEqual(preview['preview']['accounts']['accounts'],1)
        self.assertTrue(preview['preview']['encrypted'])
        with self.assertRaises(Exception):backups.confirm_restore(preview['id'],preview['archive_sha256'],True,self.data)
        self.assertFalse(backups.pending(self.data))
        backups.confirm_restore(preview['id'],preview['archive_sha256'],True,self.data,confirm_accounts=True)
        backups.startup(self.lease)
        result=backups.read(self.data);self.assertEqual(result['status'],'completed',result)
        config.get_settings.cache_clear()
        self.assertEqual(config.get_settings().organization.name,'Synthetic portable organization')
        self.assertEqual(config.get_settings().logo_id,self.logo)
        self.assertEqual(json.loads((self.data/'report-branding.json').read_bytes())['logo_id'],self.logo)
        self.assertEqual(profile()['identity']['display_name'],'Synthetic local reviewer')
        self.assertEqual((self.data/'tls.key').read_text(),'Synthetic host key: excluded')
        self.assertEqual(self.key.read_bytes(),key_before)
        self.assertEqual(self.store.login('admin',PASSWORD,'restored')[0].id,self.admin['id'])
        with self.assertRaises(AuthError):self.store.session(self.token)
        recovery=backups.download(preview['id'],'destination-before-restore',self.data)
        self.assertEqual(recovery.suffix,'.slbak')
        self.assertFalse((backups.path_for(preview['id'],self.data)/'journal.json').exists())

    def test_wrong_passphrase_and_tampered_archive_preserve_dataset_and_accounts(self):
        path=self.make()
        with self.assertRaises(crypto.BackupCryptoError):self.preview(path,'Wrong synthetic passphrase 123!')
        self.assertEqual(self.store.session(self.token).id,self.actor.id)
        self.assertFalse(backups.pending(self.data))
        corrupt=self.data.parent/'corrupt.slbak';raw=bytearray(path.read_bytes());raw[-1]^=1;corrupt.write_bytes(raw)
        with self.assertRaises(crypto.BackupCryptoError):self.preview(corrupt)
        self.assertEqual(config.get_settings().organization.name,'Synthetic portable organization')

    def test_pending_reset_survives_restore_but_source_code_and_sessions_do_not(self):
        target=self.store.create_user(self.actor,'reset-user','Reset required','reviewer',PASSWORD)
        issued=self.store.issue_reset(self.actor,target['id'],0)
        path=self.make();preview=self.preview(path)
        backups.confirm_restore(preview['id'],preview['archive_sha256'],True,self.data,confirm_accounts=True);backups.startup(self.lease)
        self.assertEqual(backups.read(self.data)['status'],'completed')
        with self.assertRaises(AuthError):self.store.login('reset-user',PASSWORD,'restored')
        with self.assertRaises(AuthError):self.store.complete_reset(issued['code'],PASSWORD+'new','restored')
        admin=self.store.login('admin',PASSWORD,'restore-admin')[0]
        row=next(row for row in self.store.users(admin) if row['username']=='reset-user')
        code=self.store.issue_reset(admin,row['id'],row['revision'])['code']
        self.store.complete_reset(code,PASSWORD+'new','new-reset')
        self.assertEqual(self.store.login('reset-user',PASSWORD+'new','restored-new')[0].id,target['id'])

    def test_activation_failure_rolls_back_accounts_and_settings(self):
        path=self.make()
        self.store.change_password(self.actor,PASSWORD,PASSWORD+'current')
        preview=self.preview(path)
        backups.confirm_restore(preview['id'],preview['archive_sha256'],True,self.data,confirm_accounts=True)
        original=backups.validate_store
        def fail_activation(root,*args,**kwargs):
            if Path(root)==self.data:raise OSError('Synthetic activation failure')
            return original(root,*args,**kwargs)
        with patch.object(backups,'validate_store',side_effect=fail_activation):backups.startup(self.lease)
        self.assertEqual(backups.read(self.data)['status'],'failed')
        self.assertEqual(self.store.login('admin',PASSWORD+'current','after-rollback')[0].id,self.admin['id'])
        self.assertFalse(backups.pending(self.data))
        self.assertFalse((backups.path_for(preview['id'],self.data)/'journal.json').exists())

    def test_missing_key_fails_before_pausing_or_creating_any_archive(self):
        with patch.dict(os.environ,{'SAP_LENS_BACKUP_KEY_FILE':''}):
            with self.assertRaises(crypto.BackupCryptoError):backups.request_backup(self.data)
        self.assertFalse(backups.pending(self.data))
        self.assertEqual(self.store.session(self.token).id,self.actor.id)

    def test_portable_schedule_restores_disabled_and_preserves_current_recovery_configuration(self):
        import backup_schedule as schedule
        crypto.verify_escrow(self.key.read_text().strip(),self.data)
        schedule.save(dict(enabled=True,time='07:30',timezone='Europe/Oslo'),0,self.data)
        path=self.make();preview=self.preview(path)
        backups.confirm_restore(preview['id'],preview['archive_sha256'],True,self.data,confirm_accounts=True)
        backups.startup(self.lease)
        restored=schedule.settings(self.data)
        self.assertEqual(restored['schedule']['time'],'07:30')
        self.assertEqual(restored['schedule']['timezone'],'Europe/Oslo')
        self.assertFalse(restored['schedule']['enabled'])
        self.assertTrue(crypto.key_status(self.data)['escrow_verified'])

    def test_public_offline_cli_encrypts_and_requires_explicit_account_restore(self):
        import contextlib,io
        import maintenance
        self.lease.close()
        target=self.data.parent/'exports/offline.slbak'
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(maintenance.cli(['backup','--data',str(self.data),'--output',str(target),'--mode','desktop']),0)
            self.assertEqual(maintenance.cli(['verify','--data',str(self.data),'--archive',str(target),'--mode','desktop']),0)
        self.assertTrue(target.read_bytes().startswith(crypto.MAGIC))
        restored=self.data.parent/'empty-restored'
        # A refused archive leaves the empty target exactly as it was, so the valid archive can still be restored into it.
        modified=bytearray(target.read_bytes());modified[len(modified)//2]^=1
        tampered=self.data.parent/'exports/tampered.slbak';tampered.write_bytes(modified)
        prepared=self.data.parent/'prepared-empty';prepared.mkdir()
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            for destination in (restored,prepared):
                self.assertEqual(maintenance.cli(['restore','--archive',str(tampered),'--data',str(destination),'--mode','desktop','--confirm-restore','--confirm-accounts']),1)
        self.assertFalse(restored.exists());self.assertEqual(list(prepared.iterdir()),[])
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(maintenance.cli(['restore','--archive',str(target),'--data',str(prepared),'--mode','desktop','--confirm-restore','--confirm-accounts']),0)
            self.assertEqual(maintenance.cli(['restore','--archive',str(target),'--data',str(restored),'--mode','desktop','--confirm-restore','--confirm-accounts']),0)
        restored_store=AuthStore(restored/'security/accounts.sqlite3')
        self.assertEqual(restored_store.login('admin',PASSWORD,'restored')[0].id,self.admin['id'])
        with self.assertRaises(AuthError):restored_store.session(self.token)

