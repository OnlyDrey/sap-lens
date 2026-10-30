"""Proposed access package: suffix replacement, validation, deterministic export. Nothing here changes SAP access."""
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
import access_package
import cache
import config
from main import create_app

H = {'X-SAP-Lens': '1'}
NAMES = ['ZC:MM:BUY:ENP', 'ZC:FI:VIEW:ENP', 'ZC:FI:VIEW:ENK', 'ZC:SD:ORD:ENK', 'ZC:MM:BUY:*', 'ZC:SD:ORD:EN*', 'ZC:HR:MISC:XYZ', 'ZO:MM:M:REL:ALL', 'ZC:SD:LONG_ROLE_NAME_FOR_SAP:ENP']
CATALOGUE = 'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT\n' + ''.join(f'MM,{name},Description of {name},ZS:{i},MM,MIGO,Goods\n' for i, name in enumerate(NAMES))


class PureRules(unittest.TestCase):
    known = access_package.naming_evidence(NAMES)

    def test_naming_evidence_uses_business_roles_used_under_several_stems(self):
        self.assertEqual(self.known, {'ENP': 3, 'ENK': 2})

    def test_replaces_organizational_and_wildcard_suffixes(self):
        self.assertEqual(access_package.propose('ZC:MM:BUY:ENP', 'ENS', self.known)[:2], ('ZC:MM:BUY:ENS', 'organizational'))
        self.assertEqual(access_package.propose('ZC:MM:BUY:*', 'ENO', self.known)[:2], ('ZC:MM:BUY:ENO', 'wildcard'))
        self.assertEqual(access_package.propose('ZC:SD:ORD:EN*', 'ENS', self.known)[:2], ('ZC:SD:ORD:ENS', 'wildcard'))

    def test_ambiguous_structures_are_never_rewritten_silently(self):
        for source, suffix in (('ZC:SD:ORD:EN*', 'XX'), ('ZC:*:X*', 'ENP'), ('ZC:A**', 'ENP')):
            name, kind, message = access_package.propose(source, suffix, self.known)
            self.assertEqual((name, kind), (None, 'ambiguous'), source)
            self.assertTrue(message)

    def test_suffix_eligibility_follows_role_patterns_not_the_last_character(self):
        kinds = {name: access_package.suffix_kind(name, self.known) for name in ('ZC:MM:BUY:ENP', 'ZC:MM:BUY:*', 'ZC:SD:ORD:EN*', 'ZC:HR:MISC:XYZ', 'PLAIN', 'ZC:HR:MISC:ENX')}
        self.assertEqual(kinds, {'ZC:MM:BUY:ENP': 'organizational', 'ZC:MM:BUY:*': 'wildcard', 'ZC:SD:ORD:EN*': 'wildcard', 'ZC:HR:MISC:XYZ': None, 'PLAIN': None, 'ZC:HR:MISC:ENX': None})
        # exact roles keep their name whatever suffix is offered
        self.assertEqual(access_package.propose('ZC:HR:MISC:XYZ', 'ENP', self.known), ('ZC:HR:MISC:XYZ', 'exact', None))

    def test_sap_role_name_rules(self):
        self.assertIsNone(access_package.name_error('ZC:MM:BUY:ENP'))
        for bad in ('ZC:MM:BUY:enp', 'ZC::BUY', 'ZC:MM:', 'ZC:SD:LONG_ROLE_NAME_FOR_SAP:ENP', 'ZC MM', 'ZC:MM:BUY$'):
            self.assertTrue(access_package.name_error(bad), bad)


