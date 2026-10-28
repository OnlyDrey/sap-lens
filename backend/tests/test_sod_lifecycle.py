"""Synthetic fourth-source replacement, persistence and boundary regression tests."""
import csv
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cache
import config
from config_models import AppConfig
from csv_lifecycle import load, diff_records
from employee_directory import store
from portable_config import export_configuration, PortableConfig, read_portable

HEADERS = ['RISK','CRITICITY','TYPE','TEXT','ACTVT1','ACTVT2','ACTIVITY_SLOT','ACTIVITY','TCODE','TTEXT']


class SodLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(self.root/'config'), 'DATA_CSV_PATH': ''})
        self.env.start(); config.get_settings.cache_clear(); cache.clear_cache(); store.clear()
        self.path = self.root/'matrix.csv'
        self.write()

    def tearDown(self):
        cache.clear_cache(); store.clear(); config.get_settings.cache_clear(); self.env.stop(); self.temp.cleanup()

    def write(self, risk='SYN01', second='SYN_B'):
        with self.path.open('w',encoding='utf-8',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=HEADERS);writer.writeheader()
            for slot,activity,code in [('ACTVT1','SYN_A','SYN01'),('ACTVT2',second,'SYN02')]:
                writer.writerow(dict(RISK=risk,CRITICITY='H',TYPE='S',TEXT='Synthetic two-sided review',ACTVT1='SYN_A',ACTVT2=second,ACTIVITY_SLOT=slot,ACTIVITY=activity,TCODE=code,TTEXT='Synthetic transaction'))

    def settings(self, mode='static'):
        settings=config.get_settings().model_copy(deep=True)
        settings.sod_csv_path=str(self.path);settings.source_modes.sod=mode;settings.features.sod=True
        return settings

    def activate(self,mode='static'):
        return load(self.settings(mode),operation='import',strict=True,force=('sod',))

    def test_automatic_import_commits_records_and_source_metadata(self):
        result=self.activate()
        row=next(row for row in result['sources'] if row['source']=='sod')
        self.assertEqual((row['status'],row['records'],row['added']),('updated',2,2))
        self.assertEqual(cache.get_snapshot().sod['risks'][0]['risk_id'],'SYN01')
        self.assertIn('sod',config.get_settings().data_lifecycle.sources)
        self.assertEqual(len(config.get_settings().data_lifecycle.sod_history),1)

    def test_static_restart_does_not_require_original_file(self):
        self.activate();identity=config.get_settings().data_lifecycle.sources['sod'].snapshot
        self.path.unlink();cache.clear_cache();config.get_settings.cache_clear()
        result=load(operation='startup')
        self.assertEqual(result['failed'],0)
        self.assertIsNone(cache.get_snapshot().last_loaded)
        self.assertEqual(cache.get_snapshot().sod['risks'][0]['risk_id'],'SYN01')
        self.assertEqual(config.get_settings().data_lifecycle.sources['sod'].snapshot,identity)

    def test_dynamic_full_replacement_removes_previous_risks(self):
        self.activate('dynamic');self.write('SYN02')
        result=load();row=next(row for row in result['sources'] if row['source']=='sod')
        self.assertEqual((row['added'],row['removed']),(2,2))
        self.assertEqual([r['risk_id'] for r in cache.get_snapshot().sod['risks']],['SYN02'])

    def test_failed_import_preserves_settings_and_last_valid_generation(self):
        self.activate();previous=cache.get_snapshot();saved=config.get_settings().model_dump()
        self.path.write_text('WRONG\ninvalid\n')
        with self.assertRaises(ValueError):self.activate()
        self.assertIs(cache.get_snapshot(),previous)
        self.assertEqual(config.get_settings().model_dump(),saved)

    def test_failed_refresh_preserves_sod_and_reports_failure(self):
        self.activate('dynamic');previous=cache.get_snapshot().sod;self.path.unlink()
        result=load();row=next(row for row in result['sources'] if row['source']=='sod')
        self.assertEqual(row['status'],'failed');self.assertTrue(row['previous_preserved'])
        self.assertIs(cache.get_snapshot().sod,previous)

    def test_catalogue_replacement_and_clear_preserve_sod(self):
        self.activate();before=cache.get_snapshot().sod
        roles=self.root/'roles.csv';roles.write_text('AGR_NAME,TCODE\nZC:SYN,SYN01\n')
        settings=config.get_settings().model_copy(deep=True);settings.data_csv_path=str(roles)
        load(settings,operation='import',strict=True,force=('roles',))
        self.assertIs(cache.get_snapshot().sod,before)
        settings=config.get_settings().model_copy(deep=True);settings.data_csv_path=''
        load(settings,operation='import',strict=True)
        self.assertIs(cache.get_snapshot().sod,before)

    def test_clear_sod_does_not_clear_core_catalogue(self):
        self.activate();settings=config.get_settings().model_copy(deep=True);settings.sod_csv_path=''
        load(settings,operation='import',strict=True)
        self.assertFalse(cache.get_snapshot().sod)
        self.assertNotIn('sod',config.get_settings().data_lifecycle.sources)

    def test_unconfigured_sod_preserves_existing_three_source_report_contract(self):
        result=load()
        self.assertEqual(len(result['sources']),3);self.assertEqual(result['skipped'],3)

    def test_portable_export_never_exposes_sod_path_or_snapshot(self):
        self.activate()
        exported=export_configuration(config.get_settings(),include_private=True)
        self.assertEqual(exported['settings']['sod_csv_path'],'')
        self.assertEqual(exported['settings']['data_lifecycle']['sources'],{})
        bad=PortableConfig(settings=AppConfig(sod_csv_path=str(self.path)))
        with self.assertRaises(ValueError):read_portable(bad,'')

    def test_static_global_refresh_does_not_read_changed_source(self):
        self.activate();self.write('SYN02');result=load()
        self.assertEqual(next(row for row in result['sources'] if row['source']=='sod')['reason'],'static')
        self.assertEqual(cache.get_snapshot().sod['risks'][0]['risk_id'],'SYN01')

    def test_settings_cas_failure_never_publishes_staged_sod(self):
        self.activate('dynamic');before=cache.get_snapshot();self.write('SYN02')
        with patch('csv_lifecycle.save_configuration',side_effect=PermissionError('synthetic denial')):result=load()
        self.assertEqual(result['status'],'failed');self.assertIs(cache.get_snapshot(),before)
        self.assertTrue(next(row for row in result['sources'] if row['source']=='sod')['previous_preserved'])

    def test_changes_keep_activity_slot_and_transaction_identity(self):
        before=[dict(RISK='SYN01',ACTIVITY_SLOT='ACTVT1',ACTIVITY='SYN_A',TCODE='SYN01',TEXT='Before')]
        after=[{**before[0],'TEXT':'After'}]
        result=diff_records('sod',before,after)
        self.assertEqual((result['modified'],result['added'],result['removed']),(1,0,0))
        self.assertEqual(result['changes'][0]['fields'][0]['field'],'TEXT')

    def test_source_history_retains_removed_risk_definitions_and_clear(self):
        from csv_lifecycle import read_private
        self.activate('dynamic');self.write('SYN02');load()
        history=config.get_settings().data_lifecycle.sod_history
        self.assertEqual(len(history),2)
        first=read_private('snapshots',history[0].snapshot)
        self.assertEqual(first['records'][0]['RISK'],'SYN01')
        settings=config.get_settings().model_copy(deep=True);settings.sod_csv_path=''
        load(settings,operation='import',strict=True)
        self.assertEqual(len(config.get_settings().data_lifecycle.sod_history),2)

    def test_history_capacity_failure_preserves_previous_source(self):
        self.activate('dynamic')
        settings=config.get_settings().model_copy(deep=True)
        settings.data_lifecycle.sod_history = settings.data_lifecycle.sod_history * 1000
        config.save_configuration(settings,settings.revision)
        previous=cache.get_snapshot().sod;previous_ref=config.get_settings().data_lifecycle.sources['sod'].snapshot;self.write('SYN02')
        result=load()
        self.assertEqual(next(row for row in result['sources'] if row['source']=='sod')['status'],'failed')
        self.assertIs(cache.get_snapshot().sod,previous)
        self.assertEqual(config.get_settings().data_lifecycle.sources['sod'].snapshot,previous_ref)

    def test_selection_and_preview_reuse_existing_authenticated_source_routes(self):
        from fastapi.testclient import TestClient
        from main import create_app
        headers={'X-SAP-Lens':'synthetic-sod-session'}
        with TestClient(create_app(session_token=headers['X-SAP-Lens']),base_url='http://127.0.0.1:18743') as client:
            body=dict(path=str(self.path),revision=config.get_settings().revision,mode='static')
            self.assertEqual(client.post('/api/data-sources/sod/select',json=body).status_code,403)
            response=client.post('/api/data-sources/sod/select',json=body,headers=headers)
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['records'],2)
            preview=client.get('/api/data-sources/sod/preview',headers=headers).json()
            self.assertTrue(preview['loaded']);self.assertEqual(preview['columns'],HEADERS)
            self.assertEqual(preview['total'],2)
            response=client.post('/api/data-sources/sod/select',json={**body,'revision':config.get_settings().revision,'profile':{}},headers=headers)
            self.assertEqual(response.status_code,400)

    def test_browser_upload_soD_remains_static_and_referenced_upload_is_retained(self):
        from fastapi.testclient import TestClient
        from main import create_app
        from deployment import ServerSettings
        data=self.root/'server'
        environment={'SAP_LENS_DEPLOYMENT_MODE':'server','SAP_LENS_DATA_DIR':str(data),'SAP_LENS_CONFIG_DIR':str(data),'SAP_LENS_SOURCE_DIR':str(self.root/'sources'),'SAP_LENS_HOST':'127.0.0.1','SAP_LENS_PORT':'18743','SAP_LENS_PUBLIC_ORIGIN':'http://127.0.0.1:18743','SAP_LENS_ALLOWED_HOSTS':'127.0.0.1','SAP_LENS_AUTH':'local'}
        with patch.dict(os.environ,environment):
            config.get_settings.cache_clear()
            client=TestClient(create_app(server=ServerSettings.from_env()),base_url='http://127.0.0.1:18743',client=('127.0.0.1',50000))
            headers={'X-SAP-Lens':'1','X-Upload-Filename':'synthetic.csv'}
            upload=client.post('/api/server/uploads/sod',content=self.path.read_bytes(),headers=headers)
            self.assertEqual(upload.status_code,200,upload.text)
            path=upload.json()['path']
            body=dict(path=path,revision=config.get_settings().revision,mode='dynamic')
            self.assertEqual(client.post('/api/data-sources/sod/select',json=body,headers=headers).status_code,400)
            body['mode']='static'
            response=client.post('/api/data-sources/sod/select',json=body,headers=headers)
            self.assertEqual(response.status_code,200,response.text)
            for _ in range(4):
                client.post('/api/server/uploads/roles',content=b'AGR_NAME,TCODE\nZC:SYN,SYN01\n',headers=headers)
            self.assertTrue(Path(path).exists())
            self.assertEqual(client.post('/api/server/uploads/sod',content=b'bad',headers={**headers,'X-Upload-Filename':'../private.csv'}).status_code,400)

    def test_sod_restore_does_not_relabel_sap_generation_timestamp(self):
        from csv_lifecycle import restore
        from datetime import datetime, timezone
        roles=self.root/'roles.csv';roles.write_text('AGR_NAME,TCODE\nZC:SYN,SYN01\n')
        settings=self.settings();settings.data_csv_path=str(roles)
        load(settings,operation='import',strict=True,force=('roles','sod'))
        settings=config.get_settings().model_copy(deep=True)
        settings.data_lifecycle.sources['roles'].imported_at='2020-01-01T00:00:00+00:00'
        settings.data_lifecycle.sources['sod'].imported_at='2026-01-01T00:00:00+00:00'
        state=restore(settings)
        self.assertEqual(state.last_loaded,datetime(2020,1,1,tzinfo=timezone.utc))

    def test_identical_force_selection_does_not_duplicate_source_history(self):
        self.activate();self.activate()
        self.assertEqual(len(config.get_settings().data_lifecycle.sod_history),1)

    def test_risk_change_summary_separates_definition_changes(self):
        from csv_lifecycle import sod_risk_changes
        old=dict(risk_id='SYN01',criticality='H',risk_type='S',source_text='Before',activity1='A',activity2='B',activities={'ACTVT1':[],'ACTVT2':[]})
        new={**old,'criticality':'C','source_text':'After','activity2':'C','activities':{'ACTVT1':[dict(activity='A',tcode='SYN01',ttext='Synthetic')],'ACTVT2':[]}}
        summary=sod_risk_changes([old,{**old,'risk_id':'SYN02'}],[new,{**old,'risk_id':'SYN03'}])
        self.assertEqual(summary['added_risks']['risk_ids'],['SYN03'])
        self.assertEqual(summary['removed_risks']['risk_ids'],['SYN02'])
        for key in ['changed_risks','changed_criticality','changed_source_descriptions','changed_activities','changed_transaction_mappings']:
            self.assertEqual(summary[key],dict(total=1,risk_ids=['SYN01'],truncated=False))
        self.assertEqual(sod_risk_changes([old],[old])['changed_risks']['total'],0)
        added=sod_risk_changes([],[{**old,'risk_id':f'SYN{x:03d}'} for x in range(105)])['added_risks']
        self.assertEqual(added['total'],105);self.assertEqual(len(added['risk_ids']),100);self.assertTrue(added['truncated'])

    def test_direct_cache_builder_sod_only_does_not_claim_sap_refresh(self):
        state=cache.build_cache(configuration=self.settings())
        self.assertTrue(state.sod);self.assertIsNone(state.last_loaded)
