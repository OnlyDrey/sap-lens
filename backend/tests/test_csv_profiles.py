import csv
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cache,config
from config_models import AppConfig,ImportProfile
from main import create_app


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.environment=patch.dict(os.environ,{'SAP_LENS_CONFIG_DIR':str(self.root/'config'),'DATA_CSV_PATH':''})
        self.environment.start();config.get_settings.cache_clear();cache.clear_cache()

    def tearDown(self):
        self.environment.stop();config.get_settings.cache_clear();self.temp.cleanup()

    def test_nine_column_relationships_assignments_and_reordered_schema(self):
        file=self.root/'data.csv'
        file.write_text('TCODE,Effective_Role,PARENT_AGR,AGR_NAME,CHILD_AGR,FUNCTION_KEY,TEXT,CHILD_AGR_TEXT,TTEXT\nDEMO_T,DEMO_EFFECTIVE,DEMO_PARENT,DEMO_ROLE,DEMO_CHILD,FI,Synthetic role,Synthetic child,Synthetic transaction\n')
        state=cache.build_cache(str(file))
        role=state.roles['DEMO_ROLE'];source=role.single_roles[0].tcodes[0].assignment_sources[0]
        self.assertEqual(source.parent_agr,'DEMO_PARENT');self.assertEqual(source.effective_role,'DEMO_EFFECTIVE')
        self.assertEqual(role.relationships[0].child_agr,'DEMO_CHILD')
        self.assertEqual(state.import_report['transaction_assignments'],1)
        self.assertEqual(role.analysis['profile_id'],'legacy')

    def test_custom_mapping_delimiter_and_optional_warnings(self):
        file=self.root/'custom.csv';file.write_text('Role;Child;Transaction\nDEMO_ROOT;DEMO_CHILD;DEMO_T\n')
        profile=ImportProfile(id='mapped',name='Synthetic',delimiter=';',mapping={'AGR_NAME':'Role','CHILD_AGR':'Child','TCODE':'Transaction'})
        cfg=AppConfig(import_profiles=[profile],active_import='mapped',active_classification='generic')
        state=cache.build_cache(str(file),cfg)
        self.assertEqual(state.roles['DEMO_ROOT'].function_key,'UNCLASSIFIED')
        self.assertEqual(state.import_report['unique_roles'],1)
        self.assertTrue(state.import_report['warnings'])

    def test_utf16_quoted_values_duplicates_and_direct_assignments(self):
        file=self.root/'encoding.csv'
        file.write_text('AGR_NAME,TEXT,TCODE\nDEMO_ROLE,"Synthetic, description",DEMO_T\nDEMO_ROLE,"Synthetic, description",DEMO_T\n',encoding='utf-16')
        state=cache.build_cache(str(file))
        self.assertEqual(state.import_report['parsed_rows'],2)
        self.assertEqual(state.import_report['duplicate_rows'],1)
        self.assertEqual(state.roles['DEMO_ROLE'].tcode_count,1)
        self.assertEqual(state.roles['DEMO_ROLE'].single_roles[0].child_agr,'DEMO_ROLE')
        self.assertTrue(any('direct composite' in w for w in state.import_report['warnings']))

    def test_invalid_width_headers_and_missing_role_do_not_replace_cache(self):
        file=self.root/'bad.csv'
        for text in ['AGR_NAME,AGR_NAME\nA,B\n','AGR_NAME,TCODE\nA,B,C\n','AGR_NAME,TCODE\n,DEMO_T\n','TEXT\nSynthetic\n']:
            file.write_text(text)
            previous=cache.get_snapshot()
            with self.assertRaises(ValueError):cache.load_cache(str(file))
            self.assertIs(cache.get_snapshot(),previous)

    def test_alternate_descriptions_and_case_preserved_count_definitions(self):
        file=self.root/'alternates.csv'
        file.write_text('AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT\nDEMO_ROOT,First description,DEMO_CHILD,First child,DEMO_T,First transaction\nDEMO_ROOT,Second description,DEMO_CHILD,Second child,DEMO_T,Second transaction\nDEMO_ROOT,First description,DEMO_CHILD,First child,demo_t,Lowercase transaction\n')
        state=cache.build_cache(str(file));role=state.roles['DEMO_ROOT']
        self.assertEqual(role.alternate_descriptions,['Second description'])
        self.assertEqual(role.single_roles[0].alternate_descriptions,['Second child'])
        self.assertEqual(role.single_roles[0].tcodes[0].alternate_texts,['Second transaction'])
        self.assertEqual(state.import_report['unique_transactions'],2)
        self.assertEqual(role.tcode_count,2)
        self.assertEqual(len(state.tcode_index),1)

    def test_cancel_stalled_read_allows_new_file_without_stale_publication(self):
        import threading,time
        slow=self.root/'slow.csv';slow.write_text('AGR_NAME\nDEMO_SLOW\n')
        good=self.root/'good.csv';good.write_text('AGR_NAME,TCODE\nDEMO_GOOD,DEMO_T\n')
        started,release,finished=threading.Event(),threading.Event(),threading.Event()
        original=cache.build_cache
        def build(path=None,configuration=None):
            if path==str(slow) or (path is None and config.get_settings().data_csv_path==str(slow)):
                started.set();release.wait(5)
                result=original(str(slow),configuration)
                finished.set();return result
            return original(path,configuration)
        with patch.dict(os.environ,{'DATA_CSV_PATH':str(slow)}):
            config.get_settings.cache_clear()
            with patch('cache.build_cache',side_effect=build):
                try:
                    with TestClient(create_app(),base_url='http://127.0.0.1:18743') as client:
                        self.assertTrue(started.wait(1))
                        self.assertEqual(client.post('/api/data/cancel',headers={'X-SAP-Lens':'1'}).status_code,200)
                        self.assertEqual(client.post('/api/settings',json={'data_csv_path':str(good)},headers={'X-SAP-Lens':'1'}).status_code,200)
                        release.set();self.assertTrue(finished.wait(1))
                        time.sleep(0.02)
                        self.assertEqual(set(cache.get_snapshot().roles),{'DEMO_GOOD'})
                        self.assertEqual(config.get_settings().data_csv_path,str(good))
                finally:release.set()

    def test_preview_is_readonly_and_header_detection_precedes_mapping(self):
        file=self.root/'custom.csv';file.write_text('Role;Transaction\nDEMO_ROLE;DEMO_T\n')
        headers={'X-SAP-Lens':'1'}
        with TestClient(create_app(),base_url='http://127.0.0.1:18743') as client:
            response=client.post('/api/import/headers',json={'data_csv_path':str(file)},headers=headers)
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['detected_columns'],['Role','Transaction'])
            profile=ImportProfile(id='map',name='Map',mapping={'AGR_NAME':'Role','TCODE':'Transaction'})
            response=client.post('/api/import/preview',json={'data_csv_path':str(file),'profile':profile.model_dump()},headers=headers)
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['unique_roles'],1)
            self.assertEqual(cache.get_snapshot().roles,{})
            self.assertFalse((self.root/'config'/'settings.json').exists())

    def test_profile_change_rebuilds_without_losing_graph_and_versions_analysis(self):
        file=self.root/'source.csv';file.write_text('AGR_NAME,FUNCTION_KEY,CHILD_AGR,PARENT_AGR,Effective_Role,TCODE\nDEMO_ROOT,UNKNOWN,DEMO_CHILD,DEMO_PARENT,DEMO_EFFECTIVE,DEMO_T\n')
        headers={'X-SAP-Lens':'1'}
        with TestClient(create_app(),base_url='http://127.0.0.1:18743') as client:
            self.assertEqual(client.post('/api/settings',json={'data_csv_path':str(file)},headers=headers).status_code,200)
            previous=cache.get_snapshot().roles['DEMO_ROOT']
            cfg=client.get('/api/configuration').json()['settings'];cfg['active_classification']='generic'
            cfg['import_profiles'][0]['name']='Renamed synthetic profile'
            result=client.post('/api/configuration',json=cfg,headers=headers)
            self.assertEqual(result.status_code,200,result.text)
            role=cache.get_snapshot().roles['DEMO_ROOT']
            self.assertEqual(role.function_key,'UNCLASSIFIED')
            self.assertEqual(role.relationships,previous.relationships)
            self.assertEqual(role.single_roles[0].tcodes,previous.single_roles[0].tcodes)
            self.assertEqual(role.analysis['import_profile_version'],2)
            self.assertEqual(role.analysis['configuration_revision'],result.json()['settings']['revision'])


if __name__=='__main__':unittest.main()
