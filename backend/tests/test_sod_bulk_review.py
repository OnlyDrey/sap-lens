"""SoD Access Explorer: exact role suffix filtering, multi-value filters and batch assignment review."""
import copy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cache
import sod_decisions as decisions
from user_access import UserState
from test_sod_analysis_api import role, assignment
from test_sod_governance import GovernanceCase, H, matrix, user

BUY, SEL = 'ZC:MM:BUY:ENP', 'ZC:MM:SEL:ENP'


def held(name, catalogue, group='FIN'):
    return dict(assignment(name, group=group), catalogue_roles=[catalogue])


def person(*pairs, group='FIN'):
    return dict(assignments=[held(name, catalogue, group) for name, catalogue in pairs],
                accounts=[dict(valid_from='2020-01-01', valid_to='9999-12-31', locked=False)], emails=set())


def suffix_snapshot():
    """Every user holds a BUY-side and a SEL-side role (activities A and B of risk R1); suffixes vary per assignment."""
    users = {
        'U1': person(('ZC:MM:BUY:CDK', BUY), ('ZC:MM:BUY:EMS', BUY), ('ZC:MM:SEL:CDK', SEL)),
        'U2': person(('ZC:MM:BUY:ES2', BUY), ('ZC:MM:SEL:ENO', SEL), group='P2P'),
        'U3': person(('ZC:MM:BUY:ESH', BUY), ('ZC:MM:SEL:ENP', SEL), ('ZC:MM:BUY:ENP', BUY)),
        'U4': person(('ZC:MM:BUY:XCDK', BUY), ('ZC:MM:SEL:ENP', SEL)),  # a substring trap: its token is XCDK
    }
    return cache._CacheState(sod=matrix(), roles={BUY: role(BUY, 'X1'), SEL: role(SEL, 'X2')}, users=UserState(users=users),
                             last_loaded=datetime(2026, 10, 27, tzinfo=timezone.utc))


class BulkCase(GovernanceCase):
    def setUp(self):
        super().setUp()
        cache._cache = suffix_snapshot()

    def listing(self, **params):
        return self.get('/api/sod/explorer/access_list', limit=200, **params)

    def roles(self, **params):
        return sorted((row['user'], row['role']) for row in self.listing(**params)['items'])

    def get_multi(self, path, params):
        response = self.client.get(path, params=params, headers=H)
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def selection(self, **params):
        return self.get('/api/sod/explorer/access_list/selection', **params)

    def bulk(self, items, action, status=200, **extra):
        view = self.get('/api/sod/matrix/risk')
        body = dict(context='current', expected_revision=view['revision'], expected_generation=view['generation'], items=items, action=action,
                    reviewer='Synthetic Reviewer', justification='Synthetic cleanup rationale')
        body.update(extra)
        return self.post('/api/sod/decisions/assignment/bulk', body, status)

    def picked(self, **params):
        return [dict(key=row['key'], user=row['user'], ref=row['ref'], evidence_version=row['evidence_version']) for row in self.selection(**params)['items']]


