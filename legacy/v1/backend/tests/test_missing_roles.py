"""Reverse user filtering by roles: Missing ANY (lacks at least one) and Missing ALL (lacks every selected role)."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_role_negative_tcode import TransactionFilterCase

A, B = 'ZC:MM:A', 'ZC:FI:B'


class MissingRoleTests(TransactionFilterCase):
    def test_missing_any_lists_users_lacking_at_least_one_selected_role(self):
        self.assertEqual(self.users(f'missing_roles={A}&missing_roles={B}&missing_mode=any'), {'U1', 'U2', 'U3', 'U4'})

    def test_missing_all_lists_users_lacking_every_selected_role(self):
        self.assertEqual(self.users(f'missing_roles={A}&missing_roles={B}&missing_mode=all'), {'U3', 'U4'})

    def test_one_role_gives_the_same_result_for_both_operators(self):
        for mode in ('any', 'all'):
            self.assertEqual(self.users(f'missing_roles={A}&missing_mode={mode}'), {'U2', 'U3', 'U4'})

    def test_incomplete_evidence_is_never_reported_as_missing_access(self):
        listed = self.users(f'missing_roles={A}&missing_roles={B}&missing_mode=any')
        self.assertFalse({'U5', 'U7'} & listed)  # unmapped assignments may hold anything
        self.assertNotIn('U6', listed)  # only an expired assignment, so no current evidence

    def test_validity_follows_the_expired_toggle(self):
        self.assertEqual(self.users(f'missing_roles={A}&missing_roles={B}&missing_mode=any&show_expired=true') - {'U1', 'U2', 'U3', 'U4'}, {'U6'})
        self.assertNotIn('U6', self.users(f'missing_roles={A}&missing_roles={B}&missing_mode=all&show_expired=true'))

    def test_combines_with_group_and_search_and_the_export_follows_the_listing(self):
        self.assertEqual(self.users(f'missing_roles={A}&missing_mode=any&group=G2'), {'U3', 'U4'})
        self.assertEqual(self.users(f'missing_roles={A}&missing_mode=any&search=U3'), {'U3'})
        rows = self.export(f'missing_roles={A}&missing_roles={B}&missing_mode=all')
        self.assertEqual({row['USERNAME'] for row in rows}, {'U3', 'U4'})

    def test_invalid_operator_is_rejected_and_empty_selection_changes_nothing(self):
        self.assertEqual(self.client.get('/api/access/users?missing_mode=some', headers={'X-SAP-Lens': '1'}).status_code, 422)
        self.assertEqual(self.users('missing_mode=all'), self.users(''))


if __name__ == '__main__':
    unittest.main()
