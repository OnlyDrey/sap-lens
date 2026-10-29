"""Shared transaction filter semantics for Role Lookup and User Access.

Positive: AND = contains every code, OR = contains any. Exclude matching: AND = does not contain all codes together,
OR = contains none of them. Roles without mappings and users without confirmed evidence never match the exclusion."""
import csv
import io
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
USERS = '''USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO
U1,ZC:MM:A,G1,20200101,99991231
U2,ZC:FI:B,G1,20200101,99991231
U3,ZC:SD:C,G2,20200101,99991231
U4,ZC:MM:D,G2,20200101,99991231
U4,ZC:SD:C,G2,20200101,99991231
U5,ZC:XX:MISSING,G2,20200101,99991231
U6,ZC:MM:A,G2,20000101,20010101
U7,ZC:MM:D,G2,20200101,99991231
U7,ZC:XX:MISSING,G2,20200101,99991231
'''


class TransactionFilterCase(unittest.TestCase):
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

    def roles(self, query):
        response = self.client.get('/api/roles?' + query, headers=H)
        self.assertEqual(response.status_code, 200, response.text)
        return {role['agr_name'].split(':')[-1] for role in response.json()}

    def users(self, query):
        response = self.client.get('/api/access/users?limit=100&' + query, headers=H)
        self.assertEqual(response.status_code, 200, response.text)
        return {item['username'] for item in response.json()['items']}

    def export(self, query):
        response = self.client.get('/api/access/exports/users?' + query, headers=H)
        self.assertEqual(response.status_code, 200, response.text)
        return list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig')), delimiter=';'))


class RoleSemanticsTests(TransactionFilterCase):
    def test_fixture_has_a_role_without_any_transaction(self):
        self.assertIn('E', self.roles(''))
        self.assertEqual(self.client.get('/api/roles/ZC:SD:E', headers=H).json()['tcode_count'], 0)

    def test_positive_semantics_are_unchanged(self):
        self.assertEqual(self.roles('tcodes=MIGO'), {'A', 'B'})
        self.assertEqual(self.roles('tcodes=MIGO&tcodes=ME21N&transaction_mode=and'), {'A'})
        self.assertEqual(self.roles('tcodes=MIGO&tcodes=ME21N&transaction_mode=or'), {'A', 'B'})
        self.assertEqual(self.roles('tcodes=ME*&tcodes=VA03&transaction_mode=or'), {'A', 'D', 'C'})

    def test_exclude_single_code_returns_roles_with_other_mappings_only(self):
        self.assertEqual(self.roles('tcodes=MIGO&exclude_matching=true'), {'D', 'C'})
        self.assertEqual(self.roles('tcodes=MIGO&exclude_matching=true&transaction_mode=or'), {'D', 'C'})

    def test_exclude_and_means_not_all_together_and_or_means_none(self):
        base = 'tcodes=MIGO&tcodes=ME21N&exclude_matching=true'
        self.assertEqual(self.roles(base + '&transaction_mode=and'), {'B', 'D', 'C'})
        self.assertEqual(self.roles(base + '&transaction_mode=or'), {'D', 'C'})
        every = {'A', 'D', 'B', 'C'}
        self.assertEqual(self.roles('tcodes=NO_SUCH&exclude_matching=true'), every)

    def test_exclude_wildcards_unknown_codes_and_empty_values(self):
        self.assertEqual(self.roles('tcodes=ME*&exclude_matching=true&transaction_mode=or'), {'B', 'C'})
        self.assertEqual(self.roles('tcodes=ME*&tcodes=VA03&exclude_matching=true&transaction_mode=and'), {'A', 'B', 'C', 'D'})
        self.assertEqual(self.roles('tcodes=*&exclude_matching=true&transaction_mode=or'), set())
        self.assertEqual(self.roles('tcodes=%20&exclude_matching=true'), self.roles(''))

    def test_exclude_combines_with_modules_text_and_leaves_matching_tcodes_empty(self):
        self.assertEqual(self.roles('tcodes=MIGO&exclude_matching=true&function_key=SD'), {'C'})
        self.assertEqual(self.roles('tcodes=MIGO&exclude_matching=true&search=delta'), {'D'})
        self.assertEqual(self.roles('tcodes=MIGO&exclude_matching=true&function_keys=MM&function_keys=SD'), {'D', 'C'})
        found = self.client.get('/api/roles?tcodes=MIGO&exclude_matching=true', headers=H).json()
        self.assertTrue(all(role['matching_tcodes'] == [] for role in found))
        self.assertEqual(self.client.get('/api/roles?exclude_matching=true', headers=H).status_code, 200)
        self.assertEqual(self.client.get('/api/roles?tcodes=' + 'X' * 129 + '&exclude_matching=true', headers=H).status_code, 422)


