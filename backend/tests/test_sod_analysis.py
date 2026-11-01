import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from models import RoleDetail, SingleRole, TCode, AssignmentSource
from sod_analysis import analyze
from sod_import import build_sod


def role(name, *codes):
    return RoleDetail(agr_name=name, tcode_count=len(codes), single_roles=[SingleRole(child_agr='SINGLE', tcodes=[TCode(tcode=c, assignment_sources=[AssignmentSource(child_agr='SINGLE', parent_agr=name)]) for c in codes])])


def assignment(name, start='2020-01-01', end='9999-12-31', match='exact'):
    return dict(role_name=name, catalogue_roles=[name], match_status=match, valid_from=start, valid_to=end, user_group='SYNTHETIC')


def snapshot():
    base = dict(RISK='SYNTHETIC', CRITICITY='H', TYPE='S', TEXT='Synthetic definition', ACTVT1='A', ACTVT2='B', TTEXT='Synthetic')
    sod = build_sod([dict(base, ACTIVITY_SLOT='ACTVT1', ACTIVITY='A', TCODE='X1'), dict(base, ACTIVITY_SLOT='ACTVT2', ACTIVITY='B', TCODE='X2')])
    user = dict(assignments=[assignment('ROLE_A'), assignment('ROLE_B')], accounts=[dict(valid_from='2020-01-01', valid_to='9999-12-31', locked=True)], emails={'user@example.invalid'})
    return SimpleNamespace(sod=sod, roles={'ROLE_A': role('ROLE_A', 'X1'), 'ROLE_B': role('ROLE_B', 'X2')}, users=SimpleNamespace(users={'USER': user}), directory=None, last_loaded=None)


