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
from test_sod_governance import GovernanceCase, H, matrix

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

    def test_investigate_is_a_review_decision_that_stays_outstanding_and_can_be_resolved(self):
        items = self.picked(role_suffix='ENO')
        result = self.bulk(items, 'Investigate')
        self.assertEqual((len(result['recorded']), result['tracked_actions']), (1, []))
        self.assertEqual(self.listing(role_suffix='ENO')['items'][0]['decision'], 'Investigate')
        self.assertEqual(self.get('/api/sod/remediation', limit=100)['actions'], [])  # a decision alone creates no action
        repeat = self.bulk(items, 'Investigate')
        self.assertEqual((repeat['recorded'], repeat['skipped'][0]['reason']), ([], 'Already under investigation.'))
        history = lambda: self.get('/api/sod/decisions/assignment/history', key=items[0]['key'])['items']
        self.assertEqual(len(history()), 1)
        outstanding = self.get('/api/sod/queue/users', limit=100)
        self.assertEqual(sum(row['assignment']['decided'] for row in outstanding['items'] if row['user'] == 'U2'), 0)  # not a completed decision
        resolved = self.bulk(items, 'Remove')  # resolving needs no replacement confirmation
        self.assertEqual(len(resolved['recorded']), 1)
        self.assertEqual([event['decision'] for event in history()], ['Remove', 'Investigate'])  # the Investigate decision stays in the history

    def test_investigate_can_track_one_action_without_duplicates_and_keeps_states_separate(self):
        items = self.picked(role_suffix='ENO')
        first = self.bulk(items, 'Investigate', track_action=True)
        self.assertEqual(len(first['tracked_actions']), 1)
        self.bulk(items, 'Keep', replace_existing=True)
        again = self.bulk(items, 'Investigate', track_action=True, replace_existing=True)
        self.assertEqual((len(again['recorded']), again['tracked_actions']), (1, []))  # the open action is reused
        actions = [item for item in self.get('/api/sod/remediation', limit=100)['actions'] if item['recommended'] == 'Investigate assignment']
        self.assertEqual([(item['user'], item['role'], item['status']) for item in actions], [('U2', 'ZC:MM:SEL:ENO', 'Open')])
        rows = self.get('/api/sod/remediation', recommended='Investigate assignment', limit=100)['items']
        self.assertEqual((rows[0]['assignment_decision'], rows[0]['action_status'], rows[0]['verification']), ('Investigate', 'Open', 'Not verifiable from source evidence'))

    def test_investigate_is_filterable_and_reported(self):
        self.bulk(self.picked(role_suffix='ENO'), 'Investigate')
        self.assertEqual(self.roles(assignment_decision='Investigate'), [('U2', 'ZC:MM:SEL:ENO')])
        self.assertEqual(self.get('/api/sod/queue', kind='assignment', status='Investigate', limit=100)['total'], 1)
        text = self.client.get('/api/sod/explorer/access_list/export', params=dict(assignment_decision='Investigate'), headers=H).text
        self.assertIn('Investigate', text)

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