class PackageApi(unittest.TestCase):
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

    def preview(self, default='', **overrides):
        roles = overrides.pop('roles', ['ZC:MM:BUY:ENP', 'ZC:MM:BUY:*'])
        body = dict(default_suffix=default, items=[dict(role=role, suffix=overrides.get(role, '')) for role in roles])
        response = self.client.post('/api/roles/package/preview', json=body, headers=H)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_naming_endpoint_reports_detected_suffixes(self):
        data = self.client.get('/api/roles/naming', headers=H).json()
        self.assertEqual(data['suffixes'], [dict(value='ENP', roles=3), dict(value='ENK', roles=2)])

    def test_default_suffix_with_explicit_overrides_validation_and_catalogue_matches(self):
        data = self.preview('enk', **{'ZC:MM:BUY:*': 'ENP'})
        first, second = data['items']
        self.assertEqual((first['name'], first['suffix'], first['suffix_source'], first['status']), ('ZC:MM:BUY:ENK', 'ENK', 'default', 'ok'))
        self.assertEqual(first['catalogue'], dict(status='wildcard', candidates=['ZC:MM:BUY:*']))
        self.assertEqual((second['name'], second['suffix_source'], second['catalogue']['status']), ('ZC:MM:BUY:ENP', 'override', 'exact'))
        self.assertEqual(data['exportable'], 2)
        again = self.preview('ENS', **{'ZC:MM:BUY:*': 'ENP'})['items']
        self.assertEqual([item['name'] for item in again], ['ZC:MM:BUY:ENS', 'ZC:MM:BUY:ENP'])  # changing the default keeps overrides

    def test_statuses_for_missing_suffix_unknown_role_ambiguity_syntax_length_and_duplicates(self):
        rows = self.preview('', roles=['ZC:MM:BUY:ENP']) ['items']
        self.assertEqual(rows[0]['status'], 'needs_suffix')
        rows = self.preview('ENP', roles=['ZC:NOT:THERE', 'ZC:HR:MISC:XYZ', 'ZC:SD:LONG_ROLE_NAME_FOR_SAP:ENP', 'ZC:MM:BUY:ENP', 'ZC:MM:BUY:*'])['items']
        self.assertEqual([row['status'] for row in rows], ['unknown_role', 'ok', 'invalid', 'ok', 'duplicate'])
        self.assertEqual([row['validation'] for row in rows], ['invalid', 'confirmed', 'invalid', 'confirmed', 'invalid'])
        exact = rows[1]  # an exact role without suffix variants keeps its name and cannot take a suffix
        self.assertEqual((exact['name'], exact['suffix'], exact['suffix_eligible'], exact['exportable']), ('ZC:HR:MISC:XYZ', '', False, True))
        self.assertIn('no suffix variants', exact['suffix_note'])
        self.assertTrue(rows[3]['suffix_eligible'])
        self.assertIn('Same generated name as ZC:MM:BUY:ENP', rows[4]['messages'][0])
        self.assertEqual(self.preview('bad suffix!')['items'][0]['status'], 'invalid')
        rows = self.preview('ENP', roles=['ZC:MM:BUY:ENP'])['items']
        self.assertEqual(rows[0]['catalogue']['status'], 'exact')
        rows = self.preview('ENQ', roles=['ZC:FI:VIEW:ENP'])['items']
        self.assertEqual(rows[0]['name'], 'ZC:FI:VIEW:ENQ')
        self.assertEqual(rows[0]['catalogue']['status'], 'unmapped')  # a proposed name that is not in the catalogue
        self.assertEqual((rows[0]['validation'], rows[0]['exportable']), ('unconfirmed', True))  # valid syntax, not confirmed: usable with a warning
        self.assertIn('not confirmed', rows[0]['messages'][-1])
        rows = self.preview('', roles=['ZC:MM:BUY:ENP', 'ZC:HR:MISC:XYZ'])['items']
        self.assertEqual([(r['validation'], r['exportable']) for r in rows], [('needs_suffix', False), ('confirmed', True)])

    def test_export_is_deterministic_unique_escaped_and_never_includes_invalid_rows(self):
        body = dict(default_suffix='ENS', items=[dict(role='ZC:MM:BUY:ENP'), dict(role='ZC:FI:VIEW:ENP'), dict(role='ZC:MM:BUY:*'), dict(role='ZC:HR:MISC:XYZ'), dict(role='ZC:NOT:THERE')])
        response = self.client.post('/api/roles/package/export', json=body, headers=H)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertRegex(response.headers['content-disposition'], r'sap-lens-access-package-\d{4}-\d{2}-\d{2}\.csv')
        self.assertTrue(response.text.startswith('﻿"Generated SAP Role Name";"Role Description";"Suffix";"Validation"\r\n'))
        rows = list(csv.reader(io.StringIO(response.text.lstrip('﻿')), delimiter=';'))
        self.assertEqual([row[0] for row in rows[1:]], ['ZC:FI:VIEW:ENS', 'ZC:HR:MISC:XYZ', 'ZC:MM:BUY:ENS'])  # unknown source roles are never exported
        self.assertEqual(rows[1], ['ZC:FI:VIEW:ENS', 'Description of ZC:FI:VIEW:ENP', 'ENS', 'Unconfirmed'])
        self.assertEqual(rows[2], ['ZC:HR:MISC:XYZ', 'Description of ZC:HR:MISC:XYZ', '', 'Confirmed'])
        nothing = self.client.post('/api/roles/package/export', json=dict(default_suffix='', items=[dict(role='ZC:MM:BUY:ENP')]), headers=H)
        self.assertEqual(nothing.status_code, 422)
        many = self.client.post('/api/roles/package/preview', json=dict(items=[dict(role=f'ZC:BULK:{n}') for n in range(450)]), headers=H)
        self.assertEqual(many.status_code, 200)  # no application limit on the number of package roles
        self.assertEqual(len(many.json()['items']), 450)
        self.assertEqual(self.client.post('/api/roles/package/preview', json=dict(items=[], extra=1), headers=H).status_code, 422)
        self.assertEqual(self.client.post('/api/roles/package/preview', json=dict(items=[])).status_code, 403)


