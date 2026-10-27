"""Synthetic captured-generation SoD filtering, evidence and complete CSV contracts."""
import copy
import csv
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI
from fastapi.testclient import TestClient
import cache
import config
from config_models import SourceSnapshot
from models import RoleDetail, SingleRole, TCode
from sod_import import build_sod
import sod_catalogue as store
from routers.sod_analysis import router, COLUMNS
from user_access import UserState


def role(name, *codes):
    return RoleDetail(agr_name=name,tcode_count=len(codes),single_roles=[SingleRole(child_agr='SINGLE_'+name,tcodes=[TCode(tcode=code) for code in codes])])


def assignment(name, start='2020-01-01', end='9999-12-31', group='SYNTHETIC'):
    return dict(role_name=name,catalogue_roles=[name],match_status='exact',valid_from=start,valid_to=end,user_group=group)


def synthetic_snapshot():
    base=dict(RISK='SYN01',CRITICITY='H',TYPE='S',TEXT='Synthetic potential conflict',ACTVT1='A',ACTVT2='B',TTEXT='Synthetic')
    sod=build_sod([dict(base,ACTIVITY_SLOT='ACTVT1',ACTIVITY='A',TCODE='X1'),dict(base,ACTIVITY_SLOT='ACTVT2',ACTIVITY='B',TCODE='X2')])
    user=dict(assignments=[assignment('ROLE_A'),assignment('ROLE_B')],accounts=[dict(valid_from='2020-01-01',valid_to='9999-12-31',locked=True)],emails={'synthetic@example.test'})
    return cache._CacheState(sod=sod,roles={'ROLE_A':role('ROLE_A','X1'),'ROLE_B':role('ROLE_B','X2')},users=UserState(users={'SYN_A':user,'SYN_B':copy.deepcopy(user)}),last_loaded=datetime(2026,10,27,tzinfo=timezone.utc))


class SodAnalysisApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'SAP_LENS_CONFIG_DIR':str(self.root),'DATA_CSV_PATH':''})
        self.env.start();config.get_settings.cache_clear();cache.clear_cache()
        cache._cache=synthetic_snapshot()
        settings=config.get_settings().model_copy(deep=True)
        settings.sod_csv_path=str(self.root/'sensitive-internal-source.csv')
        settings.data_lifecycle.sources['sod']=SourceSnapshot(snapshot='a'*64,path=settings.sod_csv_path,imported_at='2026-10-27T00:00:00+00:00',checked_at='2026-10-27T00:00:00+00:00')
        config.save_configuration(settings,settings.revision)
        app=FastAPI();app.include_router(router)
        self.client=TestClient(app)
        self.params={'as_of':'2026-10-27'}

    def tearDown(self):
        cache.clear_cache();config.get_settings.cache_clear();self.env.stop();self.temp.cleanup()

    def get(self, **params):
        response=self.client.get('/api/sod/analysis',params={**self.params,**params})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_counts_filters_sort_and_no_source_paths(self):
        result=self.get(limit=1)
        self.assertEqual(result['total'],2);self.assertEqual(len(result['items']),1)
        self.assertEqual(result['summary']['unfiltered']['user_findings'],2)
        self.assertEqual(self.get(username='SYN_B')['items'][0]['subject'],'SYN_B')
        self.assertEqual(self.get(search='SYN*')['total'],2)
        self.assertEqual(self.get(risk='MISSING')['total'],0)
        self.assertEqual(self.get(criticality='C')['total'],0)
        self.assertEqual(self.get(risk_type='S',group='SYN*',composite_role='ROLE_A',single_role='SINGLE_ROLE_A',tcode='X1')['total'],2)
        self.assertEqual(self.get(group='OTHER')['total'],0)
        self.assertEqual(self.get(sort='subject',descending=True)['items'][0]['subject'],'SYN_B')
        serialized=json.dumps(result)
        self.assertNotIn('sensitive-internal-source',serialized);self.assertNotIn(str(self.root),serialized)
        self.assertEqual(result['sources']['references']['sod']['snapshot'],'a'*64)
        self.assertEqual(self.client.get('/api/sod/analysis').headers['cache-control'],'no-store')

    def test_disabled_mapping_does_not_suppress_independent_role_analysis(self):
        snapshot=cache._cache;snapshot.roles['ROLE_B']=role('ROLE_B','X1','X2')
        settings=config.get_settings().model_copy(deep=True);settings.features.user_role_mapping=False
        config.save_configuration(settings,settings.revision)
        result=self.get()
        self.assertEqual(result['total'],0);self.assertEqual(result['coverage']['reason'],'mapping_disabled')
        self.assertEqual(self.get(kind='roles')['total'],1)

    def test_selected_role_combination_is_explicit_and_missing_role_rejected(self):
        self.assertEqual(self.get(kind='roles')['total'],0)
        result=self.get(kind='roles',selected_roles=['ROLE_A','ROLE_B'])
        self.assertEqual(result['total'],1);self.assertEqual(result['items'][0]['kind'],'role_combination')
        self.assertEqual(result['items'][0]['subject'],['ROLE_A','ROLE_B'])
        for params in [dict(selected_roles=['MISSING']),dict(selected_roles=['ROLE_A']*26),dict(validity='unsupported'),dict(as_of='31.12.9999'),dict(limit=101),dict(sort='source_path')]:
            self.assertEqual(self.client.get('/api/sod/analysis',params={**self.params,**params}).status_code,422)

    def test_metadata_and_account_filters_preserve_distinct_states(self):
        definition=cache._cache.sod['risks'][0]
        entry=store.StoredEntry(metadata=store.LocalMetadata(display_name='Synthetic ÆØÅ',business_category='Synthetic business'),observed_definition=store.definition_version(definition),modified='2026-10-27T00:00:00+00:00')
        store.write(store.CatalogueStorage(revision=1,entries={'SYN01':entry}))
        self.assertEqual(self.get(search='ÆØÅ',category='Synthetic business')['total'],2)
        self.assertEqual(self.get(account_status='locked')['total'],2)
        self.assertEqual(self.get(account_status='unlocked')['total'],0)
        self.assertEqual(self.get(account_status='ad_disabled')['total'],0)
        self.assertEqual(self.get(account_status='unknown')['total'],2)
        entry.metadata.enabled=False;store.write(store.CatalogueStorage(revision=2,entries={'SYN01':entry}))
        self.assertEqual(self.get()['total'],0)

    def test_evidence_page_retains_all_paths_and_checks_generation(self):
        user=cache._cache.users.users['SYN_A']
        user['assignments']=[assignment('ROLE_A',start=f'{2000+i}-01-01') for i in range(26)]+[assignment('ROLE_B')]
        result=self.get(username='SYN_A');row=result['items'][0]
        self.assertEqual(len(row['evidence']['ACTVT1']),25);self.assertEqual(row['evidence_total']['ACTVT1'],26)
        params={**self.params,'finding_id':row['finding_id'],'expected_generation':result['generation'],'side':'ACTVT1','offset':25}
        response=self.client.get('/api/sod/analysis/evidence',params=params)
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(len(response.json()['items']),1)
        self.assertEqual(response.headers['cache-control'],'no-store')
        cache._cache=copy.deepcopy(cache._cache)
        self.assertEqual(self.client.get('/api/sod/analysis/evidence',params=params).status_code,409)

    def test_export_all_filtered_findings_and_every_path_not_visible_page(self):
        self.assertEqual(len(self.get(limit=1)['items']),1)
        response=self.client.get('/api/sod/analysis/export',params=self.params)
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.content.startswith(b'\xef\xbb\xbf'))
        rows=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig')),delimiter=';'))
        self.assertEqual(len(rows),4);self.assertEqual(set(rows[0]),set(COLUMNS))
        self.assertEqual({row['SUBJECT'] for row in rows},{'SYN_A','SYN_B'})
        self.assertEqual({row['ROLE_VALID_TO'] for row in rows},{'31.12.9999'})
        self.assertEqual({row['SOD_SOURCE_VERSION'] for row in rows},{'a'*64})
        self.assertEqual({row['EVALUATION_POLICY'] for row in rows},{'sod-two-sided-v1'})
        self.assertEqual({row['ROLE_SOURCE_VERSION'] for row in rows},{''})
        self.assertEqual(response.headers['cache-control'],'no-store')
        rows=list(csv.DictReader(io.StringIO(self.client.get('/api/sod/analysis/export',params={**self.params,'username':'SYN_A'}).content.decode('utf-8-sig')),delimiter=';'))
        self.assertEqual(len(rows),2)

    def test_export_unicode_delimiters_and_formula_safety(self):
        value=cache._cache.users.users.pop('SYN_A');cache._cache.users.users['=SYN;ÆØÅ']=value
        value['assignments'][0]['role_name']='@SYN;ROLE'
        response=self.client.get('/api/sod/analysis/export',params={**self.params,'username':'=SYN;ÆØÅ'})
        rows=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig')),delimiter=';'))
        self.assertEqual(len(rows),2);self.assertEqual(rows[0]['SUBJECT'],"'=SYN;ÆØÅ")
        self.assertIn("'@SYN;ROLE",{row['ROLE_NAME'] for row in rows})
        self.assertEqual(value['assignments'][0]['role_name'],'@SYN;ROLE')

    def test_invalid_catalogue_storage_fails_safely(self):
        (self.root/'sod-catalogue.json').write_text('{invalid')
        response=self.client.get('/api/sod/analysis',params=self.params)
        self.assertEqual(response.status_code,409)
        self.assertEqual((self.root/'sod-catalogue.json').read_text(),'{invalid')

    def test_export_generation_guard_and_empty_export_header(self):
        from routers.sod_analysis import EXPORT_HEADER
        result=self.get()
        response=self.client.get('/api/sod/analysis/export',params={**self.params,'expected_generation':result['generation'],'risk':'MISSING'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.content.decode(),EXPORT_HEADER)
        self.assertEqual(response.headers['x-sap-lens-data-generation'],result['generation'])
        self.assertEqual(response.headers['x-sap-lens-as-of'],'2026-10-27')
        self.assertIn('sap-lens-sod-users-findings-2026-10-27.csv',response.headers['content-disposition'])
        cache._cache=copy.deepcopy(cache._cache)
        response=self.client.get('/api/sod/analysis/export',params={**self.params,'expected_generation':result['generation']})
        self.assertEqual(response.status_code,409)

    def test_filter_changes_reuse_analysis_and_feature_changes_invalidate(self):
        from routers import sod_analysis as api
        with patch.object(api,'analyze',wraps=api.analyze) as compute:
            self.get();self.get(username='SYN_A');self.get(kind='roles')
            self.assertEqual(compute.call_count,1)
            settings=config.get_settings().model_copy(deep=True);settings.features.employee_directory=True
            config.save_configuration(settings,settings.revision)
            self.get()
            self.assertEqual(compute.call_count,2)

    def test_real_application_boundary_applies_to_analysis_and_export(self):
        from main import create_app
        app=create_app(session_token='synthetic-sod-api-session')
        client=TestClient(app,base_url='http://127.0.0.1:18743')
        for endpoint in ['/api/sod/analysis','/api/sod/analysis/export']:
            self.assertEqual(client.get(endpoint,params=self.params).status_code,403)
            response=client.get(endpoint,params=self.params,headers={'X-SAP-Lens':'synthetic-sod-api-session'})
            self.assertEqual(response.status_code,200,response.text)