class IndependentDecisionTests(BulkCase):
    """Every role assignment keeps its own decision; decisions of one user's other assignments, bulk runs and history never mix."""

    def one(self, key_filter, decision, reviewer='Reviewer One', status=200, **extra):
        item = next(item for item in self.picked(usernames=['U1']) if item['ref'] == key_filter)
        view = self.get('/api/sod/matrix/risk')
        body = dict(context='current', expected_revision=view['revision'], expected_generation=view['generation'], items=[item], decision=decision,
                    reviewer=reviewer, justification=f'{decision} {key_filter}')
        body.update(extra)
        return item, self.post('/api/sod/decisions/assignment', body, status)

    def decisions_of(self, user_name='U1'):
        return {row['role']: row['decision'] for row in self.listing(usernames=[user_name])['items']}

    def test_assignments_of_one_user_hold_different_decisions_at_once(self):
        self.one('ZC:MM:BUY:CDK', 'Keep')
        self.one('ZC:MM:BUY:EMS', 'Remove')
        self.assertEqual(self.decisions_of(), {'ZC:MM:BUY:CDK': 'Keep', 'ZC:MM:BUY:EMS': 'Removal required', 'ZC:MM:SEL:CDK': 'Pending'})
        self.one('ZC:MM:SEL:CDK', 'Keep')
        self.assertEqual(self.decisions_of(), {'ZC:MM:BUY:CDK': 'Keep', 'ZC:MM:BUY:EMS': 'Removal required', 'ZC:MM:SEL:CDK': 'Keep'})

    def test_changing_one_decision_leaves_the_others_and_their_history_alone(self):
        def profile(name):
            current=self.get('/api/reviewer-profile')
            self.post('/api/reviewer-profile',dict(display_name=name,expected_revision=current['revision']))
        profile('Alice')
        keep, _ = self.one('ZC:MM:BUY:CDK', 'Keep', reviewer='Alice')
        profile('Bob')
        remove, _ = self.one('ZC:MM:BUY:EMS', 'Remove', reviewer='Bob')
        profile('Carol')
        self.one('ZC:MM:BUY:CDK', 'Remove', reviewer='Carol')
        self.assertEqual(self.decisions_of()['ZC:MM:BUY:EMS'], 'Removal required')
        self.assertEqual(self.decisions_of()['ZC:MM:BUY:CDK'], 'Removal required')
        first = self.get('/api/sod/decisions/assignment/history', key=keep['key'])['items']
        second = self.get('/api/sod/decisions/assignment/history', key=remove['key'])['items']
        self.assertEqual([(event['reviewer'], event['decision']) for event in first], [('Carol', 'Remove'), ('Alice', 'Keep')])
        self.assertEqual([(event['reviewer'], event['decision']) for event in second], [('Bob', 'Remove')])
        self.assertTrue(all(event['key'] == keep['key'] for event in first))

    def test_a_decision_is_keyed_by_assignment_not_by_username(self):
        self.one('ZC:MM:BUY:CDK', 'Keep')
        other = {row['role']: row['decision'] for row in self.listing(usernames=['U4'])['items']}
        self.assertEqual(set(other.values()), {'Pending'})
        self.assertEqual(sorted(row['decision'] for row in self.listing(role_suffix='CDK')['items']), ['Keep', 'Pending'])  # the other CDK assignment of the same user

    def test_bulk_review_leaves_unrelated_individual_decisions_untouched(self):
        self.one('ZC:MM:BUY:EMS', 'Remove', reviewer='Bob')
        before = self.decisions_of()
        result = self.bulk(self.picked(role_suffix='CDK'), 'Keep')
        self.assertEqual(len(result['recorded']), 2)
        after = self.decisions_of()
        self.assertEqual(after['ZC:MM:BUY:EMS'], before['ZC:MM:BUY:EMS'])
        self.assertEqual({role_name: value for role_name, value in after.items() if role_name.endswith(':CDK')}, {'ZC:MM:BUY:CDK': 'Keep', 'ZC:MM:SEL:CDK': 'Keep'})
        ems = next(item for item in self.picked(usernames=['U1']) if item['ref'] == 'ZC:MM:BUY:EMS')
        self.assertEqual(len(self.get('/api/sod/decisions/assignment/history', key=ems['key'])['items']), 1)


