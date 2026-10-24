"""Synthetic account review, identity reliability, durable recovery and local decisions."""
import csv
import json
import os
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cache
import config
import account_review as review
from employee_directory import HEADERS, store
from main import create_app
H = {'X-SAP-Lens': '1'}


class AccountReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(self.root / 'private'), 'DATA_CSV_PATH': ''})
        self.env.start()
        config.get_settings.cache_clear(); cache.clear_cache(); store.clear()
        self.csv = self.root / 'users.csv'; self.directory = self.root / 'directory.csv'
        self.write_users()
        with self.directory.open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=HEADERS, delimiter=';'); writer.writeheader()
            for name, enabled in [('OPEN', 'false'), ('LOCKED', 'false'), ('NORMAL', 'true')]:
                writer.writerow(dict(Name='Demo ' + name, Mail=name.lower()+'@example.test', Enabled=enabled))
        settings = config.get_settings().model_copy(deep=True)
        settings.user_csv_path = str(self.csv); settings.employee_csv_path = str(self.directory)
        settings.features.employee_directory = True
        config.save_configuration(settings, settings.revision); cache.load_cache()
        self.client = TestClient(create_app(session_token='1'), base_url='http://127.0.0.1:18743')

    def tearDown(self):
        store.clear(); cache.clear_cache(); config.get_settings.cache_clear(); self.env.stop(); self.temp.cleanup()

    def write_users(self, shared=False):
        with self.csv.open('w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow('USERNAME,ROLE_NAME,USER_GROUP,EMAIL,USER_VALID_FROM,USER_VALID_TO,USER_LOCKED,USER_TYPE'.split(','))
            for username, group, email, end, locked, kind in [
                ('DEMO_OPEN','UNLICENSED','open@example.test','99991231','0','A'),
                ('DEMO_LOCKED','DIALOG','locked@example.test','99991231','1','A'),
                ('DEMO_NORMAL','DIALOG','open@example.test' if shared else 'normal@example.test','99991231','0','A'),
                ('DEMO_MISSING','DIALOG','','99991231','','A'),
                ('DEMO_EXPIRED','DIALOG','','20200101','0','A'),
                ('DEMO_SERVICE','DIALOG','','99991231','0','S')]:
                writer.writerow([username,'',group,email,'20000101',end,locked,kind])

    def get(self, query=''):
        result = self.client.get('/api/account-review'+query, headers=H)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def test_findings_keep_security_separate_from_license_classification(self):
        data = self.get(); rows = {r['username']:r for r in data['items']}
        self.assertIn('ad_disabled_open', rows['DEMO_OPEN']['findings'])
        self.assertTrue(rows['DEMO_OPEN']['unlicensed'])
        self.assertIn('ad_disabled_locked', rows['DEMO_LOCKED']['findings'])
        self.assertEqual(rows['DEMO_NORMAL']['findings'], [])
        self.assertEqual(rows['DEMO_MISSING']['ad_status'], 'Unknown')
        self.assertNotIn('ad_disabled_open', rows['DEMO_MISSING']['findings'])
        self.assertIn('expired', rows['DEMO_EXPIRED']['findings'])
        self.assertIn('technical', rows['DEMO_SERVICE']['findings'])
        self.assertEqual(data['summary']['mismatch'], 1)
        self.assertEqual(data['summary']['total'], 6)

    def test_shared_sap_email_is_ambiguous_not_ad_disabled_evidence(self):
        self.write_users(shared=True); cache.load_cache()
        row = next(r for r in self.get()['items'] if r['username']=='DEMO_OPEN')
        self.assertEqual(row['match_status'], 'ambiguous_sap_email')
        self.assertEqual(row['ad_status'], 'Unknown')
        self.assertNotIn('ad_disabled_open', row['findings'])
        self.assertEqual(self.client.get('/api/employees/match/DEMO_OPEN', headers=H).json()['status'], 'ambiguous_sap_email')

    def test_disabled_directory_does_not_claim_missing_or_disabled_identity(self):
        settings = config.get_settings().model_copy(deep=True);settings.features.employee_directory=False
        config.save_configuration(settings, settings.revision)
        data=self.get();self.assertIsNone(data['summary']['missing']);self.assertEqual(data['summary']['mismatch'],0)
        self.assertTrue(all(r['ad_status']=='Unknown' for r in data['items']))

    def test_mapping_guard_applies_to_reviews_and_decisions(self):
        settings=config.get_settings().model_copy(deep=True);settings.features.user_role_mapping=False
        config.save_configuration(settings,settings.revision)
        self.assertEqual(self.client.get('/api/account-review',headers=H).status_code,409)
        self.assertEqual(self.client.post('/api/account-review/decision/DEMO_OPEN',headers=H,json={}).status_code,409)

    def test_filters_sort_pagination_and_generation_are_deterministic(self):
        self.assertEqual(self.get('?finding=ad_disabled_open')['total'],1)
        self.assertEqual(self.get('?license_group=classified')['items'][0]['username'],'DEMO_OPEN')
        self.assertEqual(self.get('?search=demo_normal')['total'],1)
        a=self.get('?limit=2');b=self.get('?limit=2&offset=2')
        self.assertEqual(a['data_revision'],b['data_revision'])
        self.assertFalse({r['username'] for r in a['items']}&{r['username'] for r in b['items']})
        reverse=self.get('?descending=true')['items'];self.assertEqual(reverse[0]['username'],'DEMO_SERVICE')
        self.assertEqual(self.client.get('/api/account-review?finding=unsupported',headers=H).status_code,422)

    def decision(self, row, **kwargs):
        return self.client.post('/api/account-review/decision/'+row['username'],headers=H,json=dict(state='Investigating',reviewer='Synthetic Reviewer',rationale='Synthetic investigation',evidence_version=row['evidence_version'],**kwargs))

    def test_decision_persists_restart_and_changed_identity_is_flagged(self):
        row=self.get('?search=DEMO_OPEN')['items'][0]
        self.assertEqual(self.decision(row).status_code,200)
        restarted=subprocess.run([sys.executable,'-c',"import account_review; assert next(iter(account_review.decisions().values()))['state'] == 'Investigating'"],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
        self.assertEqual(restarted.returncode,0,restarted.stderr)
        config.get_settings.cache_clear();store.clear();cache.load_cache()
        current=self.get('?search=DEMO_OPEN')['items'][0]
        self.assertEqual(current['review_state'],'Investigating');self.assertFalse(current['stale'])
        self.csv.write_text(self.csv.read_text().replace('open@example.test','changed@example.test'))
        cache.load_cache();changed=self.get('?search=DEMO_OPEN')['items'][0]
        self.assertTrue(changed['stale']);self.assertEqual(changed['review_state'],'Needs review')
        self.assertEqual(self.decision(row).status_code,409)
        saved=(config.config_dir()/'account-review.json').read_text()
        self.assertNotIn('open@example.test',saved);self.assertNotIn('DEMO_OPEN',saved)

    def test_invalid_decision_and_failed_storage_preserve_previous(self):
        row=self.get()['items'][0]
        self.assertEqual(self.decision(row).status_code,200)
        saved=(config.config_dir()/'account-review.json').read_bytes()
        with patch('account_review.atomic_write',side_effect=OSError('private location')):
            result=self.decision(row)
        self.assertEqual(result.status_code,409);self.assertNotIn('private location',result.text)
        self.assertEqual((config.config_dir()/'account-review.json').read_bytes(),saved)
        self.assertEqual(self.client.post('/api/account-review/decision/'+row['username'],headers=H,json={'state':'Automatic disable'}).status_code,422)

    def test_unlicensed_groups_persist_and_validate_without_changing_sources(self):
        settings=config.get_settings().model_copy(deep=True);settings.unlicensed_user_groups=['DIALOG']
        config.save_configuration(settings,settings.revision);config.get_settings.cache_clear()
        self.assertEqual(config.get_settings().unlicensed_user_groups,['DIALOG'])
        self.assertEqual(self.get()['summary']['unlicensed'],5)
        self.assertEqual(self.client.get('/api/account-review?finding=ad_disabled_open&license_group=exclude',headers=H).json()['total'],1)

    def test_legacy_memory_snapshot_recovery_survives_missing_csv_and_restart(self):
        status=self.client.get('/api/employees/status',headers=H).json()
        self.assertEqual(status['storage'],'legacy_path_only');self.assertFalse(status['persisted'])
        self.directory.unlink()
        result=self.client.post('/api/employees/persist',headers=H,json={'digest':status['digest'],'revision':config.get_settings().revision})
        self.assertEqual(result.status_code,200,result.text);self.assertTrue(result.json()['persisted'])
        store.clear();config.get_settings.cache_clear()
        restored=self.client.get('/api/employees/status',headers=H).json()
        self.assertTrue(restored['persisted']);self.assertEqual(restored['report']['records'],3)
        self.assertEqual(restored['report']['imported_at'],status['report']['imported_at'])
        restarted=subprocess.run([sys.executable,'-c',"from config import get_settings; from employee_directory import DirectoryStore; s=get_settings(); assert len(DirectoryStore().get(s.employee_csv_path,s.employee_snapshot_id).rows)==3"],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
        self.assertEqual(restarted.returncode,0,restarted.stderr)

    def test_failed_legacy_recovery_keeps_records_and_configuration(self):
        status=self.client.get('/api/employees/status',headers=H).json();directory=store.directory
        with patch('routers.employees.save_configuration',side_effect=OSError()):
            response=self.client.post('/api/employees/persist',headers=H,json={'digest':status['digest'],'revision':config.get_settings().revision})
        self.assertEqual(response.status_code,409);self.assertIs(store.directory,directory)
        self.assertIsNone(config.get_settings().employee_snapshot_id)

    def test_diagnostic_export_contains_no_identity_paths_or_review_notes(self):
        row=self.get()['items'][0];self.decision(row)
        text=self.client.get('/api/diagnostics/export',headers=H).text
        for forbidden in ['DEMO_OPEN','Synthetic Reviewer','Synthetic investigation','example.test',str(self.root),str(self.csv)]:self.assertNotIn(forbidden,text)

    def test_unknown_and_conflicting_validity_remain_unknown(self):
        self.assertEqual(review.validity([{'valid_from':None,'valid_to':None}]),'Unknown')
        self.assertEqual(review.validity([{'valid_from':'2000-01-01','valid_to':'9999-12-31'},{'valid_from':'2000-01-01','valid_to':'2020-01-01'}]),'Unknown')

    def test_corrupt_review_store_is_not_overwritten_or_an_error_for_core_lookup(self):
        path=config.config_dir()/'account-review.json';path.parent.mkdir(parents=True,exist_ok=True)
        for raw in [b'[]',b'{"format":1,"decisions":{"invalid":{}}}',b'not json']:
            path.write_bytes(raw)
            response=self.client.get('/api/account-review',headers=H)
            self.assertEqual(response.status_code,409);self.assertEqual(path.read_bytes(),raw)
            self.assertEqual(self.client.get('/api/roles',headers=H).status_code,200)
            self.assertEqual(self.client.get('/api/dashboard',headers=H).status_code,200)

    def test_review_pages_reuse_one_publication_and_policy_changes_invalidate_it(self):
        with patch('account_review.rows',wraps=review.rows) as calculate:
            first=self.get('?limit=2');self.get('?offset=2&limit=2')
            self.assertEqual(calculate.call_count,1)
            settings=config.get_settings().model_copy(deep=True);settings.unlicensed_user_groups=['DIALOG']
            config.save_configuration(settings,settings.revision)
            second=self.get('?limit=2');self.assertEqual(calculate.call_count,2)
            self.assertNotEqual(first['data_revision'],second['data_revision'])
            cache.load_cache();self.get();self.assertEqual(calculate.call_count,3)

    def test_evaluation_day_changes_cached_validity_without_staling_unchanged_evidence(self):
        from datetime import date
        state=cache.get_snapshot();directory=store.get(config.get_settings().employee_csv_path)
        current=review.cached_rows(state,directory,{},['UNLICENSED'],date(2026,1,1))
        next_day=review.cached_rows(state,directory,{},['UNLICENSED'],date(2026,1,2))
        self.assertIsNot(current,next_day)
        self.assertEqual(current[0]['evidence_version'],next_day[0]['evidence_version'])

    def test_review_cache_does_not_pin_a_retired_full_sap_snapshot(self):
        from datetime import date
        import gc
        import weakref
        state=cache.get_snapshot();reference=weakref.ref(state)
        review.cached_rows(state,store.get(config.get_settings().employee_csv_path),{},['UNLICENSED'],date.today())
        cache.clear_cache();del state;gc.collect()
        self.assertIsNone(reference())

    def test_dashboard_and_review_include_stale_decisions_without_current_source_findings(self):
        row=self.get('?search=DEMO_NORMAL')['items'][0]
        self.assertFalse(row['findings']);self.assertEqual(self.decision(row).status_code,200)
        with self.csv.open(newline='') as f:
            reader=csv.DictReader(f);fields=reader.fieldnames;records=list(reader)
        for record in records:
            if record['USERNAME']=='DEMO_NORMAL':record['USER_TYPE']='X'
        with self.csv.open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(records)
        cache.load_cache()
        result=self.get();normal=next(r for r in result['items'] if r['username']=='DEMO_NORMAL')
        self.assertTrue(normal['stale']);self.assertFalse(normal['findings'])
        dashboard=self.client.get('/api/dashboard',headers=H).json()
        metric=next(m for m in dashboard['metrics'] if m['id']=='account_review')
        self.assertEqual(metric['value'],result['summary']['requiring_review'])
