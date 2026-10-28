"""Reverse T-code role search: 'Does not have' means at least one other T-code but none of the queried codes or patterns."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cache
import config
from main import create_app

H = {'X-SAP-Lens': '1'}
CATALOGUE = '''FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT
MM,ZC:MM:A,Alpha purchasing,ZS:A1,MM - Purchasing,MIGO,Goods movement
MM,ZC:MM:A,Alpha purchasing,ZS:A2,MM - Purchasing,ME21N,Create purchase order
MM,ZC:MM:D,Delta purchasing,ZS:D,MM - Purchasing,ME23N,Display purchase order
FI,ZC:FI:B,Beta finance,ZS:B,FI - Finance,MIGO,Goods movement
SD,ZC:SD:C,Gamma sales,ZS:C,SD - Sales,VA03,Display sales
SD,ZC:SD:E,Empty sales,ZS:E,SD - Sales,,
'''


class NegativeTcodeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(self.root), 'DATA_CSV_PATH': ''})
        self.env.start(); config.get_settings.cache_clear(); cache.clear_cache()
        roles = self.root / 'roles.csv'; roles.write_text(CATALOGUE)
        self.client = TestClient(create_app(session_token='1'), base_url='http://127.0.0.1:18743')
        settings = config.get_settings().model_dump(); settings.update(data_csv_path=str(roles))
        self.client.post('/api/configuration', headers=H, json=settings).raise_for_status()

    def tearDown(self):
        cache.clear_cache(); config.get_settings.cache_clear(); self.env.stop(); self.temp.cleanup()

    def names(self, query):
        response = self.client.get('/api/roles?' + query, headers=H)
        self.assertEqual(response.status_code, 200, response.text)
        return {role['agr_name'] for role in response.json()}

    def test_fixture_has_a_role_without_any_transaction(self):
        every = self.names('')
        self.assertIn('ZC:SD:E', every)
        self.assertEqual(self.client.get('/api/roles/ZC:SD:E', headers=H).json()['tcode_count'], 0)

    def test_positive_search_is_unchanged(self):
        self.assertEqual(self.names('tcodes=MIGO'), {'ZC:MM:A', 'ZC:FI:B'})

    def test_negative_returns_roles_with_other_transactions_but_not_the_queried_one(self):
        self.assertEqual(self.names('not_tcodes=MIGO'), {'ZC:MM:D', 'ZC:SD:C'})
        self.assertNotIn('ZC:SD:E', self.names('not_tcodes=MIGO'))
        self.assertNotIn('ZC:MM:A', self.names('not_tcodes=MIGO'))

    def test_negative_with_several_codes_means_none_of_them(self):
        self.assertEqual(self.names('not_tcodes=MIGO&not_tcodes=VA03'), {'ZC:MM:D'})
        self.assertEqual(self.names('not_tcodes=migo&not_tcodes=%20VA03%20'), {'ZC:MM:D'})

    def test_negative_wildcards_and_unknown_codes(self):
        self.assertEqual(self.names('not_tcodes=ME*'), {'ZC:FI:B', 'ZC:SD:C'})
        self.assertEqual(self.names('not_tcodes=*'), set())
        self.assertEqual(self.names('not_tcodes=NO_SUCH'), {'ZC:MM:A', 'ZC:MM:D', 'ZC:FI:B', 'ZC:SD:C'})
        self.assertEqual(self.names('not_tcodes=NO_SUCH*'), {'ZC:MM:A', 'ZC:MM:D', 'ZC:FI:B', 'ZC:SD:C'})

    def test_empty_values_do_not_activate_the_filter(self):
        self.assertEqual(self.names('not_tcodes=%20'), self.names(''))
        self.assertEqual(self.names('not_tcodes='), self.names(''))

    def test_positive_and_negative_combine_and_compose_with_other_filters(self):
        self.assertEqual(self.names('tcodes=MIGO&not_tcodes=ME21N'), {'ZC:FI:B'})
        self.assertEqual(self.names('tcodes=ME*&transaction_mode=or&not_tcodes=ME21N'), {'ZC:MM:D'})
        self.assertEqual(self.names('tcodes=MIGO&not_tcodes=MIGO'), set())
        self.assertEqual(self.names('not_tcodes=MIGO&function_key=SD'), {'ZC:SD:C'})
        self.assertEqual(self.names('not_tcodes=MIGO&search=delta'), {'ZC:MM:D'})
        self.assertEqual(self.names('not_tcodes=MIGO&function_keys=MM&function_keys=SD'), {'ZC:MM:D', 'ZC:SD:C'})

    def test_matching_tcodes_only_describe_the_positive_filter_and_input_is_bounded(self):
        found = self.client.get('/api/roles?tcodes=MIGO&not_tcodes=ME21N', headers=H).json()
        self.assertEqual(found[0]['matching_tcodes'], ['MIGO'])
        self.assertEqual(self.client.get('/api/roles?not_tcodes=' + 'X' * 129, headers=H).status_code, 422)
        too_many = '&'.join(f'not_tcodes=T{i}' for i in range(22))
        self.assertEqual(self.client.get('/api/roles?' + too_many, headers=H).status_code, 422)

    def test_saved_filters_accept_the_negative_list(self):
        body = {'name': 'Roles without SE16', 'view': 'roles', 'filters': {'tcodes': ['MIGO'], 'notTcodes': ['SE16', 'SM*'], 'transactionMode': 'and'}}
        response = self.client.post('/api/saved-filters', headers=H, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['filters']['notTcodes'], ['SE16', 'SM*'])
        bad = self.client.post('/api/saved-filters', headers=H, json={**body, 'name': 'Bad', 'filters': {'unknownTcodes': ['X']}})
        self.assertEqual(bad.status_code, 422)


if __name__ == '__main__':
    unittest.main()