class UserAccessSemanticsTests(TransactionFilterCase):
    def test_positive_users_are_unchanged(self):
        self.assertEqual(self.users('tcodes=MIGO'), {'U1', 'U2'})
        self.assertEqual(self.users('tcodes=MIGO&tcodes=ME21N&transaction_mode=and'), {'U1'})
        self.assertEqual(self.users('tcodes=MIGO&tcodes=VA03&transaction_mode=or'), {'U1', 'U2', 'U3', 'U4'})

    def test_exclude_single_code_requires_complete_mapped_eligible_evidence(self):
        self.assertEqual(self.users('tcodes=MIGO&exclude_transactions=true'), {'U3', 'U4'})
        # U5 (unmapped role), U7 (one unmapped role) and U6 (no eligible assignment) are never reported as lacking the code.
        for unknown in ('U5', 'U6', 'U7'):
            self.assertNotIn(unknown, self.users('tcodes=MIGO&exclude_transactions=true'))

    def test_exclude_and_means_not_all_together_and_or_means_none(self):
        base = 'tcodes=MIGO&tcodes=ME21N&exclude_transactions=true'
        self.assertEqual(self.users(base + '&transaction_mode=and'), {'U2', 'U3', 'U4'})
        self.assertEqual(self.users(base + '&transaction_mode=or'), {'U3', 'U4'})

    def test_exclude_wildcards_and_expired_assignments(self):
        self.assertEqual(self.users('tcodes=ME*&exclude_transactions=true&transaction_mode=or'), {'U2', 'U3'})
        self.assertEqual(self.users('tcodes=ME*&tcodes=VA03&exclude_transactions=true&transaction_mode=and'), {'U1', 'U2', 'U3'})
        # With expired assignments shown, U6's expired mapped role counts as evidence of MIGO, so it still is not "lacking".
        self.assertEqual(self.users('tcodes=MIGO&exclude_transactions=true&show_expired=true'), {'U3', 'U4'})

    def test_exclude_combines_with_group_role_and_status_filters(self):
        self.assertEqual(self.users('tcodes=MIGO&exclude_transactions=true&group=G2'), {'U3', 'U4'})
        self.assertEqual(self.users('tcodes=MIGO&exclude_transactions=true&group=G1'), set())
        self.assertEqual(self.users('tcodes=MIGO&exclude_transactions=true&role=ZC:SD:C'), {'U3', 'U4'})
        self.assertEqual(self.users('tcodes=VA03&exclude_transactions=true&search=U1'), {'U1'})

    def test_without_a_role_catalogue_absence_is_never_concluded(self):
        settings = config.get_settings().model_dump(); settings.update(data_csv_path='')
        self.client.post('/api/configuration', headers=H, json=settings).raise_for_status()
        self.assertEqual(self.users('tcodes=MIGO&exclude_transactions=true'), set())

    def test_csv_export_uses_the_same_selection_and_semantics(self):
        for query in ('tcodes=MIGO&exclude_transactions=true', 'tcodes=MIGO&tcodes=ME21N&exclude_transactions=true&transaction_mode=and',
                      'tcodes=ME*&exclude_transactions=true&transaction_mode=or', 'tcodes=MIGO'):
            rows = self.export(query)
            self.assertEqual({row['USERNAME'] for row in rows}, self.users(query), query)
        rows = self.export('tcodes=MIGO&exclude_transactions=true')
        self.assertTrue(rows and all(row['MATCHED_FILTER'] == 'Yes' for row in rows if row['ASSIGNMENT_STATUS'] != 'Expired'))
        self.assertNotIn('Expired', {row['ASSIGNMENT_STATUS'] for row in rows})

    def test_saved_filters_store_the_exclusion_for_both_views(self):
        for view, filters in (('roles', {'tcodes': ['MIGO'], 'transactionMode': 'or', 'transactionExclude': True}), ('users', {'tcodes': ['MIGO'], 'transactionMode': 'and', 'transactionExclude': True})):
            response = self.client.post('/api/saved-filters', headers=H, json={'name': 'Without ' + view, 'view': view, 'filters': filters})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIs(response.json()['filters']['transactionExclude'], True)
        legacy = self.client.post('/api/saved-filters', headers=H, json={'name': 'Earlier', 'view': 'roles', 'filters': {'notTcodes': ['SE16'], 'transactionOperator': 'not'}})
        self.assertEqual(legacy.status_code, 200, legacy.text)
        bad = self.client.post('/api/saved-filters', headers=H, json={'name': 'Bad', 'view': 'users', 'filters': {'unknownTcodes': ['X']}})
        self.assertEqual(bad.status_code, 422)



