"""Restart handoff safety using disposable synthetic stores only."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import application_backups as backups
import maintenance
import config
from config_models import AppConfig
from storage_lease import StorageLease
from version import VERSION


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source';self.data=self.root/'destination'
        for root,mode in ((self.source,'desktop'),(self.data,'server')):
            root.mkdir();(root/'deployment.json').write_text(json.dumps(dict(version=1,mode=mode)))
            (root/'settings.json').write_text(AppConfig().model_dump_json())
        self.env=patch.dict(os.environ,{'SAP_LENS_DEPLOYMENT_MODE':'desktop','SAP_LENS_CONFIG_DIR':str(self.data),'SAP_LENS_DATA_DIR':str(self.data)})
        self.env.start();self.addCleanup(self.env.stop);config.get_settings.cache_clear();self.addCleanup(config.get_settings.cache_clear)
        (self.source/'saved-filters.json').write_text(json.dumps(dict(schema_version=1,items=[])))
        (self.data/'destination-only.json').write_text('{"synthetic":true}')
        (self.data/'users.json').write_text('{"protected":"synthetic-credential-store"}')
        (self.data/'tls.key').write_text('synthetic-destination-key')
        self.archive=self.root/'exports'/'source.tar.gz'
        maintenance.backup(self.source,self.archive,'desktop',VERSION)

    def preview(self):
        with backups.uploaded(self.data) as (identity,path):
            path.write_bytes(self.archive.read_bytes())
            return backups.register_upload(identity,self.data)

    def confirm(self):
        result=self.preview();backups.confirm_restore(result['id'],result['archive_sha256'],True,self.data)
        return result

    def activate(self):
        lease=StorageLease(self.data,'server').acquire()
        try: backups.startup(lease)
        finally: lease.close()

    def test_cross_mode_restore_preserves_security_and_replaces_not_merges(self):
        original=(self.data/'users.json').read_bytes()
        result=self.confirm();self.assertTrue((self.data/'destination-only.json').exists())
        self.activate()
        self.assertEqual(backups.read(self.data)['status'],'completed')
        self.assertFalse((self.data/'destination-only.json').exists())
        self.assertEqual((self.data/'users.json').read_bytes(),original)
        self.assertEqual((self.data/'tls.key').read_text(),'synthetic-destination-key')
        self.assertEqual(json.loads((self.data/'deployment.json').read_text())['mode'],'server')
        settings=AppConfig.model_validate_json((self.data/'settings.json').read_bytes())
        self.assertFalse(settings.refresh_schedule.enabled)
        self.assertEqual(settings.source_modes.roles,'static')
        self.assertTrue(backups.download(result['id'],'destination-before-restore',self.data).exists())

    def test_export_requires_restart_and_excludes_credentials(self):
        result=backups.request_backup(self.data)
        with self.assertRaises(ValueError): backups.download(result['id'],data=self.data)
        self.activate()
        header=maintenance.verify(backups.download(result['id'],data=self.data),'server',VERSION)
        self.assertNotIn('data/users.json',header['files']);self.assertNotIn('data/tls.key',header['files'])
        self.assertIn('data/deployment.json',header['files'])

    def test_corrupt_archive_and_changed_preview_never_replace(self):
        result=self.preview()
        with self.assertRaises(ValueError): backups.confirm_restore(result['id'],'0'*64,True,self.data)
        self.assertFalse(backups.pending(self.data))
        (backups.path_for(result['id'],self.data)/'archive.tar.gz').write_bytes(b'broken')
        with self.assertRaises(ValueError): backups.confirm_restore(result['id'],result['archive_sha256'],True,self.data)
        self.assertTrue((self.data/'destination-only.json').exists())

    def test_failed_activation_rolls_back_and_retains_automatic_backup(self):
        result=self.confirm();original=os.replace
        def fail(source,target):
            if Path(source).name=='saved-filters.json' and '/stage/data/' in str(source): raise OSError('synthetic failure')
            return original(source,target)
        with patch.object(backups.os,'replace',side_effect=fail): self.activate()
        self.assertEqual(backups.read(self.data)['status'],'failed')
        self.assertTrue((self.data/'destination-only.json').exists())
        self.assertTrue(backups.download(result['id'],'destination-before-restore',self.data).exists())

    def test_internal_backup_lease_must_match(self):
        with self.assertRaises(ValueError): maintenance.backup(self.source,self.root/'no.tar.gz','desktop',VERSION,_lease=object())

    def test_cancel_pending_restore_does_not_modify_active_store(self):
        self.confirm();backups.cancel(self.data)
        self.assertFalse(backups.pending(self.data));self.assertTrue((self.data/'destination-only.json').exists())

    def test_invalid_operation_ids_and_missing_snapshot_references(self):
        for value in ('../escape','/etc/passwd','x'*32):
            with self.assertRaises(ValueError):backups.download(value,data=self.data)
        config_value=AppConfig();from config_models import SourceSnapshot
        config_value.data_lifecycle.sources['roles']=SourceSnapshot(snapshot='f'*64,path='synthetic.csv',imported_at='2026-01-01T00:00:00Z',checked_at='2026-01-01T00:00:00Z')
        (self.source/'settings.json').write_text(config_value.model_dump_json())
        with self.assertRaises(ValueError):backups.validate_store(self.source)

    def test_http_requests_require_capability_and_pause_writes_until_cancel(self):
        from fastapi.testclient import TestClient
        from main import create_app
        client=TestClient(create_app(session_token='synthetic-backup-session'),base_url='http://127.0.0.1:18743')
        headers={'X-SAP-Lens':'synthetic-backup-session'}
        self.assertEqual(client.get('/api/backups').status_code,403)
        self.assertEqual(client.post('/api/backups/create',headers=headers).status_code,200)
        self.assertEqual(client.post('/api/refresh',headers=headers).status_code,409)
        self.assertEqual(client.post('/api/backups/cancel',headers=headers).status_code,200)
        preview=client.post('/api/backups/upload',headers={**headers,'Content-Type':'application/gzip'},content=self.archive.read_bytes())
        self.assertEqual(preview.status_code,200,preview.text)
        self.assertEqual(preview.json()['preview']['source_mode'],'desktop')
        self.assertEqual(client.get('/api/backups/'+preview.json()['id']+'/download',headers=headers).status_code,409)
        with patch.object(backups,'MAX_UPLOAD',2):
            self.assertEqual(client.post('/api/backups/upload',headers={**headers,'Content-Type':'application/gzip'},content=b'xxx').status_code,413)

    def test_server_backup_reads_and_downloads_require_actual_administrator(self):
        from fastapi.testclient import TestClient
        from main import create_app
        from deployment import ServerSettings
        from server_access import manage_user
        import base64
        account=self.root/'auth'/'accounts.json';account.parent.mkdir()
        for name,role in [('admin','administrator'),('reader','read-only')]:
            manage_user(account,dict(username=name,role=role,password='Synthetic-backup-password-123!',enabled=True))
        server=ServerSettings('127.0.0.1',18743,self.data,self.root/'sources','http://127.0.0.1:18743',('127.0.0.1',),'users','','',(),'info',accounts=str(account))
        client=TestClient(create_app(server=server),base_url='http://127.0.0.1:18743',client=('127.0.0.1',50000))
        for name,expected in [('reader',403),('admin',200)]:
            headers={'Authorization':'Basic '+base64.b64encode((name+':Synthetic-backup-password-123!').encode()).decode(),'X-SAP-Lens':'1'}
            self.assertEqual(client.get('/api/backups',headers=headers).status_code,expected)
            if name=='reader': self.assertEqual(client.get('/api/backups/'+'a'*32+'/download',headers=headers).status_code,403)

    def test_snapshot_paths_static_restore_without_reading_original_machine(self):
        from config_models import SourceSnapshot
        from csv_lifecycle import write_private,load
        source=AppConfig();source.data_csv_path=r'C:\SyntheticSource\catalogue.csv'
        from config_models import FIELDS
        row={name:'' for name in FIELDS};row.update(AGR_NAME='ZC:SYNTHETIC:ROLE',TEXT='Synthetic role')
        with patch.dict(os.environ,{'SAP_LENS_CONFIG_DIR':str(self.source)}):
            config.get_settings.cache_clear()
            identity=write_private('snapshots',dict(version=1,source='roles',records=[row],report={'warnings':[]}))
        source.data_lifecycle.sources['roles']=SourceSnapshot(snapshot=identity,path=source.data_csv_path,imported_at='2026-01-01T00:00:00Z',checked_at='2026-01-01T00:00:00Z')
        (self.source/'settings.json').write_text(source.model_dump_json());self.archive.unlink()
        maintenance.backup(self.source,self.archive,'desktop',VERSION)
        self.confirm();self.activate();config.get_settings.cache_clear()
        restored=config.get_settings()
        self.assertEqual(restored.source_modes.roles,'static')
        import cache
        cache.clear_cache();self.addCleanup(cache.clear_cache)
        # Static startup must use the durable snapshot, never the former source path.
        with patch('builtins.open',wraps=open) as opened:
            result=load(restored,operation='startup')
            self.assertNotEqual(result.get('status'),'failed',result)
            self.assertIn('ZC:SYNTHETIC:ROLE',cache.get_snapshot().roles)
            self.assertFalse(any(str(call.args[0])==source.data_csv_path for call in opened.call_args_list))

    def test_interrupted_activation_rollback_is_idempotent(self):
        result=self.confirm();operation=backups.path_for(result['id'],self.data)
        _,stage=backups.prepare(operation/'archive.tar.gz',operation,data=self.data)
        old=operation/'old';old.mkdir()
        journal=dict(old=['destination-only.json'],new=['saved-filters.json'])
        backups.write(operation/'journal.json',journal)
        os.replace(self.data/'destination-only.json',old/'destination-only.json')
        os.replace(stage/'saved-filters.json',self.data/'saved-filters.json')
        self.activate()
        self.assertEqual(backups.read(self.data)['status'],'failed')
        self.assertTrue((self.data/'destination-only.json').exists())
        self.assertFalse((self.data/'saved-filters.json').exists())

    def test_failed_rollback_blocks_startup_and_can_recover_on_next_start(self):
        result=self.confirm();original=os.replace
        def fail(source,target):
            if Path(source).name=='saved-filters.json' and '/stage/data/' in str(source) or '/old/' in str(source): raise OSError('synthetic failure')
            return original(source,target)
        with patch.object(backups.os,'replace',side_effect=fail),self.assertRaises(RuntimeError): self.activate()
        self.assertTrue((backups.path_for(result['id'],self.data)/'journal.json').exists())
        self.activate()
        self.assertTrue((self.data/'destination-only.json').exists())
        self.assertEqual(backups.read(self.data)['status'],'failed')

from test_sod_periods_v2 import PeriodV2Case


class ReviewHistoryTransferTests(PeriodV2Case):
    def test_approved_period_and_append_only_history_transfer_byte_for_byte(self):
        pid=self.new_period();self.decide_everything(pid)
        self.move(pid,'In review');self.move(pid,'Ready for approval');self.approve(pid)
        settings=config.get_settings().model_copy(deep=True)
        # This fixture's evidence cache is synthetic in-memory; its fake source
        # digest is provenance, not a physical durable-source fixture.
        settings.data_lifecycle.sources.clear();config.save_configuration(settings,settings.revision)
        (self.root/'deployment.json').write_text(json.dumps(dict(version=1,mode='desktop')))
        preserved={p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file() and (p.name in {'sod-decisions.json','sod-periods.json'} or p.parent.name=='snapshots')}
        with tempfile.TemporaryDirectory() as folder:
            destination=Path(folder)/'data';destination.mkdir()
            (destination/'deployment.json').write_text(json.dumps(dict(version=1,mode='server')))
            archive=Path(folder)/'exports'/'source.tar.gz'
            maintenance.backup(self.root,archive,'desktop',VERSION)
            with patch.dict(os.environ,{'SAP_LENS_CONFIG_DIR':str(destination)}):
                with backups.uploaded(destination) as (identity,path):
                    path.write_bytes(archive.read_bytes());preview=backups.register_upload(identity,destination)
                self.assertEqual(preview['preview']['review_periods'],1)
                self.assertEqual(preview['preview']['decision_events'],8)
                backups.confirm_restore(identity,preview['archive_sha256'],True,destination)
                lease=StorageLease(destination,'server').acquire()
                try:backups.startup(lease)
                finally:lease.close()
                self.assertEqual(backups.read(destination)['status'],'completed')
                for name,raw in preserved.items():self.assertEqual((destination/name).read_bytes(),raw,name)

class NativeBackupDownloadTests(unittest.TestCase):
    setUp=BackupTests.setUp
    activate=BackupTests.activate
    def test_native_download_uses_validated_operation_id_and_capability(self):
        from desktop import NativeDialogs
        from types import SimpleNamespace
        result=backups.request_backup(self.data);self.activate()
        owner=NativeDialogs('synthetic-native-backup-token')
        destination=self.root/'download.tar.gz'
        owner._window=SimpleNamespace(create_file_dialog=lambda *args,**kwargs:[str(destination)])
        with self.assertRaises(ValueError):owner.save_application_backup('wrong',result['id'])
        with patch.dict(sys.modules,{'webview':SimpleNamespace(FileDialog=SimpleNamespace(SAVE=1))}):
            self.assertTrue(owner.save_application_backup('synthetic-native-backup-token',result['id']))
        self.assertEqual(destination.read_bytes(),backups.download(result['id'],data=self.data).read_bytes())
