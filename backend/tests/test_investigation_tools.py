"""Synthetic comparison/coverage and restart-safe saved investigation contracts."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
import cache
import config
from main import create_app
from routers import data_health
from user_access import build_users
from config_models import UserImportProfile

H={'X-SAP-Lens':'investigation-test'}
CAT='FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,TCODE\nFI,ZC:SHARED:*,Shared viewer,ZS:SHARED,FB03\nMM,ZC:ONLY_A,Materials,ZS:A,ME23N\nMM,ZC:ONLY_A,Materials,ZS:A,FB03\nFI,ZC:NO_CODES,,ZS:EMPTY,\n'
ROWS='''USERNAME,ROLE_NAME,USER_GROUP,FIRST_NAME,LAST_NAME,EMAIL,USER_VALID_FROM,USER_VALID_TO,USER_LOCKED,USER_TYPE,ROLE_VALID_FROM,ROLE_VALID_TO
DEMO_A,ZC:SHARED:ENP,DEMO,Alpha,Example,a@example.test,20000101,99991231,0,A,20000101,99991231
DEMO_A,ZC:SHARED:ENP,DEMO,Alpha,Example,a@example.test,20000101,99991231,0,A,20010101,99991231
DEMO_A,ZC:ONLY_A,DEMO,Alpha,Example,a@example.test,20000101,99991231,0,A,20000101,99991231
DEMO_A,ZC:HIST,DEMO,Alpha,Example,a@example.test,20000101,99991231,0,A,20000101,20010101
DEMO_A,ZC:FUTURE,DEMO,Alpha,Example,a@example.test,20000101,99991231,0,A,29990101,99991231
DEMO_A,ZC:UNKNOWN,DEMO,Alpha,Example,a@example.test,20000101,99991231,0,A,,
DEMO_B,ZC:SHARED:ENP,DEMO,Beta,Example,b@example.test,20000101,99991231,0,A,20000101,99991231
DEMO_B,ZO:UNKNOWN,DEMO,Beta,Example,b@example.test,20000101,99991231,0,A,20000101,99991231
DEMO_EMPTY,,DEMO,Empty,Example,,20000101,99991231,,Z,,
'''

class InvestigationTools(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'SAP_LENS_CONFIG_DIR':str(self.root/'private'),'DATA_CSV_PATH':''});self.env.start()
        config.get_settings.cache_clear();cache.clear_cache()
        self.catalogue=self.root/'catalogue.csv';self.catalogue.write_text(CAT)
        self.users=self.root/'users.csv';self.users.write_text(ROWS)
        s=config.get_settings().model_copy(deep=True);s.data_csv_path=str(self.catalogue);s.user_csv_path=str(self.users);config.save_configuration(s,s.revision);cache.load_cache()
        self.client=TestClient(create_app(session_token='investigation-test'),base_url='http://127.0.0.1:18743')
    def tearDown(self):
        cache.clear_cache();config.get_settings.cache_clear();self.env.stop();self.temp.cleanup()
    def get(self,path,**params):
        r=self.client.get(path,params=params,headers=H);self.assertEqual(r.status_code,200,r.text);return r.json()
    def compare(self,**params): return self.get('/api/user-comparison',user_a='demo_a',user_b='DEMO_B',**params)
    def test_role_differences_retain_distinct_intervals(self):
        r=self.compare();rows={i['identifier']:i for i in r['items']}
        self.assertEqual(r['summary']['roles'],dict(shared=1,a=1,b=1))
        self.assertEqual(len(rows['ZC:SHARED:ENP']['a']),2)
        self.assertEqual(rows['ZC:ONLY_A']['difference'],'a')
        self.assertEqual(rows['ZO:UNKNOWN']['difference'],'b')
        self.assertEqual(rows['ZC:SHARED:ENP']['a'][0]['catalogue_roles'],['ZC:SHARED:*'])
    def test_transactions_keep_all_explanatory_roles(self):
        r=self.compare(kind='transactions');rows={i['identifier']:i for i in r['items']}
        self.assertEqual(rows['FB03']['difference'],'shared');self.assertEqual(set(rows['FB03']['a']),{'ZC:SHARED:ENP','ZC:ONLY_A'})
        self.assertEqual(rows['ME23N']['difference'],'a')
        evidence=r['assignment_evidence']['a']['ZC:SHARED:ENP']
        self.assertEqual(evidence['total'],2)
        self.assertEqual([a['valid_from'] for a in evidence['items']],['2000-01-01','2001-01-01'])
        self.assertEqual(evidence['items'][0]['match_status'],'wildcard')
        self.assertEqual(evidence['items'][0]['user_group'],'DEMO')
        paged=self.get('/api/user-comparison/evidence',user_a='DEMO_A',user_b='DEMO_B',kind='transactions',identifier='FB03',side='a',limit=1)
        self.assertEqual(set(paged['assignment_evidence']),set(paged['items']))
        self.assertEqual(r['summary']['transactions'],dict(shared=1,a=1,b=0))
    def test_comparison_sorting_is_stable_and_does_not_change_evidence(self):
        original=self.compare()
        sorted_rows=self.compare(sort='a',descending=True,limit=1)
        self.assertEqual(sorted_rows['items'][0]['identifier'],'ZC:SHARED:ENP')
        self.assertEqual(sorted_rows['items'][0]['a_total'],2)
        self.assertEqual(sorted_rows['summary'],original['summary'])
        identifiers=[]
        for offset in range(original['total']):
            identifiers.append(self.compare(sort='difference',descending=True,offset=offset,limit=1)['items'][0]['identifier'])
        self.assertEqual(len(identifiers),len(set(identifiers)))
        self.assertEqual(set(identifiers),{row['identifier'] for row in original['items']})
    def test_validity_filters_not_historical_current_access(self):
        self.assertEqual(self.compare(validity='expired')['items'][0]['identifier'],'ZC:HIST')
        self.assertEqual(self.compare(validity='future')['items'][0]['identifier'],'ZC:FUTURE')
        self.assertEqual(self.compare(validity='unknown')['items'][0]['identifier'],'ZC:UNKNOWN')
        self.assertEqual(self.compare(validity='all')['total'],6)
    def test_search_area_difference_and_pagination(self):
        r=self.compare(difference='a',area='Materials Management',search='ONLY')
        # Use actual module labels rather than assume a translated SAP name.
        area=self.compare()['areas'][0]
        self.assertTrue(all(area in i['areas'] for i in self.compare(area=area)['items']))
        self.assertEqual(self.compare(difference='a',search='ONLY')['total'],1)
        first=self.compare(limit=1);second=self.compare(offset=1,limit=1)
        self.assertEqual(first['total'],3);self.assertNotEqual(first['items'][0]['identifier'],second['items'][0]['identifier'])
    def test_unknown_same_and_disabled_users_rejected(self):
        for b,status in [('DEMO_A',422),('NO_USER',404)]:
            self.assertEqual(self.client.get('/api/user-comparison',params=dict(user_a='demo_a',user_b=b),headers=H).status_code,status)
        s=config.get_settings().model_copy(deep=True);s.features.user_role_mapping=False;config.save_configuration(s,s.revision)
        self.assertEqual(self.client.get('/api/user-comparison',params=dict(user_a='DEMO_A',user_b='DEMO_B'),headers=H).status_code,409)
    def test_empty_user_and_missing_catalogue_are_not_effective_access_claims(self):
        r=self.get('/api/user-comparison',user_a='DEMO_EMPTY',user_b='DEMO_B');self.assertEqual(r['summary']['roles']['shared'],0)
        s=config.get_settings().model_copy(deep=True);s.data_csv_path='';config.save_configuration(s,s.revision);cache.load_cache()
        r=self.compare(kind='transactions');self.assertFalse(r['catalogue_available']);self.assertEqual(r['total'],0)
    def test_refresh_recalculates_comparison_and_health(self):
        old=self.compare()['data_revision'];health=self.get('/api/data-health')
        self.users.write_text(ROWS.replace('ZC:ONLY_A','ZC:NEW_UNMAPPED'));cache.load_cache()
        self.assertNotEqual(self.compare()['data_revision'],old)
        new=self.get('/api/data-health');self.assertNotEqual(new['data_revision'],health['data_revision'])
        self.assertGreater(next(i['count'] for i in new['findings'] if i['id']=='unmapped'),next(i['count'] for i in health['findings'] if i['id']=='unmapped'))
    def test_health_coverage_defines_record_denominator_and_drilldown(self):
        r=self.get('/api/data-health');coverage=r['coverage'][0]
        self.assertEqual((coverage['numerator'],coverage['denominator']),(4,8));self.assertEqual(coverage['percent'],50)
        detail=self.get('/api/data-health',finding='unmapped',limit=1);self.assertEqual(detail['total'],4);self.assertEqual(len(detail['items']),1)
        self.assertEqual(detail['items'][0]['destination'],'user')
        self.assertNotIn(str(self.root),json.dumps(r));self.assertNotIn('a@example.test',json.dumps(r))
    def test_health_import_deduplication_not_duplicate_definitions(self):
        self.users.write_text(ROWS+ROWS.splitlines()[1]+'\n');cache.load_cache()
        r=self.get('/api/data-health');self.assertEqual(r['import_totals']['users']['duplicate_rows'],1)
        self.assertEqual(r['coverage'][0]['denominator'],8)
    def test_health_unknown_types_missing_mappings_and_lifecycle_severity(self):
        f={i['id']:i for i in self.get('/api/data-health')['findings']}
        self.assertEqual(f['expired']['severity'],'information');self.assertEqual(f['expired']['count'],1)
        self.assertEqual(f['unknown_type']['count'],1);self.assertEqual(f['no_transactions']['count'],1)
    def test_health_cache_avoids_repeat_snapshot_scan(self):
        self.get('/api/data-health')
        with patch.object(data_health,'calculations',side_effect=AssertionError('recomputed')): self.get('/api/data-health')
    def test_failed_refresh_preserves_published_coverage(self):
        old=self.get('/api/data-health')['coverage'];self.users.write_text(ROWS.replace('20000101,99991231,0,A','99991231,20000101,0,A'))
        with self.assertRaises(Exception):cache.load_cache()
        self.assertEqual(self.get('/api/data-health')['coverage'],old)
    def test_large_evidence_is_paged_without_losing_intervals(self):
        rows=ROWS
        for year in range(2002,2032): rows+=f'DEMO_A,ZC:SHARED:ENP,DEMO,Alpha,Example,a@example.test,20000101,99991231,0,A,{year}0101,99991231\n'
        self.users.write_text(rows);cache.load_cache()
        result=self.compare(validity='all');row=next(r for r in result['items'] if r['identifier']=='ZC:SHARED:ENP')
        self.assertEqual(len(row['a']),25);self.assertEqual(row['a_total'],32)
        evidence=self.get('/api/user-comparison/evidence',user_a='DEMO_A',user_b='DEMO_B',identifier='ZC:SHARED:ENP',side='a',validity='all',offset=25)
        self.assertEqual(evidence['total'],32);self.assertEqual(len(evidence['items']),7)
        self.assertEqual(evidence['data_revision'],result['data_revision'])
    def test_comparison_cache_reuses_only_current_pair_and_generation(self):
        from routers import user_comparison
        self.compare()
        with patch.object(user_comparison,'_compare',side_effect=AssertionError('recomputed')):self.compare(kind='transactions')
    def test_saved_failed_write_preserves_original(self):
        self.client.post('/api/saved-filters',headers=H,json=dict(name='Original',view='users',filters={}))
        path=config.config_dir()/'saved-filters.json';before=path.read_bytes()
        with patch('saved_filters.atomic_write',side_effect=OSError('failure')):
            response=self.client.post('/api/saved-filters',headers=H,json=dict(name='New',view='users',filters={}))
        self.assertEqual(response.status_code,409);self.assertEqual(path.read_bytes(),before)

    def test_saved_crud_conflicts_and_independent_views(self):
        def save(**kw):return self.client.post('/api/saved-filters',headers=H,json=dict(name='Daily',view='users',filters={'search':'Demo'},**kw))
        r=save();self.assertEqual(r.status_code,200);item=r.json()
        self.assertEqual(save().status_code,409)
        other=self.client.post('/api/saved-filters',headers=H,json=dict(name='Daily',view='review',filters={'finding':'stale'}));self.assertEqual(other.status_code,200)
        updated=self.client.post('/api/saved-filters',headers=H,json={**{k:item[k] for k in ('id','name','view','filters')},'expected':item['modified']});self.assertEqual(updated.status_code,200)
        self.assertEqual(save(id=item['id'],expected=item['modified']).status_code,409)
        now=updated.json();renamed=self.client.post('/api/saved-filters',headers=H,json=dict(id=now['id'],name='Renamed',view='users',filters={},expected=now['modified'],rename=True));self.assertEqual(renamed.status_code,200);self.assertEqual(renamed.json()['filters'],{'search':'Demo'})
        self.assertEqual(self.client.post('/api/saved-filters/delete',headers=H,json=dict(id=now['id'],expected=renamed.json()['modified'])).status_code,200)
        self.assertEqual(len(self.get('/api/saved-filters')['items']),1)
    def test_saved_definitions_survive_fresh_python_process(self):
        self.client.post('/api/saved-filters',headers=H,json=dict(name='Daily',view='users',filters={'search':'Demo'}))
        out=subprocess.check_output([sys.executable,'-c','import saved_filters;print(saved_filters.read()[0]["name"])'],cwd=Path(__file__).resolve().parents[1],env=os.environ.copy(),text=True)
        self.assertEqual(out.strip(),'Daily')
    def test_corrupt_filters_retained_and_unknown_schema_preserved(self):
        p=config.config_dir()/'saved-filters.json';p.write_text('broken')
        self.assertEqual(self.client.get('/api/saved-filters',headers=H).status_code,409);self.assertEqual(p.read_text(),'broken')
        item=dict(id='future',name='Future',view='users',filters={'unsupported':'value'},filter_schema=9,created='2026-01-01',modified='2026-01-01')
        p.write_text(json.dumps(dict(schema_version=1,items=[item])))
        self.assertEqual(self.get('/api/saved-filters')['items'][0],item)
        r=self.client.post('/api/saved-filters',headers=H,json=dict(id='future',name='Future renamed',view='users',filters={},expected=item['modified'],rename=True));self.assertEqual(r.status_code,200);self.assertEqual(r.json()['filter_schema'],9)
    def test_saved_payload_and_session_bounds(self):
        for filters in ({'dataset':[{'name':'private'}]},{'search':'x'*513},{'search':None},{'anything':'value'}):
            self.assertEqual(self.client.post('/api/saved-filters',headers=H,json=dict(name='Name',view='users',filters=filters)).status_code,422)
        self.assertEqual(self.client.post('/api/saved-filters',json=dict(name='Name',view='users',filters={})).status_code,403)
        self.assertEqual(self.client.get('/api/data-health').status_code,403)
    def test_optional_disabled_sources_are_not_errors(self):
        s=config.get_settings().model_copy(deep=True);s.features.user_role_mapping=False;config.save_configuration(s,s.revision)
        r=self.get('/api/data-health');self.assertIsNone(r['coverage'][0]['numerator']);self.assertFalse(r['sources'][1]['enabled'])
        self.assertTrue(all(f['count'] is None for f in r['findings'] if f['id']=='unmapped'))

if __name__=='__main__':unittest.main()