class SuffixFilterTests(BulkCase):
    def test_a_suffix_returns_only_assignments_whose_own_role_ends_in_that_token(self):
        rows = self.roles(role_suffix='CDK')
        self.assertEqual(rows, [('U1', 'ZC:MM:BUY:CDK'), ('U1', 'ZC:MM:SEL:CDK')])
        for other in ('EMS', 'ES2', 'ENO', 'ESH'):
            self.assertFalse([row for row in rows if row[1].endswith(':' + other)])

    def test_matching_is_an_exact_token_never_a_substring_or_catalogue_sibling(self):
        self.assertEqual(self.roles(role_suffix='DK'), [])
        self.assertEqual(self.roles(role_suffix='XCDK'), [('U4', 'ZC:MM:BUY:XCDK')])
        self.assertEqual(self.roles(role_suffix='cdk'), self.roles(role_suffix='CDK'))
        # ENP belongs to the catalogue patterns of every user, yet only the actual ENP assignments qualify.
        self.assertEqual(self.roles(role_suffix='ENP'), [('U3', 'ZC:MM:BUY:ENP'), ('U3', 'ZC:MM:SEL:ENP'), ('U4', 'ZC:MM:SEL:ENP')])

    def test_multiple_suffixes_use_or_and_combine_with_other_filters_using_and(self):
        both = self.roles(role_suffixes=['CDK', 'EMS'])
        self.assertEqual(both, [('U1', 'ZC:MM:BUY:CDK'), ('U1', 'ZC:MM:BUY:EMS'), ('U1', 'ZC:MM:SEL:CDK')])
        self.assertEqual(self.roles(role_suffixes=['CDK', 'ENO', 'ESH', 'ES2']),
                         [('U1', 'ZC:MM:BUY:CDK'), ('U1', 'ZC:MM:SEL:CDK'), ('U2', 'ZC:MM:BUY:ES2'), ('U2', 'ZC:MM:SEL:ENO'), ('U3', 'ZC:MM:BUY:ESH')])
        self.assertEqual(self.roles(role_suffixes=['CDK', 'ENP'], group='P2P'), [])
        self.assertEqual(self.roles(role_suffixes=['CDK', 'ES2', 'ENP'], usernames=['U1', 'U3']),
                         [('U1', 'ZC:MM:BUY:CDK'), ('U1', 'ZC:MM:SEL:CDK'), ('U3', 'ZC:MM:BUY:ENP'), ('U3', 'ZC:MM:SEL:ENP')])

    def test_multiple_usernames_are_exact_and_or(self):
        self.assertEqual({user_name for user_name, _ in self.roles(usernames=['U1', 'U2'])}, {'U1', 'U2'})
        self.assertEqual({row['user'] for row in self.get('/api/sod/explorer/user_risk', usernames=['U4'])['items']}, {'U4'})
        self.assertEqual(self.roles(usernames=['U']), [])

    def test_counts_pagination_selection_and_csv_use_the_same_dataset(self):
        params = dict(role_suffixes=['CDK', 'EMS'], usernames=['U1'])
        page = self.get('/api/sod/explorer/access_list', limit=2, **params)
        self.assertEqual((page['total'], len(page['items'])), (3, 2))
        self.assertEqual(self.get('/api/sod/explorer/access_list', limit=2, offset=2, **params)['items'][0]['role'], 'ZC:MM:SEL:CDK')
        selection = self.selection(**params)
        self.assertEqual((selection['total'], selection['truncated']), (3, False))
        self.assertEqual(sorted(item['key'] for item in selection['items']), sorted(row['id'] for row in self.listing(**params)['items']))
        self.assertEqual({item['suffix'] for item in selection['items']}, {'CDK', 'EMS'})
        text = self.get_multi('/api/sod/explorer/access_list/export', params).text
        lines = [line for line in text.replace('﻿', '').splitlines() if line][1:]
        self.assertEqual(len(lines), 3)
        self.assertFalse([line for line in lines if 'ES2' in line or 'ENO' in line or 'ESH' in line])

    def test_shared_views_apply_the_same_assignment_level_filter(self):
        lookup = {row['role'] for row in self.get('/api/sod/explorer/lookup', role_suffix='CDK')['items']}
        self.assertEqual(lookup, {'ZC:MM:BUY:CDK', 'ZC:MM:SEL:CDK'})
        queue = [item['ref'] for item in self.get('/api/sod/queue', kind='assignment', role_suffix='CDK', limit=100)['items']]
        self.assertEqual(sorted(queue), ['ZC:MM:BUY:CDK', 'ZC:MM:SEL:CDK'])
        options = self.get('/api/sod/filter-options', field='role_suffix')['items']
        self.assertEqual(options, sorted(['CDK', 'EMS', 'ES2', 'ENO', 'ESH', 'ENP', 'XCDK'], key=lambda value: (value.casefold(), value)))
        self.assertEqual(self.get('/api/sod/matrix/risk', role_suffixes=['ES2'])['totals']['users'], 1)

    def test_filter_options_follow_the_other_active_filters_but_never_their_own_field(self):
        self.assertEqual(self.get('/api/sod/filter-options', field='role_suffix', usernames=['U2'])['items'], ['ENO', 'ES2'])
        self.assertEqual(self.get('/api/sod/filter-options', field='role_suffix', usernames=['U2'], role_suffixes=['ENO'])['items'], ['ENO', 'ES2'])
        self.assertEqual(self.get('/api/sod/filter-options', field='username', role_suffix='CDK')['items'], ['U1'])
        self.assertEqual(self.get('/api/sod/filter-options', field='username', role_suffixes=['CDK', 'ES2'])['items'], ['U1', 'U2'])

    def test_assignment_decision_filter_lists_only_assignments_with_that_decision(self):
        self.bulk(self.picked(role_suffix='EMS'), 'Keep')
        self.assertEqual(self.roles(assignment_decision='Keep'), [('U1', 'ZC:MM:BUY:EMS')])


