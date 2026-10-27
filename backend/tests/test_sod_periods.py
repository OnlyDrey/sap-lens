"""Frozen periods, independent decisions and coverage-aware comparisons."""
import copy
from datetime import date
from pathlib import Path
import sys
import unittest
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import cache
import config
import sod_periods as periods
import sod_reviews as reviews
from main import create_app
import test_sod_analysis_api as fixtures
H={'X-SAP-Lens':'synthetic-period-session'}

class SodPeriodTests(unittest.TestCase):
    def setUp(self):
        fixtures.SodAnalysisApiTests.setUp(self)
        self.client=TestClient(create_app(session_token=H['X-SAP-Lens']),base_url='http://127.0.0.1:18743')
    tearDown=fixtures.SodAnalysisApiTests.tearDown
    def create(self,name='Synthetic review'):
        return periods.create(name,date(2026,1,1),date(2026,12,31),date(2026,10,27),periods.read().revision)['period']
    def decide_all(self,period):
        data=periods.details(period['id'])
        for finding in data['snapshot']['analysis']['users']:
            periods.save_review(period['id'],finding['finding_id'],reviews.Annotation(decision='Accepted with mitigating controls',reviewer='Synthetic Reviewer',rationale='Synthetic review justification',mitigating_controls='Synthetic independent check'),periods.read().revision,reviews.read().revision,finding['evidence_version'])
    def test_snapshot_survives_refresh_and_closure_is_immutable(self):
        period=self.create();identity=period['snapshot'];self.decide_all(period)
        for state in ('In review','Ready for approval','Approved / closed'):
            periods.transition(period['id'],state,periods.read().revision,reviews.read().revision,reviewer='Synthetic Reviewer',approver='Synthetic Approver',approval_date=date(2026,10,27),confirm=True)
        closed=periods.details(period['id']);frozen=copy.deepcopy(closed['snapshot'])
        cache._cache=copy.deepcopy(cache._cache);cache._cache.sod={}
        self.assertEqual(periods.details(period['id'])['snapshot'],frozen)
        self.assertNotEqual(closed['checksum'],identity)
        for action in [lambda:periods.recapture(period['id'],periods.read().revision,True),lambda:periods.transition(period['id'],'Draft',periods.read().revision,reviews.read().revision)]:
            with self.assertRaises(Exception) as error:action()
            self.assertEqual(error.exception.status_code,409)
    def test_pending_reviews_block_approval_and_invalid_dates_fail_safely(self):
        period=self.create();periods.transition(period['id'],'In review',periods.read().revision,reviews.read().revision)
        with self.assertRaises(Exception) as error:periods.transition(period['id'],'Ready for approval',periods.read().revision,reviews.read().revision)
        self.assertEqual(error.exception.status_code,409)
        with self.assertRaises(Exception) as error:periods.create('Bad',date(2026,12,31),date(2026,1,1),date(2026,10,27),periods.read().revision)
        self.assertEqual(error.exception.status_code,422)
    def test_period_decisions_do_not_overwrite_current_or_other_periods(self):
        first=self.create('First');second=self.create('Second');self.decide_all(first)
        self.assertTrue(all(row['lifecycle']=='Reviewed' for row in periods.details(first['id'])['snapshot']['reviews']['items']))
        self.assertTrue(all(row['lifecycle']=='Pending' for row in periods.details(second['id'])['snapshot']['reviews']['items']))
        self.assertFalse(reviews.read().contexts.get('current'))
    def test_comparison_resolution_requires_complete_scope(self):
        first=self.create('Before')
        cache._cache=copy.deepcopy(cache._cache);cache._cache.users.users['SYN_A']['assignments']=cache._cache.users.users['SYN_A']['assignments'][:1]
        second=self.create('After');result=periods.compare(first['id'],second['id'])
        self.assertEqual(result['summary']['Resolved'],1)
        cache._cache=copy.deepcopy(cache._cache);cache._cache.users.users.pop('SYN_A')
        third=self.create('Missing user');result=periods.compare(first['id'],third['id'])
        self.assertEqual(result['summary']['Resolved'],0);self.assertEqual(result['summary']['Not observed / coverage changed'],1)
    def test_api_auth_pagination_and_stale_revision(self):
        self.assertEqual(self.client.get('/api/sod/periods').status_code,403)
        period=self.create();response=self.client.get('/api/sod/periods/'+period['id']+'?limit=1',headers=H)
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['total'],2);self.assertEqual(len(response.json()['snapshot']['analysis']['users']),1)
        with self.assertRaises(Exception) as error:periods.recapture(period['id'],0,True)
        self.assertEqual(error.exception.status_code,409)
        saved=periods.details(period['id']);path=config.config_dir()/'sod-periods.json';original=path.read_bytes();path.write_bytes(b'invalid')
        with self.assertRaises(Exception):periods.read()
        self.assertEqual(path.read_bytes(),b'invalid');path.write_bytes(original);self.assertEqual(periods.details(period['id'])['checksum'],saved['checksum'])

    def test_reopened_classification_ignores_open_or_later_closed_prior_periods(self):
        prior=self.create('Prior draft');original=copy.deepcopy(cache._cache.users.users['SYN_A']['assignments'])
        cache._cache=copy.deepcopy(cache._cache);cache._cache.users.users['SYN_A']['assignments']=original[:1]
        left=self.create('Before return')
        cache._cache=copy.deepcopy(cache._cache);cache._cache.users.users['SYN_A']['assignments']=original
        right=self.create('After return')
        self.assertEqual(periods.compare(left['id'],right['id'])['summary']['New'],1)
        self.decide_all(prior)
        for state in ('In review','Ready for approval','Approved / closed'):
            periods.transition(prior['id'],state,periods.read().revision,reviews.read().revision,reviewer='Synthetic Reviewer',approver='Synthetic Approver',approval_date=date(2026,10,27),confirm=True)
        self.assertEqual(periods.compare(left['id'],right['id'])['summary']['New'],1)

    def test_reopened_classification_uses_prior_frozen_observation(self):
        prior=self.create('Prior closed');self.decide_all(prior)
        for state in ('In review','Ready for approval','Approved / closed'):
            periods.transition(prior['id'],state,periods.read().revision,reviews.read().revision,reviewer='Synthetic Reviewer',approver='Synthetic Approver',approval_date=date(2026,10,27),confirm=True)
        original=copy.deepcopy(cache._cache.users.users['SYN_A']['assignments'])
        cache._cache=copy.deepcopy(cache._cache);cache._cache.users.users['SYN_A']['assignments']=original[:1]
        left=self.create('Before return')
        cache._cache=copy.deepcopy(cache._cache);cache._cache.users.users['SYN_A']['assignments']=original
        right=self.create('After return')
        self.assertEqual(periods.compare(left['id'],right['id'])['summary']['Reopened'],1)