class ReviewStatusQueueTests(BulkCase):
    """The assignment queue filters individual assignments by review status; completed decisions leave the default view only."""

    def setUp(self):
        super().setUp()
        picked = {item['ref']: item for item in self.picked(usernames=['U1'])}
        self.bulk([picked['ZC:MM:BUY:CDK']], 'Keep')
        self.bulk([picked['ZC:MM:BUY:EMS']], 'Remove')
        self.bulk([picked['ZC:MM:SEL:CDK']], 'Investigate')

    def of(self, user_name='U1', **params):
        return sorted(row['role'] for row in self.listing(usernames=[user_name], **params)['items'])

    def test_default_attention_view_hides_only_completed_assignments_of_the_same_user(self):
        self.assertEqual(self.of(review_status='attention'), ['ZC:MM:SEL:CDK'])  # Investigate stays; Keep and Remove are completed
        self.assertEqual(self.of(review_status='reviewed'), ['ZC:MM:BUY:CDK', 'ZC:MM:BUY:EMS'])
        self.assertEqual(self.of(review_status='investigating'), ['ZC:MM:SEL:CDK'])
        self.assertEqual(self.of(review_status='pending'), [])
        self.assertEqual(self.of(review_status='all'), ['ZC:MM:BUY:CDK', 'ZC:MM:BUY:EMS', 'ZC:MM:SEL:CDK'])
        self.assertEqual(self.of(), self.of(review_status='all'))  # no status means no filtering for other views
        self.assertEqual(self.of('U2', review_status='attention'), ['ZC:MM:BUY:ES2', 'ZC:MM:SEL:ENO'])  # untouched users are pending

    def test_counts_pages_selection_and_export_follow_the_status_filter(self):
        params = dict(review_status='attention', role_suffixes=['CDK', 'ES2'])
        page = self.get('/api/sod/explorer/access_list', limit=1, **params)
        self.assertEqual(page['total'], 2)  # U1 SEL:CDK (investigating) and U2 BUY:ES2; U1 BUY:CDK is completed
        self.assertEqual(self.selection(**params)['total'], 2)
        lines = [line for line in self.get_multi('/api/sod/explorer/access_list/export', params).text.replace('\ufeff', '').splitlines() if line][1:]
        self.assertEqual(len(lines), 2)

    def test_progress_ignores_the_status_filter_and_does_not_double_count(self):
        progress = self.get('/api/sod/explorer/access_list', review_status='reviewed')['progress']
        self.assertEqual(progress, dict(total=10, completed=2, pending=7, investigating=1, outdated=0, attention=8, removal=1))

    def test_outdated_decisions_return_to_the_queue(self):
        self.bulk(self.picked(usernames=['U2'], role_suffix='ES2'), 'Keep')
        self.assertEqual(self.of('U2', review_status='attention'), ['ZC:MM:SEL:ENO'])
        changed = suffix_snapshot()
        changed.roles['ZC:MM:BUY:ENP'] = role(BUY, 'X1', 'X2')  # the catalogue role now also supplies the second activity: evidence changed
        cache._cache = changed
        self.assertIn('ZC:MM:BUY:ES2', self.of('U2', review_status='attention'))
        self.assertEqual(self.get('/api/sod/explorer/access_list', usernames=['U2'], review_status='all')['progress']['outdated'], 1)

    def test_export_keeps_each_individual_decision_and_the_assignment_identifier(self):
        text = self.get_multi('/api/sod/explorer/access_list/export', dict(usernames=['U1'], review_status='all')).text.replace('\ufeff', '')
        header, *lines = [line for line in text.splitlines() if line]
        self.assertTrue(header.endswith('"ASSIGNMENT_REVIEW";"ASSIGNMENT_ID";"ROLE_SUFFIX"'))
        by_role = {line.split(';')[1].strip('"'): line.split(';') for line in lines}
        self.assertEqual({role_name: fields[8].strip('"') for role_name, fields in by_role.items()},
                         {'ZC:MM:BUY:CDK': 'Keep', 'ZC:MM:BUY:EMS': 'Removal required', 'ZC:MM:SEL:CDK': 'Investigate'})
        ids = {fields[9].strip('"') for fields in by_role.values()}
        self.assertEqual(ids, {item['key'] for item in self.picked(usernames=['U1'], review_status='all')})

    def test_status_filter_is_saved_filter_compatible(self):
        response = self.client.post('/api/saved-filters', json=dict(name='Queue', view='sod_explorer', filters=dict(review_status='investigating')), headers=H)
        self.assertEqual(response.status_code, 200, response.text)