class SodAnalysisTests(unittest.TestCase):
    def run_analysis(self, value=None, **kwargs):
        return analyze(value or snapshot(), as_of=date(2026, 10, 27), **kwargs)

    def test_cross_role_evidence_and_explicit_combination(self):
        result = self.run_analysis(selected_roles=['ROLE_A', 'ROLE_B'])
        self.assertEqual(len(result['users']), 1)
        self.assertTrue(result['users'][0]['current_potential'])
        self.assertEqual(result['users'][0]['evidence']['ACTVT1'][0]['actual_assigned_role'], 'ROLE_A')
        self.assertEqual(result['roles'][0]['kind'], 'role_combination')
        self.assertFalse(result['roles'][0]['current_potential'])
        self.assertEqual(result['users'][0]['account']['ad_status'], 'Unknown')

    def test_one_side_and_intrinsic_role(self):
        value = snapshot()
        value.users.users['USER']['assignments'] = [assignment('ROLE_A')]
        self.assertFalse(self.run_analysis(value)['users'])
        value.roles['ROLE_A'] = role('ROLE_A', 'X1', 'X2')
        result = self.run_analysis(value)
        self.assertEqual(len(result['users']), 1)
        self.assertEqual(len(result['roles']), 1)

    def test_validity_missing_future_expired_and_maximum(self):
        for start, end, status in [('2020-01-01', '2021-01-01', 'expired'), ('2030-01-01', '9999-12-31', 'future'), ('', '9999-12-31', 'unknown')]:
            with self.subTest(status=status):
                value = snapshot()
                value.users.users['USER']['assignments'][1].update(valid_from=start, valid_to=end)
                self.assertFalse(self.run_analysis(value)['users'])
                result = self.run_analysis(value, validity='all')['users'][0]
                self.assertFalse(result['current_potential'])
                self.assertEqual(result['evidence']['ACTVT2'][0]['interval_status'], status)
        self.assertTrue(self.run_analysis()['users'][0]['current_potential'])

    def test_wildcard_duplicates_and_distinct_intervals(self):
        value = snapshot()
        item = value.users.users['USER']['assignments'][0]
        item.update(role_name='ROLE_A_EN', match_status='wildcard')
        value.users.users['USER']['assignments'].extend([dict(item), dict(item, valid_from='2022-01-01')])
        evidence = self.run_analysis(value)['users'][0]['evidence']['ACTVT1']
        self.assertEqual(len(evidence), 2)
        self.assertEqual(evidence[0]['matching_status'], 'wildcard')
        self.assertEqual(evidence[0]['matched_catalogue_pattern'], 'ROLE_A')
        item['match_status'] = 'ambiguous'
        value.users.users['USER']['assignments'] = [item, assignment('ROLE_B')]
        self.assertFalse(self.run_analysis(value)['users'])

    def test_disabled_unsupported_and_missing_sources(self):
        self.assertFalse(self.run_analysis(metadata={'SYNTHETIC': {'local': {'enabled': False}}})['users'])
        value = snapshot()
        value.sod['risks'][0]['supported'] = False
        self.assertFalse(self.run_analysis(value)['users'])
        value = snapshot()
        value.roles['ROLE_A'] = role('ROLE_A', 'X1', 'X2')
        result = self.run_analysis(value, mapping_enabled=False)
        self.assertFalse(result['users'])
        self.assertEqual(result['coverage']['reason'], 'mapping_disabled')
        self.assertTrue(result['roles'])
        value.sod = {}
        self.assertEqual(self.run_analysis(value)['coverage']['status'], 'unavailable')

    def test_fingerprint_stability_and_relevant_change(self):
        value = snapshot()
        original = self.run_analysis(value)['users'][0]
        value.last_loaded = datetime(2026, 10, 28)
        value.sod['content_hash'] = 'unrelated-revision'
        value.roles['OTHER'] = role('OTHER', 'OTHER')
        value.users.users['USER']['assignments'].reverse()
        result = self.run_analysis(value)['users'][0]
        self.assertEqual(original['evidence_version'], result['evidence_version'])
        value.users.users['USER']['assignments'][0]['valid_from'] = '2022-01-01'
        changed = self.run_analysis(value)['users'][0]
        self.assertEqual(original['finding_id'], changed['finding_id'])
        self.assertNotEqual(original['evidence_version'], changed['evidence_version'])

    def test_overlap_same_transaction_retains_both_sides(self):
        value = snapshot()
        value.sod['risks'][0]['activities']['ACTVT2'][0]['tcode'] = 'X1'
        result = self.run_analysis(value)['users'][0]
        self.assertEqual(result['evidence']['ACTVT1'][0]['tcode'], result['evidence']['ACTVT2'][0]['tcode'])

    def test_case_insensitive_transactions_preserve_both_identifiers(self):
        value = snapshot()
        value.roles['ROLE_A'] = role('ROLE_A', 'x1')
        evidence = self.run_analysis(value)['users'][0]['evidence']['ACTVT1'][0]
        self.assertEqual(evidence['tcode'], 'x1')
        self.assertEqual(evidence['matrix_transaction'], 'X1')

    def test_selected_roles_reject_unknown_and_oversized_lists(self):
        with self.assertRaises(ValueError):
            self.run_analysis(selected_roles=['ROLE_A', 'MISSING'])
        with self.assertRaises(ValueError):
            self.run_analysis(selected_roles=['ROLE_A'] * 26)
        value = snapshot()
        value.users.users['USER']['assignments'][0]['match_status'] = 'unmapped'
        coverage = self.run_analysis(value)['coverage']
        self.assertTrue(coverage['roles_available'])
        self.assertEqual(coverage['unmapped_assignment_records'], 1)

    def test_explicit_noncurrent_validity_filters(self):
        for start, end, status in [('2020-01-01', '2021-01-01', 'expired'), ('2030-01-01', '9999-12-31', 'future'), ('', '9999-12-31', 'unknown')]:
            with self.subTest(status=status):
                value = snapshot()
                for item in value.users.users['USER']['assignments']:
                    item.update(valid_from=start, valid_to=end)
                findings = self.run_analysis(value, validity=status)['users']
                self.assertEqual(len(findings), 1)
                self.assertFalse(findings[0]['current_potential'])
                self.assertTrue(all(item['interval_status'] == status for sides in findings[0]['evidence'].values() for item in sides))

    def test_directory_unique_resolution_does_not_filter_disabled(self):
        value = snapshot()
        value.directory = SimpleNamespace(match=lambda emails: {'status': 'matched', 'employee': {'account_status': 'Disabled'}})
        result = self.run_analysis(value, directory_enabled=True)['users'][0]
        self.assertEqual(result['account']['ad_status'], 'Disabled')
        self.assertTrue(result['current_potential'])
        self.assertTrue(result['account']['accounts'][0]['locked'])


if __name__ == '__main__':
    unittest.main()
