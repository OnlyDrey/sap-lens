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
            if Path(source).name=='saved-filters.json' and '/stage/data/' in Path(source).as_posix(): raise OSError('synthetic failure')
            return original(source,target)
        with patch.object(backups.os,'replace',side_effect=fail): self.activate()
        self.assertEqual(backups.read(self.data)['status'],'failed')
        self.assertTrue((self.data/'destination-only.json').exists())
        self.assertTrue(backups.download(result['id'],'destination-before-restore',self.data).exists())

    def test_pending_backup_keeps_configuration_readable_and_rejects_duplicate(self):
        from fastapi.testclient import TestClient
        from main import create_app
        client=TestClient(create_app(session_token='synthetic-backup-session'),base_url='http://127.0.0.1:18743')
        headers={'X-SAP-Lens':'synthetic-backup-session'}
        first=client.post('/api/backups/create',headers=headers)
        self.assertEqual(first.json()['status'],'waiting_for_restart')
        self.assertEqual(client.post('/api/backups/create',headers=headers).status_code,409)
        self.assertEqual(client.get('/api/configuration',headers=headers).status_code,200)
        self.assertEqual(client.post('/api/backups/cancel',headers=headers).json()['status'],'cancelled')
        self.assertFalse(backups.pending(self.data))
        self.assertEqual(client.post('/api/backups/create',headers=headers).status_code,200)

    def test_corrupt_metadata_recovery_does_not_permanently_pause_writes(self):
        result=backups.request_backup(self.data)
        backups.write(backups.area(self.data)/'operation.json',[])
        self.assertEqual(backups.read(self.data)['status'],'failed')
        self.assertFalse(backups.pending(self.data))
        self.assertNotEqual(backups.request_backup(self.data)['id'],result['id'])

    def test_journal_owner_cannot_be_cancelled_or_overwritten_even_with_corrupt_metadata(self):
        result=self.confirm()
        operation=backups.path_for(result['id'],self.data)
        backups.write(operation/'journal.json',dict(old=[],new=[]))
        with self.assertRaises(ValueError):backups.cancel(self.data)
        with self.assertRaises(ValueError):backups.request_backup(self.data)
        (backups.area(self.data)/'operation.json').write_text('broken')
        self.assertTrue(backups.pending(self.data))
        with self.assertRaises(ValueError):backups.cancel(self.data)
        with self.assertRaises(RuntimeError):self.activate()
        self.assertTrue((operation/'journal.json').exists())

    def test_interrupted_creation_is_failed_after_restart_and_can_retry(self):
        result=backups.request_backup(self.data)
        result['status']='creating';backups.write(backups.area(self.data)/'operation.json',result)
        with self.assertRaises(ValueError):backups.cancel(self.data)
        self.activate()
        self.assertEqual(backups.read(self.data)['status'],'failed')
        self.assertFalse(backups.pending(self.data))
        self.assertTrue((self.data/'destination-only.json').exists())
        self.assertEqual(backups.request_backup(self.data)['status'],'waiting_for_restart')

    def test_legacy_pending_maps_to_guided_restart_and_failed_creation_can_retry(self):
        result=backups.request_backup(self.data);result['status']='pending'
        backups.write(backups.area(self.data)/'operation.json',result)
        self.assertEqual(backups.read(self.data)['status'],'waiting_for_restart')
        with patch.object(backups.engine,'backup',side_effect=OSError('synthetic storage failure')):self.activate()
        self.assertEqual(backups.read(self.data)['status'],'failed')
        self.assertFalse(backups.pending(self.data))
        self.assertTrue((self.data/'destination-only.json').exists())
        backups.request_backup(self.data);self.activate()
        self.assertEqual(backups.read(self.data)['status'],'ready')

    def test_scheduled_refresh_resumes_after_owned_pending_operation_is_cancelled(self):
        import asyncio
        from scheduler import Scheduler
        from unittest.mock import AsyncMock
        # Pending is checked before schedule evaluation or any loader work.
        loader=type('Loader',(),{'loading':False,'load':AsyncMock()})()
        job=Scheduler(loader)
        backups.request_backup(self.data)
        self.assertEqual(asyncio.run(job.tick()),'skipped')
        loader.load.assert_not_awaited()
        backups.cancel(self.data)
        self.assertEqual(asyncio.run(job.tick()),'idle')

    def test_schedule_exact_occurrence_claim_and_busy_skip(self):
        from datetime import datetime,timezone
        from types import SimpleNamespace
        import backup_schedule as schedule
        schedule.save(dict(enabled=True,time='06:00',timezone='UTC'),0,self.data)
        cursor=datetime(2026,1,1,5,59,tzinfo=timezone.utc);now=datetime(2026,1,1,6,0,tzinfo=timezone.utc)
        self.assertEqual(schedule.tick(now,cursor,SimpleNamespace(loading=False),self.data),'waiting_for_restart')
        identity=backups.read(self.data)['id']
        self.assertEqual(schedule.tick(now,cursor,SimpleNamespace(loading=False),self.data),'skipped')
        self.assertEqual(backups.read(self.data)['id'],identity)
        self.assertEqual(backups.read(self.data)['origin'],'scheduled')
        self.assertEqual(len(schedule.status(self.data)['attempts']),1)
        backups.cancel(self.data)
        tomorrow=now.replace(day=2)
        schedule.tick(tomorrow,cursor.replace(day=2),SimpleNamespace(loading=True),self.data)
        self.assertFalse(backups.pending(self.data))
        self.assertIn('skipped',schedule.settings(self.data)['last_outcome'])

    def test_schedule_validation_revision_timezone_and_disabled_defaults(self):
        import backup_schedule as schedule
        self.assertFalse(schedule.settings(self.data)['schedule']['enabled'])
        for draft in [dict(time='25:00'),dict(mode='cron',cron='* * * * *'),dict(timezone='Unknown/Nowhere'),dict(keep=0)]:
            with self.subTest(draft=draft),self.assertRaises(ValueError):schedule.save(draft,0,self.data)
        value=schedule.save(dict(enabled=True,mode='cron',cron='0 7 * * 1-5',timezone='Europe/Oslo'),0,self.data)
        self.assertEqual(len(value['next_runs']),5)
        with self.assertRaises(ValueError):schedule.save({},0,self.data)

    def test_verified_history_and_retention_never_remove_manual_archives(self):
        import backup_schedule as schedule
        schedule.save(dict(keep=2),0,self.data)
        manual=backups.request_backup(self.data);self.activate()
        for _ in range(3):backups.request_backup(self.data,origin='scheduled');self.activate()
        history=schedule.history(self.data)
        self.assertEqual(sum(row['verified'] for row in history['items']),3)
        self.assertTrue(backups.download(manual['id'],data=self.data).exists())
        self.assertGreater(history['storage_bytes'],0)
        self.assertEqual(sum(row['status']=='deleted' for row in history['items']),1)
        with self.assertRaises(ValueError):schedule.remove(manual['id'],False,self.data)
        schedule.remove(manual['id'],True,self.data)
        with self.assertRaises(ValueError):backups.download(manual['id'],data=self.data)

    def test_staged_restore_protects_matching_backup_from_deletion(self):
        import backup_schedule as schedule
        result=backups.request_backup(self.data);self.activate()
        with backups.uploaded(self.data) as (identity,path):
            path.write_bytes(backups.download(result['id'],data=self.data).read_bytes())
            backups.register_upload(identity,self.data)
        with self.assertRaises(ValueError):schedule.remove(result['id'],True,self.data)
        self.assertTrue(backups.download(result['id'],data=self.data).exists())

    def test_free_space_failure_keeps_data_and_records_failed_history(self):
        from types import SimpleNamespace
        import backup_schedule as schedule
        result=backups.request_backup(self.data)
        with patch.object(schedule.shutil,'disk_usage',return_value=SimpleNamespace(free=0)):self.activate()
        self.assertEqual(backups.read(self.data)['status'],'failed')
        self.assertTrue((self.data/'destination-only.json').exists())
        row=next(row for row in schedule.history(self.data)['items'] if row['id']==result['id'])
        self.assertEqual((row['status'],row['verified']),('failed',False))


    def test_missing_ready_archive_is_not_reported_as_success_and_corruption_blocks_download(self):
        result=backups.request_backup(self.data);self.activate()
        path=backups.download(result['id'],data=self.data)
        raw=path.read_bytes();path.write_bytes(b'corrupt')
        with self.assertRaises((ValueError,backups.tarfile.TarError)):backups.download(result['id'],data=self.data)
        from fastapi.testclient import TestClient
        from main import create_app
        client=TestClient(create_app(session_token='synthetic-backup-session'),base_url='http://127.0.0.1:18743')
        self.assertEqual(client.get('/api/backups/'+result['id']+'/download',headers={'X-SAP-Lens':'synthetic-backup-session'}).status_code,409)
        path.write_bytes(raw);path.unlink()
        self.assertEqual(backups.read(self.data)['status'],'failed')

    def test_invalid_backup_schedule_does_not_stop_independent_refresh_scheduler(self):
        import asyncio
        from scheduler import Scheduler
        from unittest.mock import AsyncMock
        from types import SimpleNamespace
        job=Scheduler(SimpleNamespace(loading=False))
        job.tick=AsyncMock(side_effect=asyncio.CancelledError)
        with patch('asyncio.to_thread',side_effect=ValueError('synthetic invalid backup schedule')):
            with self.assertRaises(asyncio.CancelledError):asyncio.run(job.loop())
        job.tick.assert_awaited_once()

    def test_discard_preview_releases_retention_protection_but_not_active_restore(self):
        import backup_schedule as schedule
        result=backups.request_backup(self.data);self.activate()
        with backups.uploaded(self.data) as (identity,path):
            path.write_bytes(backups.download(result['id'],data=self.data).read_bytes())
            backups.register_upload(identity,self.data)
        with self.assertRaises(ValueError):schedule.remove(result['id'],True,self.data)
        backups.discard_upload(identity,self.data)
        self.assertEqual(backups.read(self.data)['status'],'ready')
        self.assertTrue((self.data/'destination-only.json').exists())
        schedule.remove(result['id'],True,self.data)
        active=self.confirm()
        with self.assertRaises(ValueError):backups.discard_upload(active['id'],self.data)
        self.assertTrue(backups.pending(self.data))

    def test_internal_backup_lease_must_match(self):
        with self.assertRaises(ValueError): maintenance.backup(self.source,self.root/'no.tar.gz','desktop',VERSION,_lease=object())

    def test_cancel_pending_restore_does_not_modify_active_store(self):
        self.confirm();backups.cancel(self.data)
        self.assertFalse(backups.pending(self.data));self.assertTrue((self.data/'destination-only.json').exists())

    def test_invalid_operation_ids_and_missing_snapshot_references(self):
        for value in ('../escape','/etc/passwd','x'*32):
            with self.assertRaises(ValueError):backups.download(value,data=self.data)
        config_value=AppConfig();from config_models import SourceSnapshot
        config_value.data_lifecycle.sources['roles']=SourceSnapshot(snapshot='f'*64,path='role-catalogue.csv',imported_at='2026-01-01T00:00:00Z',checked_at='2026-01-01T00:00:00Z')
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
        backup=backups.request_backup(self.data);self.activate()
        for name,expected in [('reader',403),('admin',200)]:
            headers={'Authorization':'Basic '+base64.b64encode((name+':Synthetic-backup-password-123!').encode()).decode(),'X-SAP-Lens':'1'}
            self.assertEqual(client.get('/api/backups',headers=headers).status_code,expected)
            if name=='reader': self.assertEqual(client.get('/api/backups/'+backup['id']+'/download',headers=headers).status_code,403)
            else:
                response=client.get('/api/backups/'+backup['id']+'/download',headers=headers)
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.content,backups.download(backup['id'],data=self.data).read_bytes())
                self.assertIn('attachment',response.headers['content-disposition'])
            for endpoint in ('history','schedule'):
                self.assertEqual(client.get('/api/backups/'+endpoint,headers=headers).status_code,expected)

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
        self.assertFalse(backups.pending(self.data))

    def test_failed_rollback_blocks_startup_and_can_recover_on_next_start(self):
        result=self.confirm();original=os.replace
        def fail(source,target):
            if Path(source).name=='saved-filters.json' and '/stage/data/' in Path(source).as_posix() or '/old/' in Path(source).as_posix(): raise OSError('synthetic failure')
            return original(source,target)
        with patch.object(backups.os,'replace',side_effect=fail),self.assertRaises(RuntimeError): self.activate()
        self.assertTrue((backups.path_for(result['id'],self.data)/'journal.json').exists())
        self.activate()
        self.assertTrue((self.data/'destination-only.json').exists())
        self.assertEqual(backups.read(self.data)['status'],'failed')

    def functional_group_archive(self, name, mutate=None):
        import functional_groups as fg
        (self.source / 'functional-groups.json').unlink(missing_ok=True)
        with patch.object(fg, 'config_dir', return_value=self.source):
            gid = fg.create_group('Purchasing', 'Buys')['id']
            second = fg.create_group('Operations')['id']
            fg.add_membership('SYN_U1', gid, 'start', 0, 'Reviewer')
            fg.add_membership('SYN_U1', second, 'second function', 1, 'Reviewer')   # several memberships in one backup
            fg.flag_for_review('SYN_U1', 'chg1', 'Directory Department changed from A to B')
            fg.set_group_status(fg.create_group('Archived group')['id'], 'archived')
        if mutate: mutate(self.source / 'functional-groups.json')
        self.archive = self.root / 'exports' / name
        maintenance.backup(self.source, self.archive, 'desktop', VERSION)
        return self.source / 'functional-groups.json'

    def test_functional_groups_survive_backup_and_restore_byte_for_byte(self):
        original = self.functional_group_archive('groups.tar.gz').read_bytes()
        self.confirm(); self.activate()
        self.assertEqual((self.data / 'functional-groups.json').read_bytes(), original)
        import functional_groups as fg
        data = json.loads(original)
        user = next(iter(data['users'].values()))
        self.assertEqual((len(user['memberships']), user['revision'], {m['status'] for m in user['memberships'].values()}), (2, 3, {'Needs review'}))  # memberships, revision and open reviews survive
        self.assertEqual({m['review']['change_id'] for m in user['memberships'].values()}, {'chg1'})
        self.assertEqual([e['event'] for e in data['history']], ['assigned', 'assigned', 'review_required', 'review_required'])
        self.assertEqual({g['status'] for g in data['groups'].values()}, {'active', 'archived'})
        fg.validate_storage(data)

    def test_a_format_1_backup_is_validated_and_read_as_migrated_memberships(self):
        import functional_groups as fg
        stamp = fg.now()
        gid = 'fg_' + 'a' * 12
        legacy = dict(format=1, groups={gid: dict(id=gid, name='Old', description='', status='active', created=stamp, modified=stamp)}, rules=[], history=[],
                      users={fg.user_key('SYN_U1'): dict(username='SYN_U1', group_id=gid, status='Confirmed', revision=2, confirmed_at=stamp, confirmed_by='Rev', rationale='', updated_at=stamp, review=None, handled=[])})
        migrated = fg.validate_storage(legacy)
        self.assertEqual(list(migrated['users'][fg.user_key('SYN_U1')]['memberships']), [gid])

    def test_older_backup_without_functional_groups_restores_to_an_empty_catalogue(self):
        (self.data / 'functional-groups.json').write_text('{"format":1,"groups":{},"users":{},"history":[],"rules":[]}')
        self.confirm(); self.activate()
        self.assertFalse((self.data / 'functional-groups.json').exists())  # replace, not merge: nothing is invented
        import functional_groups as fg
        with patch.object(fg, 'config_dir', return_value=self.data):
            self.assertEqual(fg.read(), fg.empty())

    def test_corrupt_or_broken_functional_group_data_is_rejected_before_activation(self):
        def break_reference(path):
            data = json.loads(path.read_text()); next(iter(data['users'].values()))['memberships']['fg_ffffffffffff'] = dict(status='Confirmed', confirmed_at=None, confirmed_by='', rationale='', review=None, updated_at=None); path.write_text(json.dumps(data))
        for index, mutate in enumerate((break_reference, lambda path: path.write_text('{not json'))):
            self.functional_group_archive(f'broken{index}.tar.gz', mutate)
            with self.assertRaises((maintenance.MaintenanceError, ValueError)):  # structural errors and unparsable JSON are both refused
                self.preview()
            self.assertFalse((self.data / 'functional-groups.json').exists())

    def test_reference_library_is_preserved_by_existing_backup_restore(self):
        from sod_reference import Library
        library=Library(library_version='synthetic-custom',risks={'SYN':{'display_name':'Synthetic reference'}})
        raw=library.model_dump_json().encode()
        (self.source/'sod-reference.json').write_bytes(raw)
        other=self.root/'exports'/'reference.tar.gz'
        maintenance.backup(self.source,other,'desktop',VERSION)
        self.archive=other
        self.confirm();self.activate()
        self.assertEqual((self.data/'sod-reference.json').read_bytes(),raw)


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

