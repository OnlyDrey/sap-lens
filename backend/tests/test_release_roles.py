"""Release Area derivation, multi-select release filters and distinct release-role list/export."""
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
import config
import cache
from main import create_app
from user_access import release_area
from csv_exports import ROLE_LIST_HEADER

H = {'X-SAP-Lens': '1'}
CATALOGUE = '''FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT
MM,ZC:MM:A,Alpha purchasing,ZS:A1,MM - Purchasing,MIGO,Goods movement
'''
USERS = '''USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO
DEMO_ONE,ZO:MM:M:PR_REL_ST_E2_N1:ALL,G1,20200101,99991231
DEMO_ONE,ZO:MM:M:PO_REL_ST_E3_N2:ALL,G1,20200101,99991231
DEMO_TWO,ZO:MM:M:PR_REL_ST_E2_N1:ALL,G2,20200101,99991231
DEMO_TWO,ZO:MM:M:PR_REL_ST_N1_N1:ALL,G2,20200101,99991231
DEMO_TWO,ZO:MM:M:PR_REL_ST_A2_S1:ALL,G2,20200101,20210101
DEMO_THREE,ZO:UNKNOWN,G2,20200101,99991231
DEMO_THREE,ZC:MM:A,G2,20200101,99991231
'''


class ReleaseRoleTests(unittest.TestCase):
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

    def test_area_is_first_character_and_malformed_values_have_none(self):
        self.assertEqual([release_area(v) for v in ('E2', 'E3', 'N1', 'A2', ' e2 ')], ['E', 'E', 'N', 'A', 'E'])
        self.assertEqual([release_area(v) for v in (None, '', '  ', '-1', 'É2')], [None] * 5)

    def test_options_are_derived_and_release_groups_narrow_by_selected_areas(self):
        areas = self.get('access/release-options?field=release_area&status=all')['items']
        self.assertEqual(areas, ['A', 'E', 'N'])
        self.assertEqual(self.get('access/release-options?field=release_group&status=all')['items'], ['A2', 'E2', 'E3', 'N1'])
        self.assertEqual(self.get('access/release-options?field=release_group&status=all&release_areas=E')['items'], ['E2', 'E3'])
        self.assertEqual(self.get('access/release-options?field=release_group&status=all&release_areas=E&release_areas=N')['items'], ['E2', 'E3', 'N1'])
        # An area never narrows its own options.
        self.assertEqual(self.get('access/release-options?field=release_area&status=all&release_areas=E')['items'], ['A', 'E', 'N'])

    def test_multiselect_is_or_within_and_between_categories(self):
        base = 'access/releases?status=all&'
        names = lambda q: {r['role_name'] for r in self.get(base + q)['items']}
        self.assertEqual(names('release_areas=E'), {'ZO:MM:M:PR_REL_ST_E2_N1:ALL', 'ZO:MM:M:PO_REL_ST_E3_N2:ALL'})
        self.assertEqual(names('release_areas=E&release_areas=N'), {'ZO:MM:M:PR_REL_ST_E2_N1:ALL', 'ZO:MM:M:PO_REL_ST_E3_N2:ALL', 'ZO:MM:M:PR_REL_ST_N1_N1:ALL'})
        self.assertEqual(names('release_areas=E&release_groups=E3'), {'ZO:MM:M:PO_REL_ST_E3_N2:ALL'})
        self.assertEqual(names('release_groups=E2&release_groups=A2'), {'ZO:MM:M:PR_REL_ST_E2_N1:ALL', 'ZO:MM:M:PR_REL_ST_A2_S1:ALL'})
        self.assertEqual(names('release_areas=E&document_type=PO'), {'ZO:MM:M:PO_REL_ST_E3_N2:ALL'})
        # Areas that match nothing and blank or over-long values never widen the result.
        self.assertEqual(names('release_areas=Z'), set())
        self.assertEqual(names('release_areas=%20&release_groups='), set(names('')))
        self.assertEqual(names('release_groups=' + 'X' * 101), set(names('')))
        rows = {r['role_name']: r['release_area'] for r in self.get(base)['items']}
        self.assertEqual(rows['ZO:MM:M:PR_REL_ST_N1_N1:ALL'], 'N')

    def test_distinct_role_list_respects_filters_and_validity_and_excludes_catalogue_roles(self):
        every = self.get('access/release-roles?status=all')
        self.assertEqual(every['total'], 5)  # four parsed roles and one unparsed; the catalogue role is excluded
        active = self.get('access/release-roles')
        self.assertNotIn('ZO:MM:M:PR_REL_ST_A2_S1:ALL', [r['role_name'] for r in active['items']])
        self.assertEqual([r['role_name'] for r in self.get('access/release-roles?release_areas=E&document_type=PR')['items']], ['ZO:MM:M:PR_REL_ST_E2_N1:ALL'])
        self.assertNotIn('ZC:MM:A', [r['role_name'] for r in every['items']])
        # Roles shared by several users are listed once.
        self.assertEqual(sum(r['role_name'] == 'ZO:MM:M:PR_REL_ST_E2_N1:ALL' for r in every['items']), 1)
        first = self.get('access/release-roles?status=all')
        self.assertEqual(first, self.get('access/release-roles?status=all'))

    def test_role_list_csv_is_distinct_filtered_and_separate_from_assignment_export(self):
        response = self.client.get('/api/access/exports/release-roles?status=all&release_areas=E', headers=H)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.text.startswith(ROLE_LIST_HEADER))
        self.assertIn('sap-lens-release-role-list-review-', response.headers['content-disposition'])
        rows = list(csv.reader(io.StringIO(response.text.lstrip('﻿')), delimiter=';'))
        self.assertEqual(rows[0], ['ROLE_NAME', 'ROLE_DESCRIPTION', 'RELEASE_AREA', 'RELEASE_GROUP', 'RELEASE_STRATEGY', 'PR_PO'])
        self.assertEqual([r[0] for r in rows[1:]], ['ZO:MM:M:PO_REL_ST_E3_N2:ALL', 'ZO:MM:M:PR_REL_ST_E2_N1:ALL'])
        self.assertEqual(rows[1][2:], ['E', 'E3', 'N2', 'PO'])
        assignments = self.client.get('/api/access/exports/releases?status=all&release_areas=E', headers=H)
        self.assertIn('"USERNAME"', assignments.text.splitlines()[0])
        self.assertEqual(len(list(csv.reader(io.StringIO(assignments.text.lstrip('﻿')), delimiter=';'))) - 1, 3)
