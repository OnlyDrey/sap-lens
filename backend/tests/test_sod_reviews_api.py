"""Review boundary, generation races, immutable history and complete exports."""
import copy
import csv
import io
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
import cache
from main import create_app
import test_sod_analysis_api as fixtures

H={'X-SAP-Lens':'synthetic-review-session'}

class SodReviewApiTests(unittest.TestCase):
    def setUp(self):
        fixtures.SodAnalysisApiTests.setUp(self)
        self.client=TestClient(create_app(session_token=H['X-SAP-Lens']),base_url='http://127.0.0.1:18743')
    tearDown=fixtures.SodAnalysisApiTests.tearDown

    def data(self):
        response=self.client.get('/api/sod/reviews',headers=H)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def save(self,data,row,**annotation):
        return self.client.post('/api/sod/reviews/'+row['finding_id'],headers=H,json=dict(expected_revision=data['revision'],expected_generation=data['generation'],evidence_version=row['finding']['evidence_version'],annotation={**dict(decision='Accepted with mitigating controls',reviewer='Synthetic Reviewer',rationale='Synthetic documented investigation',mitigating_controls='Synthetic independent control'),**annotation}))

    def test_auth_justification_and_history_append(self):
        self.assertEqual(self.client.get('/api/sod/reviews').status_code,403)
        data=self.data();row=data['items'][0]
        self.assertEqual(self.save(data,row,rationale='').status_code,422)
        response=self.save(data,row);self.assertEqual(response.status_code,200,response.text)
        self.assertIn('Self-reported',response.json()['reviewer_identity'])
        updated=self.data();self.assertEqual(updated['items'][0]['lifecycle'],'Reviewed')
        self.assertEqual(self.save(data,row).status_code,409)
        self.assertEqual(self.save(updated,updated['items'][0],comments='Additional evidence').status_code,200)
        history=self.client.get(f"/api/sod/reviews/{row['finding_id']}/history",headers=H).json()
        self.assertEqual(history['total'],2)
        event=history['items'][0]
        evidence=self.client.get(f"/api/sod/reviews/{row['finding_id']}/history/{event['event_id']}/evidence",headers=H).json()
        self.assertEqual(evidence['total'],1);self.assertEqual(evidence['source_versions']['sod'],'a'*64)

    def test_changed_generation_rejected_and_missing_source_never_resolved(self):
        data=self.data();row=data['items'][0]
        cache._cache=copy.deepcopy(cache._cache)
        self.assertEqual(self.save(data,row).status_code,409)
        data=self.data();row=data['items'][0];self.assertEqual(self.save(data,row).status_code,200)
        cache._cache=copy.deepcopy(cache._cache);cache._cache.sod={}
        historical=self.data()['items'][0]
        self.assertEqual(historical['lifecycle'],'Historical');self.assertTrue(historical['stale'])

    def test_filtered_exports_include_all_results_and_formula_safety(self):
        data=self.data()
        for row in data['items']:self.assertEqual(self.save(self.data(),row).status_code,200)
        response=self.client.get('/api/sod/reviews/export',headers=H)
        self.assertTrue(response.content.startswith(b'\xef\xbb\xbf'))
        rows=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig')),delimiter=';'))
        self.assertEqual(len(rows),2);self.assertTrue(all(row['REVIEWER']=='Synthetic Reviewer' for row in rows))
        filtered=self.client.get('/api/sod/reviews/export?search=SYN_A',headers=H)
        self.assertEqual(len(list(csv.DictReader(io.StringIO(filtered.content.decode('utf-8-sig')),delimiter=';'))),1)
        self.assertEqual(self.client.get('/api/sod/reviews/actions/export',headers=H).status_code,200)

    def test_resolution_requires_complete_retained_scope_not_missing_sources(self):
        data=self.data();row=data['items'][0];self.assertEqual(self.save(data,row).status_code,200)
        cache._cache=copy.deepcopy(cache._cache)
        cache._cache.users.users['SYN_A']['assignments']=cache._cache.users.users['SYN_A']['assignments'][:1]
        result=next(item for item in self.data()['items'] if item['finding']['subject']=='SYN_A')
        self.assertEqual(result['lifecycle'],'Resolved')
        cache._cache=copy.deepcopy(cache._cache);cache._cache.roles={}
        result=next(item for item in self.data()['items'] if item['finding']['subject']=='SYN_A')
        self.assertEqual(result['lifecycle'],'Historical')