class MultiSelectScopeTests(BulkCase):
    """Every multi-select SoD filter is OR within and AND between filters, in matrices, explorer, selection and exports."""

    def users_in(self, **params):
        return sorted({row['user'] for row in self.get('/api/sod/matrix/risk', **params)['rows']})

    def test_groups_roles_activities_transactions_and_risks_combine_with_or(self):
        self.assertEqual(self.users_in(groups=['P2P']), ['U2'])
        self.assertEqual(self.users_in(groups=['FIN', 'P2P']), ['U1', 'U2', 'U3', 'U4'])
        self.assertEqual(self.users_in(roles=['ZC:MM:BUY:ES2', 'ZC:MM:BUY:ESH']), ['U2', 'U3'])
        self.assertEqual(self.users_in(roles=['ZC:MM:BUY:ES2', 'ZC:MM:BUY:ESH'], groups=['P2P']), ['U2'])  # AND between filters
        self.assertEqual(self.users_in(activities=['A', 'B']), ['U1', 'U2', 'U3', 'U4'])
        self.assertEqual(self.users_in(tcodes=['X1', 'X9']), ['U1', 'U2', 'U3', 'U4'])
        self.assertEqual(self.users_in(risks=['R1', 'R9']), ['U1', 'U2', 'U3', 'U4'])
        self.assertEqual(self.users_in(risks=['R9']), [])
        self.assertEqual(self.users_in(criticalities=['H', 'M'], categories=[]), ['U1', 'U2', 'U3', 'U4'])

    def test_assignment_lists_apply_multi_role_group_and_activity_filters_per_assignment(self):
        rows = self.listing(roles=['ZC:MM:BUY:CDK', 'ZC:MM:SEL:ENO'])['items']
        self.assertEqual(sorted((row['user'], row['role']) for row in rows), [('U1', 'ZC:MM:BUY:CDK'), ('U2', 'ZC:MM:SEL:ENO')])
        self.assertEqual(self.selection(roles=['ZC:MM:BUY:CDK', 'ZC:MM:SEL:ENO'])['total'], 2)
        self.assertEqual(len(self.listing(groups=['P2P'], activities=['B'])['items']), 1)  # only U2's SEL:ENO supplies B in P2P

    def test_filter_options_are_scoped_by_the_other_multi_selects(self):
        self.assertEqual(self.get('/api/sod/filter-options', field='group', roles=['ZC:MM:BUY:ES2'])['items'], ['P2P'])
        self.assertEqual(self.get('/api/sod/filter-options', field='role', groups=['P2P'])['items'], ['ZC:MM:BUY:ES2', 'ZC:MM:SEL:ENO'])

    def test_conflict_pages_honor_multi_values_too(self):
        users = lambda **params: sorted({item['subject'] for item in self.get('/api/sod/analysis', kind='users', limit=100, **params)['items']})
        self.assertEqual(users(usernames=['U1', 'U3']), ['U1', 'U3'])
        self.assertEqual(users(groups=['P2P']), ['U2'])
        self.assertEqual(users(risks=['R1'], usernames=['U4']), ['U4'])


if __name__ == '__main__':
    unittest.main()

