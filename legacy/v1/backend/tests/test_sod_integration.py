"""Cross-view SoD overview and complete filtered catalogue export contracts."""
import csv
import io
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import test_sod_analysis_api as fixtures
from routers.sod import router

class SodIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.SodAnalysisApiTests();self.fixture.setUp()
        app=FastAPI();app.include_router(router);self.client=TestClient(app)
    def tearDown(self):self.fixture.tearDown()
    def test_overview_matches_analysis_and_disabled_coverage(self):
        response=self.client.get('/api/sod/overview');self.assertEqual(response.status_code,200,response.text)
        result=response.json();self.assertEqual(result['counts']['defined'],1);self.assertEqual(result['counts']['user_findings'],2)
        settings=fixtures.config.get_settings().model_copy(deep=True);settings.features.user_role_mapping=False
        fixtures.config.save_configuration(settings,settings.revision)
        result=self.client.get('/api/sod/overview').json();self.assertIsNone(result['counts']['user_findings']);self.assertEqual(result['counts']['role_findings'],0)
    def test_catalogue_export_filters_full_source_and_guidance(self):
        response=self.client.get('/api/sod/catalogue/export');self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.content.startswith(b'\xef\xbb\xbf'))
        rows=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig')),delimiter=';'))
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['RISK_ID'],'SYN01');self.assertIn('X1',rows[0]['ACTIVITY_1_TCODES'])
        self.assertIn('EXPLANATION_NO',rows[0]);self.assertNotIn('sensitive-internal-source',response.text)
        response=self.client.get('/api/sod/catalogue/export?search=absent')
        self.assertEqual(len(list(csv.reader(io.StringIO(response.content.decode('utf-8-sig')),delimiter=';'))),1)
    def test_account_display_does_not_change_engine_evidence(self):
        from sod_analysis import analyze
        result=self.fixture.get();finding=result['items'][0]
        self.assertEqual(finding['account']['sap_validity'],'Valid');self.assertEqual(finding['account']['lock_status'],'Locked')
        direct=analyze(fixtures.cache.get_snapshot(),as_of=fixtures.datetime(2026,10,27).date())
        self.assertEqual(finding['evidence_version'],direct['users'][0]['evidence_version'])
