"""Bulk Functional Group assignment (adds memberships): previews, one-write commits, explicit per-user outcomes, idempotent overlaps, concurrency, staleness, audit and permissions."""
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_role_negative_tcode import TransactionFilterCase, H
import functional_groups as fg
from server_access import may_access

BASE = '/api/functional-groups'


class Bulk(TransactionFilterCase):
    def setUp(self):
        super().setUp()
        self.a = self.client.post(BASE, headers=H, json={'name': 'Purchasing', 'description': ''}).json()['id']
        self.b = self.client.post(BASE, headers=H, json={'name': 'Logistics', 'description': ''}).json()['id']

    def post(self, path, **body):
        return self.client.post(BASE + path, headers=H, json=body)

    def preview(self, groups, names):
        groups = [groups] if isinstance(groups, str) else groups
        return self.post('/bulk/preview', group_ids=groups, usernames=names).json()

    def assign(self, groups, names, expected=None, **extra):
        groups = [groups] if isinstance(groups, str) else groups
        revisions = expected if expected is not None else {item['username']: item['revision'] for item in self.preview(groups, names)['items']}
        return self.post('/bulk', group_ids=groups, usernames=names, expected=revisions, rationale='bulk', reviewer='Admin One',
                         operation_id=extra.pop('operation_id', uuid.uuid4().hex), **extra)

    def groups_of(self, username):
        return sorted(self.client.get(f'{BASE}/users/{username}', headers=H).json()['classification']['group_ids'])

    def group_of(self, username):
        found = self.groups_of(username)
        return found[0] if len(found) == 1 else (None if not found else found)

    def test_preview_separates_additions_from_memberships_already_held(self):
        self.assign(self.a, ['U1']); self.assign(self.b, ['U2'])
        preview = self.preview([self.a, self.b], ['U1', 'U2', 'U3', 'u3', 'GHOST'])
        self.assertEqual(preview['counts'], {'users': 3, 'additions': 4, 'existing': 2, 'unassigned': 1})
        self.assertEqual(preview['missing'], ['GHOST'])
        self.assertEqual(preview['requested'], 4)                      # the duplicate u3 is one user
        rows = {i['username']: i for i in preview['items']}
        self.assertEqual((rows['U1']['existing'], rows['U1']['additions']), ([self.a], [self.b]))
        self.assertEqual((rows['U3']['existing'], rows['U3']['additions']), ([], [self.a, self.b]))

    def test_unassigned_users_are_assigned_in_one_write_with_audit_history(self):
        with patch.object(fg, 'write', wraps=fg.write) as write:
            result = self.assign(self.a, ['U1', 'U3', 'U4']).json()
        self.assertEqual((result['status'], len(result['applied']), result['conflicts'], result['unchanged']), ('applied', 3, [], []))
        self.assertEqual(write.call_count, 1)                           # the whole applied set is committed together
        self.assertEqual({self.group_of(n) for n in ('U1', 'U3', 'U4')}, {self.a})
        history = fg.read()['history']
        events = [h for h in history if h['change_id'] == result['operation_id']]
        self.assertEqual(sorted(h['username'] for h in events), ['U1', 'U3', 'U4'])
        self.assertTrue(all((h['event'], h['previous_group'], h['new_group'], h['actor']) == ('assigned', None, self.a, 'Admin One') and h['timestamp'] for h in events))

    def test_several_groups_are_added_together_and_existing_memberships_are_kept(self):
        self.assign(self.b, ['U1', 'U2'])
        result = self.assign([self.a, self.b], ['U1', 'U2', 'U3']).json()
        self.assertEqual(result['status'], 'applied')
        self.assertEqual(self.groups_of('U1'), sorted([self.a, self.b]))           # Logistics kept, Purchasing added
        self.assertEqual(self.groups_of('U3'), sorted([self.a, self.b]))
        by_user = {r['username']: r for r in result['applied']}
        self.assertEqual((by_user['U1']['added'], by_user['U1']['unchanged']), ([self.a], [self.b]))   # overlap is an idempotent no-op
        self.assertEqual(len([h for h in fg.read()['history'] if h['username'] == 'U1']), 2)          # one original + one new event, no duplicates

    def test_users_already_in_every_group_are_unchanged_and_write_nothing(self):
        self.assign(self.a, ['U1'])
        with patch.object(fg, 'write') as write:
            result = self.assign(self.a, ['U1']).json()
        self.assertEqual((result['status'], [u['username'] for u in result['unchanged']], result['applied']), ('applied', ['U1'], []))
        write.assert_not_called()

    def test_replacement_is_not_supported_and_changes_nothing(self):
        self.assign(self.b, ['U1'])
        response = self.assign(self.a, ['U1'], replace_existing=True)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.group_of('U1'), self.b)

    def test_the_legacy_single_group_field_still_works_and_adds(self):
        self.assign(self.b, ['U1'])
        response = self.post('/bulk', group_id=self.a, usernames=['U1'], expected={'U1': 1}, rationale='', reviewer='Admin One', operation_id='legacy-op-1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.groups_of('U1'), sorted([self.a, self.b]))

    def test_invalid_archived_and_unknown_groups_change_nothing(self):
        self.assertEqual(self.post('/bulk', group_ids=['nope'], usernames=['U1'], expected={}, operation_id='x' * 12, reviewer='A').status_code, 404)
        self.client.post(f'{BASE}/{self.b}/archive', headers=H)
        self.assertEqual(self.assign(self.b, ['U1'], expected={'U1': 0}).status_code, 409)
        self.assertEqual(self.group_of('U1'), None)
        self.assertEqual(self.post('/bulk', group_ids=[], usernames=['U1'], expected={}, operation_id='y' * 12, reviewer='A').status_code, 422)

    def test_missing_users_are_rejected_visibly_and_never_mistaken_for_success(self):
        result = self.assign(self.a, ['U1', 'GHOST'], expected={'U1': 0}).json()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual([r['username'] for r in result['rejected']], ['GHOST'])
        self.assertEqual(self.group_of('U1'), self.a)

    def test_duplicates_are_applied_once(self):
        result = self.assign(self.a, ['U1', 'u1', 'U1'], expected={'U1': 0}).json()
        self.assertEqual(len(result['applied']), 1)
        self.assertEqual(len([h for h in fg.read()['history'] if h['username'] == 'U1']), 1)

    def test_a_concurrent_change_is_a_conflict_for_that_user_only(self):
        seen = {item['username']: item['revision'] for item in self.preview(self.a, ['U1', 'U3'])['items']}
        self.client.post(f'{BASE}/memberships', headers=H, json={'username': 'U1', 'group_id': self.b, 'rationale': 'other admin', 'reviewer': 'Admin Two', 'expected_revision': 0})
        result = self.assign(self.a, ['U1', 'U3'], expected=seen).json()
        self.assertEqual((result['status'], [c['username'] for c in result['conflicts']], [c['reason'] for c in result['conflicts']]), ('partial', ['U1'], ['changed']))
        self.assertEqual((self.group_of('U1'), self.group_of('U3')), (self.b, self.a))

    def test_a_dataset_published_after_the_selection_is_refused_outright(self):
        revision = self.preview(self.a, ['U1'])['data_revision']
        import cache
        cache._cache = cache._CacheState(users=cache.get_snapshot().users, roles=cache.get_snapshot().roles)     # a publication
        response = self.assign(self.a, ['U1'], expected={'U1': 0}, data_revision=revision)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['detail']['code'], 'stale_dataset')
        self.assertIsNone(self.group_of('U1'))

    def test_a_repeated_operation_is_refused(self):
        self.assign(self.a, ['U1'], operation_id='operation-1')
        self.assertEqual(self.assign(self.a, ['U3'], operation_id='operation-1').status_code, 409)
        self.assertIsNone(self.group_of('U3'))

    def test_a_failing_write_leaves_the_store_unchanged(self):
        with patch.object(fg, 'write', side_effect=OSError('disk full')):
            response = self.assign(self.a, ['U1', 'U3'], expected={'U1': 0, 'U3': 0})
        self.assertEqual(response.status_code, 500)                      # reported as a failure, never as a partial success
        self.assertEqual((self.group_of('U1'), self.group_of('U3'), fg.read()['history']), (None, None, []))

    def test_a_full_history_stops_the_whole_operation(self):
        with patch.object(fg, 'MAX_HISTORY', 1):
            response = self.assign(self.a, ['U1', 'U3'], expected={'U1': 0, 'U3': 0})
        self.assertEqual(response.status_code, 409)
        self.assertEqual((self.group_of('U1'), self.group_of('U3')), (None, None))

    def test_only_administrators_may_assign(self):
        self.assertTrue(may_access('administrator', 'POST', BASE + '/bulk'))
        for role in ('reviewer', 'viewer', 'auditor'):
            self.assertFalse(may_access(role, 'POST', BASE + '/bulk'), role)
            self.assertFalse(may_access(role, 'POST', BASE + '/bulk/preview'), role)

    def test_a_reviewer_name_is_required(self):
        response = self.post('/bulk', group_ids=[self.a], usernames=['U1'], expected={'U1': 0}, operation_id='o' * 10, reviewer='')
        self.assertEqual(response.status_code, 422)

    def test_the_selection_endpoint_lists_the_filtered_usernames_in_order(self):
        everyone = self.client.get('/api/access/users-selection', headers=H).json()
        self.assertEqual((everyone['total'], everyone['truncated']), (len(everyone['usernames']), False))
        self.assertEqual(everyone['usernames'], sorted(everyone['usernames']))
        filtered = self.client.get('/api/access/users-selection?group=G2&descending=true', headers=H).json()
        self.assertEqual(set(filtered['usernames']), self.users('group=G2'))
        listed = self.client.get('/api/access/users-selection?usernames=u1,U3', headers=H).json()
        self.assertEqual(listed['usernames'], ['U1', 'U3'])
        self.assertRegex(listed['data_revision'], r'^[a-f0-9]+\.\d+\.\d+$')

    def test_the_directory_listing_shows_the_assignment_afterwards(self):
        self.assign(self.a, ['U1'])
        items = {i['username']: i for i in self.client.get('/api/access/users?limit=100', headers=H).json()['items']}
        self.assertEqual(items['U1']['functional_group']['id'], self.a)
        self.assertEqual([g['id'] for g in items['U1']['functional_groups']], [self.a])


if __name__ == '__main__':
    unittest.main()
