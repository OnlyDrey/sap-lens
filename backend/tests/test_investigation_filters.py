"""Catalogue set semantics and shared, inclusive assignment-date filtering."""
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
import cache
from main import create_app
from assignment_filters import assignment_dates, within_dates
from transaction_filters import matching_role_names

H = {'X-SAP-Lens': '1'}
CATALOGUE = '''FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT
MM,ZC:MM:A,Alpha purchasing,ZS:A1,MM - Purchasing,MIGO,Goods movement
MM,ZC:MM:A,Alpha purchasing,ZS:A2,MM - Purchasing,ME21N,Create purchase order
FI,ZC:FI:B,Beta finance,ZS:B,FI - Finance,MIGO,Goods movement
SD,ZC:SD:C,Gamma sales,ZS:C,SD - Sales,VA03,Display sales
'''
USERS = '''USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO
DEMO_ONE,ZC:MM:A,G1,20200101,99991231
DEMO_ONE,ZC:FI:B,G1,20240101,20260101
DEMO_ONE,ZO:MM:M:PR_REL_ST_G1_N1:ALL,G1,20240101,99991231
DEMO_TWO,ZO:MM:M:PR_REL_ST_G1_N1:ALL,G2,20250101,20251231
DEMO_TWO,ZO:MM:M:PO_REL_ST_G2_N2:ALL,G2,,
DEMO_THREE,ZO:UNKNOWN,G2,20300101,99991231
'''


class InvestigationFilterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(self.root), 'DATA_CSV_PATH': ''})
        self.env.start(); config.get_settings.cache_clear(); cache.clear_cache()
        roles, users = self.root / 'roles.csv', self.root / 'users.csv'
        roles.write_text(CATALOGUE); users.write_text(USERS)
        self.client = TestClient(create_app(session_token='1'), base_url='http://127.0.0.1:18743')
        settings = config.get_settings().model_dump(); settings.update(data_csv_path=str(roles), user_csv_path=str(users))
        self.client.post('/api/configuration', headers=H, json=settings).raise_for_status()

    def tearDown(self):
        cache.clear_cache(); config.get_settings.cache_clear(); self.env.stop(); self.temp.cleanup()

    def get(self, path):
        response = self.client.get('/api/' + path, headers=H); response.raise_for_status(); return response.json()

    def test_catalogue_default_and_uses_whole_role_across_mapping_rows(self):
        found = self.get('roles?tcodes=%20migo%20&tcodes=ME21N&tcodes=MIGO')
        self.assertEqual([r['agr_name'] for r in found], ['ZC:MM:A'])
        self.assertEqual(set(found[0]['matching_tcodes']), {'MIGO', 'ME21N'})
        self.assertEqual(self.get('roles?tcodes=MIGO&tcodes=VA03'), [])

    def test_catalogue_or_and_exact_unmatched_and_operator_bounds(self):
        found = self.get('roles?tcodes=MIGO&tcodes=ME21N&transaction_mode=or')
        self.assertEqual({r['agr_name'] for r in found}, {'ZC:MM:A', 'ZC:FI:B'})
        self.assertEqual(self.get('roles?tcodes=MIG'), [])
        self.assertEqual(len(self.get('roles?transaction_mode=or')), 3)
        self.assertEqual(self.client.get('/api/roles?transaction_mode=x', headers=H).status_code, 422)
        self.assertEqual(matching_role_names({}, [], 'and'), set())

    def test_areas_use_or_and_combine_with_text_and_tcodes_using_and(self):
        found = self.get('roles?function_keys=MM&function_keys=SD')
        self.assertEqual({r['agr_name'] for r in found}, {'ZC:MM:A', 'ZC:SD:C'})
        found = self.get('roles?function_keys=MM&function_keys=SD&tcodes=MIGO&search=alpha')
        self.assertEqual([r['agr_name'] for r in found], ['ZC:MM:A'])
        self.assertEqual(self.get('roles?function_keys=SD&tcodes=MIGO'), [])

    def test_role_text_search_never_matches_tcode_or_module_metadata(self):
        self.assertEqual(self.get('roles?search=migo'), [])
        self.assertEqual(self.get('roles?search=materials%20management'), [])
        self.assertEqual([r['agr_name'] for r in self.get('roles?search=PURCHASING')], ['ZC:MM:A'])
        self.assertEqual([r['agr_name'] for r in self.get('roles?search=zc:fi')], ['ZC:FI:B'])

    def test_user_assignment_date_bounds_apply_before_pagination(self):
        base = 'access/users/DEMO_ONE?scope=all&show_expired=true&valid_from_min=2024-01-01&valid_from_max=2024-01-01'
        first = self.get(base + '&limit=1'); second = self.get(base + '&limit=1&offset=1')
        self.assertEqual((first['total'], len(first['items']), len(second['items'])), (2, 1, 1))
        self.assertEqual({a['role_name'] for a in first['items'] + second['items']}, {'ZC:FI:B', 'ZO:MM:M:PR_REL_ST_G1_N1:ALL'})
        exact_end = self.get('access/users/DEMO_ONE?scope=all&show_expired=true&valid_to_min=2026-01-01&valid_to_max=2026-01-01')
        self.assertEqual(exact_end['total'], 1)
        self.assertEqual(exact_end['items'][0]['role_name'], 'ZC:FI:B')

    def test_open_ended_missing_dates_and_status_categories_stay_distinct(self):
        only = self.get('access/releases?status=all&open_ended=only')
        self.assertEqual({r['role_name'] for r in only['items']}, {'ZO:MM:M:PR_REL_ST_G1_N1:ALL', 'ZO:UNKNOWN'})
        missing = self.get('access/releases?status=unknown')
        self.assertEqual([r['role_name'] for r in missing['items']], ['ZO:MM:M:PO_REL_ST_G2_N2:ALL'])
        self.assertEqual(self.get('access/releases?status=unknown&valid_to_min=0001-01-01')['total'], 0)
        self.assertEqual(self.get('access/releases?status=all&valid_to_max=9999-12-31')['total'], 2)

    def test_date_validation_rejects_reversed_and_invalid_bounds(self):
        for suffix in ['valid_from_min=2025-01-01&valid_from_max=2024-01-01', 'valid_to_min=2025-01-01&valid_to_max=2024-01-01', 'valid_to_min=2025-02-30', 'open_ended=guess']:
            self.assertEqual(self.client.get('/api/access/releases?' + suffix, headers=H).status_code, 422)

    def test_release_counts_matrix_navigation_and_detail_share_same_predicate(self):
        query = 'status=all&valid_from_min=2024-01-01&valid_from_max=2024-01-01'
        roles = self.get('access/releases?' + query)
        self.assertEqual(roles['total'], 1); self.assertEqual(roles['items'][0]['assigned_users'], 1)
        self.assertEqual(roles['matrix'][0]['user_count'], 1)
        role = 'ZO:MM:M:PR_REL_ST_G1_N1:ALL'
        details = self.get('access/release-assignments?role=' + role + '&' + query)
        self.assertEqual((details['total'], details['distinct_users']), (1, 1))
        self.assertEqual(details['role_info']['release_strategy'], 'N1')
        nav = self.get('access/releases?anchor=' + role + '&' + query)['navigation']
        self.assertEqual((nav['total'], nav['index']), (1, 0))
        self.assertIsNone(nav['next'])
        options = self.get('access/release-options?field=group&' + query)
        self.assertEqual(options['items'], ['G1'])
        self.assertFalse(self.get('access/release-assignments?role=ZO:UNKNOWN&status=all')['role_info']['parsed'])

    def test_filter_requests_do_not_mutate_diagnostics_or_source_records(self):
        before = self.get('diagnostics/export')
        self.get('roles?tcodes=UNMATCHED&function_keys=MM')
        self.get('access/releases?status=expired&valid_to_max=2025-12-31')
        after = self.get('diagnostics/export')
        before.pop('generated_at'); after.pop('generated_at')
        self.assertEqual(before, after)
        self.assertEqual(self.get('access/users/DEMO_ONE?scope=all&show_expired=true')['retained_assignments'], 3)

    def test_date_predicate_is_inclusive_and_does_not_supply_missing_values(self):
        filters = assignment_dates(valid_from_min=date(2024, 1, 1), valid_from_max=date(2024, 1, 1), valid_to_max=date(9999, 12, 31))
        self.assertTrue(within_dates({'valid_from': '2024-01-01', 'valid_to': '9999-12-31'}, filters))
        self.assertFalse(within_dates({'valid_from': None, 'valid_to': '9999-12-31'}, filters))