class MixedPackage(unittest.TestCase):
    """Release roles join the package under their exact technical names; the catalogue rules never touch them."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(self.root), 'DATA_CSV_PATH': ''})
        self.env.start(); config.get_settings.cache_clear(); cache.clear_cache()
        roles, users = self.root / 'roles.csv', self.root / 'users.csv'
        roles.write_text(CATALOGUE)
        users.write_text('USERNAME,ROLE_NAME,USER_GROUP,ROLE_VALID_FROM,ROLE_VALID_TO\nDEMO_ONE,ZO:MM:M:PR_REL_ST_E2_N1:ALL,G1,20200101,99991231\nDEMO_ONE,ZO:MM:M:PO_REL_ST_N1_N2:ENP,G1,20200101,99991231\n')
        self.client = TestClient(create_app(session_token='1'), base_url='http://127.0.0.1:18743')
        settings = config.get_settings().model_dump(); settings.update(data_csv_path=str(roles), user_csv_path=str(users))
        self.client.post('/api/configuration', headers=H, json=settings).raise_for_status()

    def tearDown(self):
        cache.clear_cache(); config.get_settings.cache_clear(); self.env.stop(); self.temp.cleanup()

    def post(self, path, items, default='ENS'):
        return self.client.post('/api/roles/package/' + path, json=dict(default_suffix=default, items=items), headers=H)

    def test_release_roles_keep_exact_names_next_to_suffix_replaced_catalogue_roles(self):
        items = [dict(role='ZC:MM:BUY:ENP'), dict(role='ZO:MM:M:PR_REL_ST_E2_N1:ALL', source='release'), dict(role='ZO:MM:M:PO_REL_ST_N1_N2:ENP', source='release', suffix='XYZ')]
        rows = self.post('preview', items).json()['items']
        self.assertEqual([(r['name'], r['source'], r['status']) for r in rows], [('ZC:MM:BUY:ENS', 'catalogue', 'ok'), ('ZO:MM:M:PR_REL_ST_E2_N1:ALL', 'release', 'ok'), ('ZO:MM:M:PO_REL_ST_N1_N2:ENP', 'release', 'ok')])
        self.assertEqual(rows[2]['suffix'], '')  # neither the default nor an override replaces a release suffix
        exported = list(csv.reader(io.StringIO(self.post('export', items).text.lstrip('\ufeff')), delimiter=';'))
        self.assertEqual([r[0] for r in exported[1:]], ['ZC:MM:BUY:ENS', 'ZO:MM:M:PO_REL_ST_N1_N2:ENP', 'ZO:MM:M:PR_REL_ST_E2_N1:ALL'])

    def test_unknown_duplicate_and_wildcard_release_items_are_not_exported(self):
        items = [dict(role='ZO:MM:M:PR_REL_ST_E2_N1:ALL', source='release'), dict(role='zo:mm:m:pr_rel_st_e2_n1:all', source='release'),
                 dict(role='ZO:MM:M:PR_REL_ST_X9_N1:ALL', source='release'), dict(role='ZO:MM:M:*', source='release'), dict(role='ZC:MM:BUY:ENP', source='release')]
        rows = self.post('preview', items).json()['items']
        self.assertEqual([r['status'] for r in rows], ['ok', 'duplicate', 'unknown_role', 'unknown_role', 'unknown_role'])
        self.assertEqual(self.post('preview', items).json()['exportable'], 1)
        self.assertEqual(self.post('preview', [dict(role='X', source='other')]).status_code, 422)


if __name__ == '__main__':
    unittest.main()