class IndependentGroupTests(TransactionFilterCase):
    """Include and exclude are separate lists: include ALL/ANY, exclude ANY/ALL, combined with AND between the groups."""
    def test_role_exclude_any_and_all_without_an_include_group(self):
        self.assertEqual(self.roles('exclude_tcodes=MIGO&exclude_tcodes=ME21N&exclude_mode=any'), {'D', 'C'})
        self.assertEqual(self.roles('exclude_tcodes=MIGO&exclude_tcodes=ME21N&exclude_mode=all'), {'B', 'D', 'C'})
        self.assertEqual(self.roles('exclude_tcodes=MIGO'), {'D', 'C'})  # ANY is the default
        self.assertNotIn('E', self.roles('exclude_tcodes=MIGO'))  # a role without mappings is never returned by an exclusion

    def test_role_include_all_or_any_combined_with_exclusion(self):
        self.assertEqual(self.roles('tcodes=MIGO&tcodes=ME23N&transaction_mode=or&exclude_tcodes=ME21N&exclude_mode=any'), {'B', 'D'})
        self.assertEqual(self.roles('tcodes=MIGO&tcodes=ME23N&transaction_mode=or&exclude_tcodes=ME21N&exclude_tcodes=MIGO&exclude_mode=all'), {'B', 'D'})  # only A holds both excluded codes
        self.assertEqual(self.roles('tcodes=MIGO&exclude_tcodes=MIGO'), set())  # contradictory groups select nothing
        self.assertEqual(self.roles('tcodes=MIGO&tcodes=ME21N&transaction_mode=and&exclude_tcodes=ME23N'), {'A'})
        self.assertEqual(self.roles('exclude_tcodes=ME*&exclude_mode=any'), {'B', 'C'})  # wildcards behave as in the include group

    def test_exclusion_never_changes_the_included_roles_matching_codes(self):
        found = self.client.get('/api/roles?tcodes=MIGO&exclude_tcodes=ME21N', headers=H).json()
        self.assertEqual({role['agr_name'] for role in found}, {'ZC:FI:B'})
        self.assertEqual(found[0]['matching_tcodes'], ['MIGO'])

    def test_exclusion_validation_is_bounded(self):
        self.assertEqual(self.client.get('/api/roles?exclude_mode=some', headers=H).status_code, 422)
        self.assertEqual(self.client.get('/api/roles?' + '&'.join('exclude_tcodes=T%d' % n for n in range(22)), headers=H).status_code, 422)
        self.assertEqual(self.client.get('/api/access/users?exclude_mode=some', headers=H).status_code, 422)

    def test_users_exclude_any_and_all_need_complete_mapped_evidence(self):
        self.assertEqual(self.users('exclude_tcodes=MIGO&exclude_tcodes=VA03&exclude_mode=any'), set())  # every mapped user holds MIGO or VA03
        self.assertEqual(self.users('exclude_tcodes=MIGO&exclude_tcodes=ME21N&exclude_mode=all'), {'U2', 'U3', 'U4'})
        self.assertEqual(self.users('exclude_tcodes=MIGO&exclude_tcodes=ME21N&exclude_mode=any'), {'U3', 'U4'})
        for unknown in ('U5', 'U6', 'U7'):
            self.assertNotIn(unknown, self.users('exclude_tcodes=MIGO'))  # unmapped or ineligible assignments never prove absence

    def test_users_include_and_exclude_combine_and_match_the_export(self):
        queries = ('tcodes=VA03&exclude_tcodes=ME23N', 'tcodes=MIGO&tcodes=VA03&transaction_mode=or&exclude_tcodes=ME21N&exclude_mode=any',
                   'tcodes=MIGO&exclude_tcodes=ME21N&exclude_tcodes=MIGO&exclude_mode=all', 'exclude_tcodes=MIGO&exclude_mode=any')
        self.assertEqual(self.users(queries[0]), {'U3'})
        self.assertEqual(self.users(queries[1]), {'U2', 'U3', 'U4'})  # U1 holds ME21N and drops out
        self.assertEqual(self.users(queries[2]), {'U2'})  # U1 holds both excluded codes, U2 only MIGO
        for query in queries:
            self.assertEqual({row['USERNAME'] for row in self.export(query)}, self.users(query), query)

    def test_explicit_exclude_group_overrides_the_earlier_single_list_switch(self):
        self.assertEqual(self.roles('tcodes=MIGO&exclude_matching=true&exclude_tcodes=VA03'), self.roles('exclude_tcodes=VA03'))
        self.assertEqual(self.roles('tcodes=MIGO&exclude_matching=true'), {'D', 'C'})  # earlier saved links keep their meaning

    def test_saved_filters_accept_the_independent_groups(self):
        body = {'name': 'Independent', 'view': 'users', 'filters': {'tcodes': ['MIGO'], 'transactionMode': 'or', 'excludeTcodes': ['ME21N'], 'excludeMode': 'all'}}
        saved = self.client.post('/api/saved-filters', headers=H, json=body)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()['filters']['excludeMode'], 'all')
        roles = self.client.post('/api/saved-filters', headers=H, json=dict(body, view='roles', name='Roles'))
        self.assertEqual(roles.status_code, 200, roles.text)

if __name__ == '__main__':
    unittest.main()