class PendingStateReadTests(unittest.TestCase):
    def test_status_check_does_not_create_first_run_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder)/'not-created'
            self.assertFalse(backups.pending(data))
            self.assertFalse(data.exists())

    def test_configured_runtime_alias_reads_the_same_private_operation(self):
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder)/'data';data.mkdir();alias=Path(folder)/'alias'
            try:alias.symlink_to(data,target_is_directory=True)
            except OSError:self.skipTest('Creating directory aliases is unavailable.')
            result=backups.request_backup(data)
            self.assertEqual(backups.read(alias)['id'],result['id'])
            self.assertTrue(backups.pending(alias))
            from types import SimpleNamespace
            server=SimpleNamespace(accounts=str(alias/'custom-auth.json'),tls_cert='',tls_key='')
            self.assertIn('custom-auth.json',backups.protected(data,server))

class ReparseBoundaryTests(unittest.TestCase):
    def test_windows_reparse_attributes_are_rejected_without_following_the_entry(self):
        import stat
        from types import SimpleNamespace
        entry=SimpleNamespace(st_mode=stat.S_IFDIR,st_file_attributes=0x400)
        with patch.object(Path,'lstat',return_value=entry):
            self.assertTrue(maintenance.linked(Path('/synthetic-junction')))

    def test_inventory_rejects_a_reparse_directory_before_entering_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);redirect=root/'redirect';redirect.mkdir()
            with patch.object(maintenance,'linked',side_effect=lambda path:Path(path)==redirect):
                with self.assertRaises(ValueError):maintenance.inventory(root,'data')