class BulkReviewTests(BulkCase):
    def history(self, key):
        return self.get('/api/sod/decisions/assignment/history', key=key)['items']

    def test_batch_keep_uses_individual_events_and_updates_review_status(self):
        items = self.picked(role_suffixes=['CDK'])
        result = self.bulk(items, 'Keep')
        self.assertEqual((len(result['recorded']), result['skipped'], result['failed']), (2, [], []))
        decisions_by_role = {row['role']: row['decision'] for row in self.listing()['items']}
        self.assertEqual({role_name: value for role_name, value in decisions_by_role.items() if role_name.endswith(':CDK')}, {'ZC:MM:BUY:CDK': 'Keep', 'ZC:MM:SEL:CDK': 'Keep'})
        self.assertEqual(decisions_by_role['ZC:MM:BUY:EMS'], 'Pending')
        for item in items:
            events = self.history(item['key'])
            self.assertEqual(len(events), 1)
            self.assertEqual((events[0]['reviewer'], events[0]['decision'], events[0]['justification']), ('Synthetic Reviewer', 'Keep', 'Synthetic cleanup rationale'))

    def test_recommend_removal_marks_assignments_without_changing_sap_evidence(self):
        before = copy.deepcopy(cache._cache.users.users)
        result = self.bulk(self.picked(role_suffixes=['ES2', 'ESH']), 'Remove')
        self.assertEqual(len(result['recorded']), 2)
        self.assertEqual(sorted(row['role'] for row in self.listing(assignment_decision='Removal required')['items']), ['ZC:MM:BUY:ES2', 'ZC:MM:BUY:ESH'])
        self.assertEqual(cache._cache.users.users, before)
        remediation = self.get('/api/sod/remediation', recommended='Remove assignment', limit=100)
        self.assertEqual(sorted({row['role'] for row in remediation['items']}), ['ZC:MM:BUY:ES2', 'ZC:MM:BUY:ESH'])

    def test_existing_decisions_are_protected_until_replacement_is_confirmed(self):
        items = self.picked(role_suffix='CDK')
        self.bulk(items, 'Keep')
        revision = decisions.read().revision
        again = self.bulk(items, 'Remove')
        self.assertEqual((again['recorded'], len(again['skipped'])), ([], 2))
        self.assertIn('Already reviewed', again['skipped'][0]['reason'])
        self.assertEqual(decisions.read().revision, revision)
        replaced = self.bulk(items, 'Remove', replace_existing=True)
        self.assertEqual(len(replaced['recorded']), 2)
        events = self.history(items[0]['key'])
        self.assertEqual([event['decision'] for event in events], ['Remove', 'Keep'])  # earlier history is preserved

    def test_investigate_tracks_one_action_per_assignment_without_deciding_it(self):
        items = self.picked(role_suffix='ENO')
        result = self.bulk(items, 'Investigate')
        self.assertEqual(len(result['recorded']), 1)
        remediation = self.get('/api/sod/remediation', limit=100)
        actions = [item for item in remediation['actions'] if item['recommended'] == 'Investigate assignment']
        self.assertEqual([(item['user'], item['role'], item['status']) for item in actions], [('U2', 'ZC:MM:SEL:ENO', 'Open')])
        self.assertEqual(self.listing(role_suffix='ENO')['items'][0]['decision'], 'Pending')
        repeat = self.bulk(items, 'Investigate')
        self.assertEqual((repeat['recorded'], len(repeat['skipped'])), ([], 1))

    def test_partial_failures_are_reported_per_assignment_and_only_valid_items_persist(self):
        good = self.picked(role_suffix='CDK')
        stale = dict(self.picked(role_suffix='ENO')[0], evidence_version='f' * 64)
        missing = dict(good[0], key='e' * 64, ref='ZC:MM:BUY:GONE')
        result = self.bulk([*good, stale, missing], 'Keep')
        self.assertEqual(len(result['recorded']), 2)
        self.assertEqual(sorted(item['reason'] for item in result['failed']),
                         ['Evidence changed since the selection was made.', 'No longer supported by current evidence.'])
        self.assertEqual({row['role']: row['decision'] for row in self.listing(role_suffix='ENO')['items']}, {'ZC:MM:SEL:ENO': 'Pending'})

    def test_stale_state_and_invalid_requests_change_nothing(self):
        items = self.picked(role_suffix='CDK')
        view = self.get('/api/sod/matrix/risk')
        body = dict(context='current', expected_revision=view['revision'], expected_generation=view['generation'], items=items, action='Keep',
                    reviewer='R', justification='x')
        self.post('/api/sod/decisions/assignment/bulk', dict(body, expected_generation='b' * 64), 409)
        self.post('/api/sod/decisions/assignment/bulk', dict(body, expected_revision=view['revision'] + 5), 409)
        self.post('/api/sod/decisions/assignment/bulk', dict(body, justification=''), 422)
        self.post('/api/sod/decisions/assignment/bulk', dict(body, action='Pending'), 422)
        self.post('/api/sod/decisions/assignment/bulk', dict(body, items=[items[0], items[0]]), 422)
        self.assertEqual(decisions.read().revision, view['revision'])

    def test_selection_after_a_filter_change_is_an_explicit_list_of_stable_identifiers(self):
        wide = self.picked(role_suffixes=['CDK', 'EMS'])
        narrow = self.picked(role_suffixes=['CDK'])
        self.assertTrue({item['key'] for item in narrow} < {item['key'] for item in wide})
        result = self.bulk(narrow, 'Keep')
        self.assertEqual(len(result['recorded']), len(narrow))
        self.assertEqual(self.listing(role_suffix='EMS')['items'][0]['decision'], 'Pending')

    def test_bulk_review_requires_the_application_capability(self):
        response = self.client.post('/api/sod/decisions/assignment/bulk', json={})
        self.assertIn(response.status_code, (401, 403))
        self.assertIn(self.client.get('/api/sod/explorer/access_list/selection').status_code, (401, 403))


if __name__ == '__main__':
    unittest.main()