class AtomicQueueReviewTests(GovernanceCase):
    def selection(self,**filters):
        return self.get('/api/sod/explorer/access_list/selection',review_status='all',**filters)
    def body(self,selection,action='Keep',**extra):
        return dict(context='current',expected_revision=selection['revision'],expected_generation=selection['generation'],atomic=True,action=action,
                    reviewer='Synthetic Reviewer',justification='Synthetic atomic review',items=[{key:row[key] for key in ('key','user','ref','evidence_version')} for row in selection['items']],**extra)
    def test_explicit_role_modes_do_not_change_group_semantics(self):
        self.assertEqual(self.selection(role='ROLE_A',role_match='exact')['total'],0)
        self.assertEqual(self.selection(role='ROLE_AB',role_match='exact')['total'],1)
        self.assertEqual(self.selection(role='ROLE_A',role_match='prefix',groups=['FIN'])['total'],2)
        self.assertEqual(self.selection(role='ROLE_A*',role_match='wildcard',groups=['FIN'])['total'],2)
        self.assertEqual(self.selection(role='ROLE_*',role_match='wildcard',groups=['FI*'])['total'],0)
    def test_atomic_invalid_selection_has_no_partial_decisions(self):
        selected=self.selection(usernames=['SYN_A']);body=self.body(selected)
        body['items'][0]['key']='f'*64
        self.post('/api/sod/decisions/assignment/bulk',body,409)
        self.assertEqual(decisions.read().revision,0)
    def test_operation_history_replay_and_explicit_overwrite(self):
        selected=self.selection(usernames=['SYN_B']);body=self.body(selected)
        first=self.post('/api/sod/decisions/assignment/bulk',body)
        self.assertEqual(len(first['operation_id']),32)
        self.post('/api/sod/decisions/assignment/bulk',body,409)
        second_selection=self.selection(usernames=['SYN_B'])
        self.post('/api/sod/decisions/assignment/bulk',self.body(second_selection,'Remove'),409)
        second=self.post('/api/sod/decisions/assignment/bulk',self.body(second_selection,'Remove',replace_existing=True))
        events=decisions.history('assignment','current',selected['items'][0]['key'])
        self.assertEqual(len(events),2);self.assertEqual(events[1]['bulk_operation_id'],first['operation_id'])
        self.assertEqual(events[0]['previous_decision'],'Keep');self.assertEqual(events[0]['bulk_operation_id'],second['operation_id'])
    def test_large_atomic_operation_commits_one_revision_and_uses_bounded_body(self):
        import test_sod_governance as core
        from unittest.mock import patch
        cache._cache=core.snapshot(extra_users={f'SYN_ATOMIC_{i:03}':core.user('ROLE_AB') for i in range(105)})
        selected=self.selection(role='ROLE_AB',role_match='exact')
        self.assertGreater(len(selected['items']),100)
        with patch.object(decisions,'_write',wraps=decisions._write) as write:
            result=self.post('/api/sod/decisions/assignment/bulk',self.body(selected))
            self.assertEqual(write.call_count,1)
        self.assertEqual(len(result['recorded']),len(selected['items']));self.assertEqual(result['revision'],selected['revision']+1)
        response=self.client.post('/api/sod/decisions/assignment/bulk',headers=H,content=b'x'*2_000_001)
        self.assertEqual(response.status_code,413)
    def test_atomic_storage_failure_preserves_previous_review_index(self):
        from unittest.mock import patch
        from fastapi import HTTPException
        selected=self.selection(usernames=['SYN_A'])
        with patch.object(decisions,'_write',side_effect=HTTPException(409,'Synthetic storage failure')):
            self.post('/api/sod/decisions/assignment/bulk',self.body(selected),409)
        self.assertEqual(decisions.read().revision,0)
        self.assertFalse(decisions.read().contexts)
    def test_authenticated_actor_overrides_entered_bulk_reviewer(self):
        from server_access import ACTOR
        token=ACTOR.set('SyntheticAuthenticated')
        try:
            result=decisions.record('assignment','current',[dict(key='a'*64,user='SYN_AUTH',ref='ROLE_AUTH',evidence_version='b'*64,evidence={})],
                'Keep','SpoofedReviewer','Synthetic authentication evidence',0,bulk_operation_id='c'*32)
            self.assertEqual(result['events'][0]['reviewer'],'SyntheticAuthenticated')
        finally:ACTOR.reset(token)
    def test_atomic_investigation_requires_explicit_replacement(self):
        self.decide('assignment',[self.assignment_item('SYN_B','ROLE_AB')],'Investigate')
        selected=self.selection(usernames=['SYN_B'])
        self.assertTrue(selected['items'][0]['has_review'])
        self.assertEqual(selected['items'][0]['previous_decision'],'Investigate')
        revision=decisions.read().revision
        self.post('/api/sod/decisions/assignment/bulk',self.body(selected),409)
        self.assertEqual(decisions.read().revision,revision)
        self.post('/api/sod/decisions/assignment/bulk',self.body(selected,replace_existing=True))
        self.assertEqual(decisions.history('assignment','current',selected['items'][0]['key'])[0]['previous_decision'],'Investigate')

    def test_atomic_outdated_review_is_not_silently_overwritten(self):
        self.decide('assignment',[self.assignment_item('SYN_B','ROLE_AB')],'Keep')
        data=decisions.read();key=self.assignment_item('SYN_B','ROLE_AB')['key']
        previous=data.contexts['current']['assignment'][key][-1]
        data.contexts['current']['assignment'][key][-1]=previous.model_copy(update={'evidence_version':'f'*64})
        decisions._write(data) # synthetic prior evidence version, never a production history edit
        selected=self.selection(usernames=['SYN_B'])
        self.assertEqual(selected['items'][0]['decision'],'Outdated')
        self.assertTrue(selected['items'][0]['has_review'])
        self.post('/api/sod/decisions/assignment/bulk',self.body(selected),409)
        self.assertEqual(decisions.read().revision,data.revision)

    def test_selection_rejects_revision_change_during_preview(self):
        from unittest.mock import patch
        import sod_scope as scope
        with patch.object(scope,'revision',side_effect=[0,1]):
            response=self.client.get('/api/sod/explorer/access_list/selection',headers=H)
        self.assertEqual(response.status_code,409,response.text)


class CompleteAssignmentReviewTests(BulkCase):
    def setUp(self):
        super().setUp()
        fresh=suffix_snapshot()
        fresh.roles['ZC:MM:READ:ENP']=role('ZC:MM:READ:ENP','X9')
        fresh.users.users['U_ONLY']=person(('ZC:MM:READ:CDK','ZC:MM:READ:ENP'))
        fresh.users.users['U1']['assignments'].append(held('ZC:MM:READ:CDK','ZC:MM:READ:ENP'))
        fresh.users.users['U_EXPIRED']=person(('ZC:MM:READ:CDK','ZC:MM:READ:ENP'))
        fresh.users.users['U_EXPIRED']['assignments'][0]['valid_to']='2000-01-01'
        cache._cache=fresh

    def all_selection(self,**params):
        return self.selection(assignment_scope='all',**params)

    def test_all_population_includes_active_assignments_without_conflicts(self):
        before=self.get('/api/sod/matrix/risk')
        selected=self.all_selection(role_suffix='CDK')
        self.assertIn(('U_ONLY','ZC:MM:READ:CDK'),[(row['user'],row['ref']) for row in selected['items']])
        self.assertIn(('U1','ZC:MM:READ:CDK'),[(row['user'],row['ref']) for row in selected['items']])
        self.assertNotIn('U_EXPIRED',[row['user'] for row in selected['items']])
        self.assertNotIn('U_ONLY',[row['user'] for row in before['rows']])
        self.assertEqual(self.get('/api/sod/matrix/risk')['rows'],before['rows'])
        listing=self.listing(assignment_scope='all',role_suffix='CDK')
        self.assertEqual(listing['total'],selected['total'])
        exported=self.client.get('/api/sod/explorer/access_list/export',headers=H,params={'assignment_scope':'all','role_suffix':'CDK'})
        self.assertEqual(exported.status_code,200)
        self.assertIn('U_ONLY',exported.text)

    def test_atomic_keep_remove_investigate_preserve_individual_history(self):
        selected=self.all_selection(role_exact=['ZC:MM:READ:CDK'])
        for action in ('Keep','Remove','Investigate'):
            result=self.bulk([{key:row[key] for key in ('key','user','ref','evidence_version')} for row in selected['items']],action,atomic=True,replace_existing=True)
            self.assertEqual(len(result['recorded']),2)
            self.assertEqual((result['failed'],result['skipped']),([],[]))
            history=self.get('/api/sod/decisions/assignment/history',key=selected['items'][0]['key'])['items']
            self.assertEqual(history[0]['decision'],action)
            self.assertEqual(history[0]['bulk_operation_id'],result['operation_id'])
        subject=self.subject('U_ONLY')
        self.assertEqual(subject['overview']['risks'],[])
        self.assertEqual(subject['overview']['activities'],[])
        self.assertEqual(subject['overview']['assignments'][0]['decision'],'Investigate')

    def test_source_replacement_rejects_frozen_preview_atomically(self):
        selected=self.all_selection(role_suffix='CDK')
        before=decisions.read().model_dump()
        cache._cache=copy.deepcopy(cache._cache)
        self.bulk([{key:row[key] for key in ('key','user','ref','evidence_version')} for row in selected['items']],'Remove',status=409,atomic=True,expected_generation=selected['generation'])
        self.assertEqual(decisions.read().model_dump(),before)

    def test_legacy_exact_filters_do_not_expand_to_a_family(self):
        exact=self.all_selection(roles=['ZC:MM:BUY:CDK'],role_match='exact')
        self.assertEqual({row['ref'] for row in exact['items']},{'ZC:MM:BUY:CDK'})
        family=self.all_selection(role_families=['ZC:MM:BUY:*'])
        self.assertGreater(family['total'],exact['total'])
        self.assertNotIn('ZC:MM:BUY:EMS',{row['ref'] for row in family['items']}) # No organizational evidence for this suffix: retained as an exact option.

    def test_base_role_or_suffix_or_and_filters_are_shared(self):
        selected=self.all_selection(role_families=['ZC:MM:BUY:*','ZC:MM:SEL:*'],role_suffixes=['CDK','ENP'])
        self.assertTrue(selected['items'])
        self.assertTrue(all(row['ref'].endswith((':CDK',':ENP')) for row in selected['items']))
        self.assertTrue(all(row['ref'].startswith(('ZC:MM:BUY:','ZC:MM:SEL:')) for row in selected['items']))
        self.assertEqual({row['ref'] for row in self.all_selection(role_families=['ZC:MM:BUY:*'],role_suffix='CDK')['items']},{'ZC:MM:BUY:CDK'})
        self.assertEqual(self.all_selection(role_families=['ZC:MM:BUY:*'],role_suffix='DK')['total'],0)
        scoped=self.all_selection(role_families=['ZC:MM:BUY:*'],groups=['P2P'])
        self.assertTrue(all(row['user_group']=='P2P' for row in scoped['items']))

    def test_family_options_are_compact_but_opaque_and_unrecognized_roles_stay_exact(self):
        options=self.get('/api/sod/filter-options',field='role',group_roles=True,assignment_scope='all')
        self.assertIn('ZC:MM:BUY:*',options['items'])
        self.assertNotIn('ZC:MM:BUY:CDK',options['items'])
        self.assertIn('ZC:MM:BUY:XCDK',options['items'])
        from access_package import role_families
        self.assertEqual(role_families(['OTHER:ROLE:CDK','ZO:OPAQUE:CODE:CDK','NO_SUFFIX']),{})
        self.assertEqual(role_families(['ZC:MM:READ:*','ZC:*:READ:CDK']),{'ZC:MM:READ:*':'ZC:MM:READ:*'})
        self.assertEqual(self.all_selection(role_exact=['ZC:MM:BUY:XCDK'])['total'],1)

    def test_selection_is_independent_of_display_pagination(self):
        fresh=copy.deepcopy(cache._cache)
        for index in range(65):fresh.users.users[f'U_PAGE_{index:03d}']=person(('ZC:MM:READ:CDK','ZC:MM:READ:ENP'))
        cache._cache=fresh
        selected=self.all_selection(role_exact=['ZC:MM:READ:CDK'])
        response=self.get('/api/sod/explorer/access_list',assignment_scope='all',role_exact=['ZC:MM:READ:CDK'],limit=50)
        self.assertEqual(len(response['items']),50)
        self.assertEqual(selected['total'],67)
        self.assertEqual(len(selected['items']),67)

    def test_period_snapshot_isolated_from_later_imports_and_frozen_decisions(self):
        revision=self.get('/api/sod/periods')['revision']
        period=self.post('/api/sod/periods',dict(name='Synthetic complete scope',start='2026-01-01',end='2026-12-31',evaluation_date='2026-10-27',expected_revision=revision))['period']['id']
        selected=self.get('/api/sod/explorer/access_list/selection',context=period,assignment_scope='all',role_exact=['ZC:MM:READ:CDK'])
        self.assertEqual(selected['total'],2)
        cache._cache=suffix_snapshot()
        retained=self.get('/api/sod/explorer/access_list/selection',context=period,assignment_scope='all',role_exact=['ZC:MM:READ:CDK'])
        self.assertEqual(retained['items'],selected['items'])
        body=dict(context=period,expected_revision=selected['revision'],expected_generation=selected['generation'],items=[{key:row[key] for key in ('key','user','ref','evidence_version')} for row in selected['items']],action='Keep',atomic=True,reviewer='Synthetic Reviewer',justification='Synthetic period review')
        self.post('/api/sod/decisions/assignment/bulk',body)
        self.assertEqual(self.get('/api/sod/explorer/access_list/selection',assignment_scope='all',role_exact=['ZC:MM:READ:CDK'])['total'],0)

    def test_saved_exact_and_family_definitions_round_trip_without_conversion(self):
        exact=dict(roles=['ZC:MM:BUY:CDK'],role_match='exact',assignment_scope='all')
        family=dict(role_families=['ZC:MM:BUY:*'],role_suffixes=['CDK'],assignment_scope='all')
        for index,definition in enumerate((exact,family)):
            self.post('/api/saved-filters',dict(name=f'Synthetic scope {index}',view='sod_queue',filters=definition))
        saved=self.get('/api/saved-filters')['items']
        self.assertEqual([row['filters'] for row in saved],[exact,family])
        for row in saved:
            restored=self.get('/api/sod/explorer/access_list/selection',**row['filters'])
            self.assertEqual({item['ref'] for item in restored['items']},{'ZC:MM:BUY:CDK'})

    def test_assignment_identifier_cannot_be_relabeled_in_a_bulk_body(self):
        selected=self.all_selection(role_exact=['ZC:MM:READ:CDK'])
        items=[{key:row[key] for key in ('key','user','ref','evidence_version')} for row in selected['items']]
        items[-1]['ref']='SYN_UNRELATED_ROLE'
        before=decisions.read().model_dump()
        self.bulk(items,'Remove',status=409,atomic=True)
        self.assertEqual(decisions.read().model_dump(),before)

    def test_nonconflict_decision_synchronizes_queue_overview_remediation_and_export(self):
        before=self.get('/api/sod/overview')['governance']
        selected=self.all_selection(usernames=['U_ONLY'])
        self.bulk([{key:row[key] for key in ('key','user','ref','evidence_version')} for row in selected['items']],'Remove',atomic=True)
        queue=self.get('/api/sod/queue/users',usernames=['U_ONLY'])['items']
        self.assertEqual(len(queue),1)
        self.assertEqual(queue[0]['assignment'],dict(total=1,decided=1))
        self.assertEqual(queue[0]['activity'],dict(total=0,decided=0))
        self.assertEqual(queue[0]['removal'],1)
        after=self.get('/api/sod/overview')['governance']
        self.assertEqual(after['users_with_conflicts'],before['users_with_conflicts'])
        self.assertEqual(after['acceptance'],before['acceptance'])
        self.assertEqual(after['review_coverage']['assignment']['reviewed'],before['review_coverage']['assignment']['reviewed']+1)
        rows=self.get('/api/sod/remediation',usernames=['U_ONLY'])['items']
        self.assertEqual(len(rows),1)
        self.assertEqual((rows[0]['activity'],rows[0]['risks'],rows[0]['recommended']),('',[],'Remove assignment'))
        self.assertIsNone(rows[0]['activity_summary'])
        self.assertEqual(rows[0]['assignment_summary']['label'],'Remove')
        for path in ('/api/sod/queue/export','/api/sod/remediation/export'):
            response=self.client.get(path,headers=H,params={'usernames':'U_ONLY'})
            self.assertEqual(response.status_code,200)
            self.assertIn('U_ONLY',response.text)
        tracked=self.post('/api/sod/remediation/actions',dict(context='current',expected_revision=decisions.read().revision,actor='Synthetic Reviewer',user='U_ONLY',assignment_id=selected['items'][0]['key'],role=selected['items'][0]['ref'],recommended='Remove assignment',reason='Synthetic follow-up',owner='Synthetic Owner'))
        self.assertTrue(tracked)

    def test_full_assignment_period_progress_and_report_retain_nonconflict_decisions(self):
        import sod_periods as periods
        import sod_reports as reports
        revision=self.get('/api/sod/periods')['revision']
        period=self.post('/api/sod/periods',dict(name='Synthetic assignment report',start='2026-01-01',end='2026-12-31',evaluation_date='2026-10-27',expected_revision=revision))['period']['id']
        selected=self.get('/api/sod/explorer/access_list/selection',context=period,assignment_scope='all',usernames=['U_ONLY'])
        body=dict(context=period,expected_revision=selected['revision'],expected_generation=selected['generation'],atomic=True,action='Remove',reviewer='Synthetic Reviewer',justification='Synthetic follow-up',items=[{key:row[key] for key in ('key','user','ref','evidence_version')} for row in selected['items']])
        self.post('/api/sod/decisions/assignment/bulk',body)
        record=periods.read().items[0]
        self.assertEqual(periods.outstanding(record)['assignment'].get('Removal required'),1)
        report=reports.remediation_model(period,reports.RemediationOptions())
        self.assertIn('U_ONLY',str(report))
        self.assertIn('Remove assignment',str(report))
        self.assertTrue(reports.render_docx(report).startswith(b'PK'))
        self.assertTrue(reports.render_pdf(report).startswith(b'%PDF'))

    def test_legacy_period_queue_keeps_retained_scope_without_using_current_assignments(self):
        from unittest.mock import patch
        import sod_scope as scope
        revision=self.get('/api/sod/periods')['revision']
        period=self.post('/api/sod/periods',dict(name='Synthetic legacy scope',start='2026-01-01',end='2026-12-31',evaluation_date='2026-10-27',expected_revision=revision))['period']['id']
        retained=dict(scope.load(period),assignment_source=None)
        with patch.object(scope,'load',return_value=retained):
            queue=self.get('/api/sod/queue/users',context=period)
            self.assertNotIn('U_ONLY',[row['user'] for row in queue['items']])
            self.assertEqual(self.get('/api/sod/remediation',context=period)['items'],[])
            response=self.client.get('/api/sod/explorer/access_list/selection',headers=H,params={'context':period,'assignment_scope':'all'})
            self.assertEqual(response.status_code,409)


    def test_eligibility_counts_cover_the_complete_scope_even_when_preview_is_truncated(self):
        from unittest.mock import patch
        selected=self.all_selection(usernames=['U_ONLY'])
        self.bulk([{key:row[key] for key in ('key','user','ref','evidence_version')} for row in selected['items']],'Keep',atomic=True)
        with patch('routers.sod_governance.SELECTION_LIMIT',1):
            result=self.all_selection(role_exact=['ZC:MM:READ:CDK'])
        self.assertEqual(result['total'],2)
        self.assertTrue(result['truncated'])
        self.assertEqual(len(result['items']),1)
        self.assertEqual(result['eligible_counts']['Keep'],dict(unreviewed=1,include_reviewed=1))
        self.assertEqual(result['eligible_counts']['Remove'],dict(unreviewed=1,include_reviewed=2))
        self.assertEqual(result['eligible_counts']['Investigate'],dict(unreviewed=1,include_reviewed=2))
