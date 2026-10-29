"""SoD 2.0: matrices, activity/assignment/risk-acceptance decisions, what-if impact and remediation."""
import copy
from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
import cache
import config
from config_models import SourceSnapshot
from main import create_app
from sod_import import build_sod
import sod_decisions as decisions
import sod_governance as governance
from user_access import UserState
from test_sod_analysis_api import role, assignment

H = {'X-SAP-Lens': 'synthetic-governance-session'}


def matrix(extra=False):
    rows = []
    for risk, a1, a2, c1, c2 in (('R1', 'A', 'B', 'X1', 'X2'), ('R2', 'A', 'C', 'X1', 'X3')):
        base = dict(RISK=risk, CRITICITY='H', TYPE='S', TEXT='Synthetic ' + risk, ACTVT1=a1, ACTVT2=a2, TTEXT='Synthetic')
        rows += [dict(base, ACTIVITY_SLOT='ACTVT1', ACTIVITY=a1, TCODE=c1), dict(base, ACTIVITY_SLOT='ACTVT2', ACTIVITY=a2, TCODE=c2)]
        if extra and risk == 'R1':
            rows.append(dict(base, ACTIVITY_SLOT='ACTVT1', ACTIVITY=a1, TCODE='X5'))
    return build_sod(rows)


def user(*roles, group='FIN'):
    return dict(assignments=[assignment(name, group=group) for name in roles], accounts=[dict(valid_from='2020-01-01', valid_to='9999-12-31', locked=False)], emails=set())


def snapshot(extra_users=None, tcodes=None, extra=False):
    tcodes = tcodes or {}
    roles = {'ROLE_A1': role('ROLE_A1', 'X1'), 'ROLE_A2': role('ROLE_A2', 'X1'), 'ROLE_B': role('ROLE_B', 'X2'), 'ROLE_C': role('ROLE_C', 'X3'),
             'ROLE_AB': role('ROLE_AB', 'X1', 'X2', *tcodes.get('ROLE_AB', []))}
    users = {'SYN_A': user('ROLE_A1', 'ROLE_A2', 'ROLE_B', 'ROLE_C'), 'SYN_B': user('ROLE_AB', group='P2P'), 'SYN_C': user('ROLE_A1', group='P2P')}
    users.update(extra_users or {})
    return cache._CacheState(sod=matrix(extra), roles=roles, users=UserState(users=users), last_loaded=datetime(2026, 10, 27, tzinfo=timezone.utc))


class GovernanceCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(self.root), 'DATA_CSV_PATH': ''})
        self.env.start()
        config.get_settings.cache_clear()
        cache.clear_cache()
        cache._cache = snapshot()
        settings = config.get_settings().model_copy(deep=True)
        settings.features.sod = True
        settings.data_lifecycle.sources['sod'] = SourceSnapshot(snapshot='a' * 64, path=str(self.root / 'x.csv'), imported_at='2026-10-27T00:00:00+00:00', checked_at='2026-10-27T00:00:00+00:00')
        config.save_configuration(settings, settings.revision)
        self.client = TestClient(create_app(session_token=H['X-SAP-Lens']), base_url='http://127.0.0.1:18743')

    def tearDown(self):
        cache.clear_cache()
        config.get_settings.cache_clear()
        self.env.stop()
        self.temp.cleanup()

    def get(self, path, **params):
        response = self.client.get(path, params=params, headers=H)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def post(self, path, body, status=200):
        response = self.client.post(path, json=body, headers=H)
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def risk_matrix(self, **params):
        return self.get('/api/sod/matrix/risk', **params)

    def subject(self, user_name, **params):
        return self.get('/api/sod/subject', user=user_name, **params)

    def decide(self, kind, items, decision, status=200, context='current', **extra):
        view = self.risk_matrix(context=context)
        body = dict(context=context, expected_revision=view['revision'], expected_generation=view['generation'], items=items, decision=decision,
                    reviewer='Synthetic Reviewer', justification='Synthetic business need')
        body.update(extra)
        return self.post(f'/api/sod/decisions/{kind}', body, status)

    def activity_item(self, user_name, name, context='current'):
        detail = next(row for row in self.subject(user_name, context=context)['activities'] if row['activity'] == name)
        return dict(key=detail['key'], user=user_name, ref=name, evidence_version=detail['evidence_version'])

    def assignment_item(self, user_name, role_name, activity='A', context='current'):
        detail = next(row for row in self.subject(user_name, context=context)['activities'] if row['activity'] == activity)
        found = next(item for item in detail['assignments'] if item['role'] == role_name)
        return dict(key=found['id'], user=user_name, ref=role_name, evidence_version=found['evidence_version'])

    def acceptance_item(self, user_name, risk_id, context='current'):
        detail = self.subject(user_name, risk=risk_id, context=context)['risk']
        return dict(key=detail['finding_id'], user=user_name, ref=risk_id, evidence_version=detail['evidence_version'])


class MatrixTests(GovernanceCase):
    def test_risk_matrix_counts_distinct_users_and_user_risk_pairs(self):
        result = self.risk_matrix()
        self.assertEqual([row['user'] for row in result['rows']], ['SYN_A', 'SYN_B'])
        self.assertEqual(set(result['rows'][0]['cells']), {'R1', 'R2'})
        self.assertEqual(result['totals'], dict(users=2, user_risk=3, risks=2))
        self.assertEqual(result['criticality']['H'], dict(risks=2, user_risk=3, users=2))
        self.assertEqual({column['risk_id']: column['users'] for column in result['columns']}, {'R1': 2, 'R2': 1})
        self.assertNotIn('SYN_C', str(result['rows']))
        self.assertEqual(result['status_counts'], {'Pending': 3})
        self.assertEqual(self.get('/api/sod/matrix/risk', group_by='group')['status_counts'], {'Pending': 3})
        self.assertEqual(self.get('/api/sod/matrix/activity')['status_counts'], {'Pending': 5})

    def test_filter_options_come_from_imported_evidence_and_are_searchable(self):
        options = lambda field, **params: self.get('/api/sod/filter-options', field=field, **params)
        self.assertEqual(options('risk')['items'], ['R1', 'R2'])
        self.assertEqual(options('group')['items'], ['FIN', 'P2P'])
        self.assertEqual(options('username')['items'], ['SYN_A', 'SYN_B'])
        self.assertEqual(options('criticality')['items'], ['H'])
        self.assertEqual(options('tcode', term='x2')['items'], ['X2'])
        self.assertEqual(options('role', term='role_a')['items'], ['ROLE_A1', 'ROLE_A2', 'ROLE_AB'])
        self.assertEqual(options('role_suffix')['items'], ['A1', 'A2', 'AB', 'B', 'C'])
        self.assertEqual(options('risk', limit=1), dict(options('risk', limit=1), items=['R1'], total=2))
        self.assertEqual(self.client.get('/api/sod/filter-options?field=password', headers=H).status_code, 422)

    def test_activity_matrix_shares_activity_across_risks_without_inflation(self):
        result = self.get('/api/sod/matrix/activity')
        cell = result['rows'][0]['cells']['A']
        self.assertEqual((cell['roles'], cell['duplicate'], cell['risks']), (2, True, ['R1', 'R2']))
        self.assertEqual(result['totals'], dict(users=2, user_activity=5, activities=3))
        self.assertEqual({column['activity']: column['users'] for column in result['columns']}, {'A': 2, 'B': 2, 'C': 1})

    def test_group_aggregation_keeps_distinct_user_totals(self):
        result = self.risk_matrix(group_by='group')
        by_group = {row['user']: row for row in result['rows']}
        self.assertEqual((by_group['FIN']['users'], by_group['FIN']['cells']['R1']['users']), (1, 1))
        self.assertEqual(by_group['P2P']['cells']['R1']['users'], 1)
        self.assertEqual(result['totals']['users'], 2)

    def test_shared_filters_apply_to_both_matrices_and_explorer(self):
        self.assertEqual([row['user'] for row in self.risk_matrix(group='P2P')['rows']], ['SYN_B'])
        self.assertEqual([row['user'] for row in self.get('/api/sod/matrix/activity', role='ROLE_AB')['rows']], ['SYN_B'])
        self.assertEqual(self.risk_matrix(risk='R2')['totals']['users'], 1)
        self.assertEqual(self.risk_matrix(activity='C')['totals']['user_risk'], 1)
        self.assertEqual(self.risk_matrix(role_suffix='AB')['totals']['users'], 1)
        self.assertEqual(self.get('/api/sod/explorer/user_risk', username='SYN_B')['total'], 1)
        self.assertEqual(self.get('/api/sod/explorer/access_list')['total'], 5)
        lookup = {row['role']: row['users'] for row in self.get('/api/sod/explorer/lookup')['items']}
        self.assertEqual(lookup['ROLE_A1'], 1)

    def test_repeated_role_assignments_count_one_distinct_user_in_lookup_and_exports(self):
        """Role evidence repeats a username only per assignment record; aggregation and export count distinct users."""
        twin = user('ROLE_A1', 'ROLE_A1', 'ROLE_B', group='FIN')
        twin['assignments'][1] = dict(twin['assignments'][1], valid_from='2021-01-01', valid_to='9999-12-31')
        cache._cache = snapshot(extra_users={'SYN_TWIN': twin})
        lookup = {row['role']: row['users'] for row in self.get('/api/sod/explorer/lookup')['items']}
        self.assertEqual(lookup['ROLE_A1'], 2)  # SYN_A and SYN_TWIN once each; SYN_TWIN has two ROLE_A1 records
        records = [row for row in self.get('/api/sod/explorer/access_list', username='SYN_TWIN')['items'] if row['role'] == 'ROLE_A1']
        self.assertEqual(len(records), 2)  # each validity interval stays its own assignment record
        self.assertEqual({row['user'] for row in records}, {'SYN_TWIN'})
        exported = self.client.get('/api/sod/explorer/lookup/export', headers=H).text
        self.assertIn('"ROLE_A1";"2"', exported.replace('\ufeff', ''))
        self.assertEqual(self.risk_matrix()['totals']['users'], 3)

    def test_empty_scope_and_paging(self):
        empty = self.risk_matrix(username='NOBODY')
        self.assertEqual((empty['rows'], empty['totals']['users']), ([], 0))
        page = self.risk_matrix(limit=1, offset=1)
        self.assertEqual((len(page['rows']), page['total_rows'], page['rows'][0]['user']), (1, 2, 'SYN_B'))

    def test_large_dataset_stays_bounded_and_correct(self):
        extra = {f'SYN_L{index:04}': user('ROLE_AB', group='BULK') for index in range(1500)}
        cache._cache = snapshot(extra)
        started = time.time()
        result = self.risk_matrix(limit=100)
        self.assertEqual((result['total_rows'], len(result['rows']), result['totals']['users']), (1502, 100, 1502))
        self.assertLess(time.time() - started, 30)
        self.assertEqual(self.get('/api/sod/explorer/user_risk', limit=200)['total'], 1503)

    def test_csv_exports_respect_filters(self):
        response = self.client.get('/api/sod/explorer/user_risk/export', params={'username': 'SYN_B'}, headers=H)
        self.assertEqual(response.status_code, 200)
        lines = response.text.strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(response.text.startswith('﻿"USERNAME"'))
        self.assertEqual(self.client.get('/api/sod/explorer/lookup/export', headers=H).status_code, 200)

    def test_group_heatmap_export_counts_distinct_users_with_a_fixed_header(self):
        response = self.client.get('/api/sod/matrix/risk/group-export', headers=H)
        self.assertEqual(response.status_code, 200)
        self.assertIn('sap-lens-sod-group-risk-heatmap-', response.headers['content-disposition'])
        lines = response.text.strip().splitlines()
        self.assertEqual(lines[0], '\ufeff"SAP_USER_GROUP";"RISK_ID";"USERS_WITH_ITEM";"USERS_IN_GROUP_WITH_ITEMS"')
        self.assertEqual(sorted(lines[1:]), ['"FIN";"R1";"1";"1"', '"FIN";"R2";"1";"1"', '"P2P";"R1";"1";"1"'])
        activity = self.client.get('/api/sod/matrix/activity/group-export', params={'group': 'P2P'}, headers=H).text.strip().splitlines()
        self.assertEqual(activity[0], '\ufeff"SAP_USER_GROUP";"ACTIVITY";"USERS_WITH_ITEM";"USERS_IN_GROUP_WITH_ITEMS"')
        self.assertEqual(sorted(activity[1:]), ['"P2P";"A";"1";"1"', '"P2P";"B";"1";"1"'])
        from routers.sod_governance import native_csv_header
        self.assertEqual(native_csv_header('sap-lens-sod-group-activity-heatmap-2026-10-28.csv'), activity[0] + '\r\n')

    def test_csv_export_follows_assignment_validity_including_expired(self):
        expired = user('ROLE_A1', 'ROLE_B')
        expired['assignments'] = [assignment('ROLE_A1', end='2021-12-31'), assignment('ROLE_B', end='2021-12-31')]
        cache._cache = snapshot({'SYN_EXPIRED': expired})
        export = lambda **params: self.client.get('/api/sod/explorer/user_risk/export', params=params, headers=H).text
        self.assertNotIn('SYN_EXPIRED', export())
        self.assertIn('SYN_EXPIRED', export(validity='expired'))
        self.assertIn('SYN_EXPIRED', export(validity='all'))
        self.assertNotIn('SYN_A', export(validity='expired', username='SYN_EXPIRED').replace('SYN_EXPIRED', ''))


class DecisionTests(GovernanceCase):
    def test_activity_review_does_not_change_risk_detection_or_accept_risk(self):
        before = self.risk_matrix()['totals']
        self.decide('activity', [self.activity_item('SYN_A', 'A'), self.activity_item('SYN_A', 'B')], 'Approved')
        after = self.risk_matrix()
        self.assertEqual(after['totals'], before)
        cell = after['rows'][0]['cells']['R1']
        self.assertEqual((cell['acceptance'], cell['activities']), ('Pending', {'Approved': 2}))
        self.assertIn('R2', after['rows'][0]['cells'])

    def test_activity_is_reviewed_once_for_all_risks_and_never_for_other_users(self):
        self.decide('activity', [self.activity_item('SYN_A', 'A')], 'Remove')
        a = {row['activity']: row['decision'] for row in self.subject('SYN_A')['activities']}
        b = {row['activity']: row['decision'] for row in self.subject('SYN_B')['activities']}
        self.assertEqual((a['A'], a['B']), ('Removal required', 'Pending'))
        self.assertEqual(b['A'], 'Pending')
        self.assertEqual(self.subject('SYN_A', risk='R2')['activities'][0]['decision'], 'Removal required')

    def test_conditional_requires_conditions_and_decisions_need_justification(self):
        item = self.activity_item('SYN_A', 'A')
        self.decide('activity', [item], 'Conditional', status=422)
        self.decide('activity', [item], 'Conditional', controls='Quarterly supervisor sign-off')
        self.decide('activity', [item], 'Keep', status=422)
        view = self.risk_matrix()
        body = dict(context='current', expected_revision=view['revision'], expected_generation=view['generation'], items=[item], decision='Approved', reviewer='R', justification='')
        self.post('/api/sod/decisions/activity', body, 422)

    def test_independent_role_assignment_decisions_with_duplicate_coverage(self):
        detail = next(row for row in self.subject('SYN_A', risk='R1')['activities'] if row['activity'] == 'A')
        self.assertTrue(detail['duplicate_coverage'])
        self.assertEqual({item['role'] for item in detail['assignments']}, {'ROLE_A1', 'ROLE_A2'})
        self.decide('activity', [self.activity_item('SYN_A', 'A')], 'Approved')
        self.decide('assignment', [self.assignment_item('SYN_A', 'ROLE_A1')], 'Keep')
        self.decide('assignment', [self.assignment_item('SYN_A', 'ROLE_A2')], 'Remove')
        detail = next(row for row in self.subject('SYN_A', risk='R1')['activities'] if row['activity'] == 'A')
        self.assertEqual(detail['decision'], 'Approved')
        self.assertEqual({item['role']: item['decision'] for item in detail['assignments']}, {'ROLE_A1': 'Keep', 'ROLE_A2': 'Removal required'})
        self.decide('assignment', [self.assignment_item('SYN_A', 'ROLE_A1')], 'Approved', status=422)

    def test_assignment_identity_distinguishes_validity_not_just_role(self):
        user_two = copy.deepcopy(user('ROLE_A1', 'ROLE_B'))
        user_two['assignments'].append(assignment('ROLE_A1', start='2025-01-01', end='9999-12-31', group='FIN'))
        cache._cache = snapshot({'SYN_D': user_two})
        ids = {item['id'] for row in self.subject('SYN_D')['activities'] for item in row['assignments'] if item['role'] == 'ROLE_A1'}
        self.assertEqual(len(ids), 2)

    def test_risk_acceptance_is_separate_with_separation_expiry_and_history(self):
        item = self.acceptance_item('SYN_B', 'R1')
        self.decide('acceptance', [item], 'Accepted', status=422)
        self.decide('acceptance', [item], 'Accepted', status=422, approver='Synthetic Reviewer')
        self.decide('acceptance', [item], 'Accepted', status=422, approver='Approver', expires=(date.today() - timedelta(days=1)).isoformat())
        self.decide('acceptance', [item], 'Accepted', approver='Synthetic Approver', controls='Monitoring report', expires=(date.today() + timedelta(days=90)).isoformat())
        risk = self.subject('SYN_B', risk='R1')['risk']
        self.assertEqual(risk['acceptance'], 'Accepted')
        self.assertEqual(self.risk_matrix()['rows'][1]['cells']['R1']['acceptance'], 'Accepted')
        self.assertIn('R1', self.risk_matrix()['rows'][1]['cells'])
        self.decide('acceptance', [item], 'Rejected', approver='Synthetic Approver')
        self.assertEqual(self.subject('SYN_B', risk='R1')['risk']['acceptance'], 'Rejected')
        history = self.get('/api/sod/decisions/acceptance/history', key=item['key'])['items']
        self.assertEqual([event['decision'] for event in history], ['Rejected', 'Accepted'])
        evidence = self.get('/api/sod/decisions/acceptance/evidence', key=item['key'], event_id=history[1]['event_id'])
        self.assertEqual(evidence['evidence']['risk_id'], 'R1')

    def test_evidence_change_marks_decisions_outdated_without_deleting_history(self):
        item = self.activity_item('SYN_B', 'A')
        self.decide('activity', [item], 'Approved')
        self.assertEqual(self.subject('SYN_B')['activities'][0]['decision'], 'Approved')
        cache._cache = snapshot(tcodes={'ROLE_AB': ['X5']}, extra=True)
        changed = next(row for row in self.subject('SYN_B')['activities'] if row['activity'] == 'A')
        self.assertEqual(changed['decision'], 'Outdated')
        self.assertNotEqual(changed['evidence_version'], item['evidence_version'])
        self.assertEqual(len(self.get('/api/sod/decisions/activity/history', key=item['key'])['items']), 1)
        self.decide('activity', [item], 'Approved', status=409)
        self.decide('activity', [dict(item, evidence_version=changed['evidence_version'])], 'Approved')
        self.assertEqual(next(row for row in self.subject('SYN_B')['activities'] if row['activity'] == 'A')['decision'], 'Approved')
        self.assertEqual(len(self.get('/api/sod/decisions/activity/history', key=item['key'])['items']), 2)

    def test_stale_revision_and_generation_are_rejected(self):
        item = self.activity_item('SYN_A', 'A')
        view = self.risk_matrix()
        body = dict(context='current', expected_revision=view['revision'], expected_generation=view['generation'], items=[item], decision='Approved', reviewer='R', justification='x')
        self.post('/api/sod/decisions/activity', body)
        self.post('/api/sod/decisions/activity', body, 409)
        self.post('/api/sod/decisions/activity', dict(body, expected_revision=1, expected_generation='b' * 64), 409)

    def test_batch_review_is_explicit_and_atomic(self):
        items = [self.activity_item('SYN_A', 'B'), self.activity_item('SYN_B', 'B')]
        result = self.decide('activity', items, 'Approved')
        self.assertEqual(len(result['events']), 2)
        self.assertEqual(self.subject('SYN_A')['activities'][0]['decision'], 'Pending')
        bad = items + [dict(items[0], key='c' * 64, ref='NOPE')]
        before = decisions.read().revision
        self.decide('activity', bad, 'Remove', status=409)
        self.assertEqual(decisions.read().revision, before)


class ImpactTests(GovernanceCase):
    def test_removing_one_of_two_providers_does_not_resolve_the_risk(self):
        impact = self.subject('SYN_A', risk='R1')['impact']
        single = {item: value for item, value in impact['per_assignment'].items()}
        roles = {row['id']: row['role'] for row in next(a for a in self.subject('SYN_A', risk='R1')['activities'] if a['activity'] == 'A')['assignments']}
        a1 = next(aid for aid, role_name in roles.items() if role_name == 'ROLE_A1')
        self.assertEqual(single[a1]['resolves'], [])
        self.assertEqual(sorted(single[a1]['remaining']), ['R1', 'R2'])
        sides = {option['slot']: option for option in impact['options']}
        self.assertEqual(len(sides['ACTVT1']['assignments']), 2)
        self.assertTrue(sides['ACTVT1']['resolves_risk'])
        self.assertEqual(sides['ACTVT1']['also_resolves'], ['R2'])

    def test_removing_all_providers_resolves_and_warns_for_approved_activity(self):
        self.decide('activity', [self.activity_item('SYN_A', 'A')], 'Approved')
        subject = self.subject('SYN_A', risk='R1')
        ids = [item['id'] for row in subject['activities'] if row['activity'] == 'A' for item in row['assignments']]
        result = self.post('/api/sod/simulate', dict(user='SYN_A', removed=ids))
        self.assertEqual((result['resolved'], result['after']), (['R1', 'R2'], []))
        self.assertEqual(result['lost_activities'], ['A'])
        self.assertTrue(any('approved access to activity A' in text for text in result['warnings']))
        self.assertTrue(result['eliminates_all'])

    def test_simulation_never_mutates_imported_evidence(self):
        before = copy.deepcopy(cache.get_snapshot().users.users)
        evidence_before = self.get('/api/sod/analysis', as_of=str(date.today()))['summary']
        ids = [item['id'] for row in self.subject('SYN_A')['activities'] for item in row['assignments']]
        self.post('/api/sod/simulate', dict(user='SYN_A', removed=ids))
        self.assertEqual(cache.get_snapshot().users.users, before)
        self.assertEqual(self.get('/api/sod/analysis', as_of=str(date.today()))['summary'], evidence_before)
        self.assertEqual(self.risk_matrix()['totals']['user_risk'], 3)
        self.post('/api/sod/simulate', dict(user='SYN_A', removed=['d' * 64]), 422)
        self.post('/api/sod/simulate', dict(user='NOBODY', removed=[]), 404)

    def test_multiple_role_paths_each_side_is_sufficient_alone(self):
        subject = self.subject('SYN_B', risk='R1')
        ids = [item['id'] for row in subject['activities'] for item in row['assignments']]
        self.assertEqual(len(set(ids)), 1)
        one = self.post('/api/sod/simulate', dict(user='SYN_B', removed=ids))
        self.assertEqual(one['resolved'], ['R1'])

    def test_missing_evidence_is_not_absence_of_conflict(self):
        cache._cache = snapshot()
        cache._cache.users = UserState(users={})
        result = self.risk_matrix()
        self.assertEqual(result['coverage']['status'], 'unavailable')
        self.assertEqual(result['rows'], [])
        self.assertEqual(self.get('/api/sod/queue')['total'], 0)


class RemediationTests(GovernanceCase):
    def test_removal_decision_derives_rows_and_tracked_action_is_not_verification(self):
        self.decide('activity', [self.activity_item('SYN_A', 'A')], 'Approved')
        remove = self.assignment_item('SYN_A', 'ROLE_A2')
        self.decide('assignment', [remove], 'Remove')
        rows = self.get('/api/sod/remediation')['items']
        row = next(item for item in rows if item['role'] == 'ROLE_A2' and item['activity'] == 'A')
        self.assertEqual((row['recommended'], row['action_status'], row['verification']), ('Remove assignment', 'Not tracked', 'Not tracked'))
        view = self.get('/api/sod/remediation')
        body = dict(context='current', expected_revision=view['revision'], actor='Owner', user='SYN_A', assignment_id=remove['key'], role='ROLE_A2',
                    recommended='Remove assignment', reason='Duplicate coverage', owner='Access team', due_date=(date.today() - timedelta(days=2)).isoformat())
        self.post('/api/sod/remediation/actions', dict(body, status='Completed'), 422)
        self.post('/api/sod/remediation/actions', body)
        row = next(item for item in self.get('/api/sod/remediation')['items'] if item['role'] == 'ROLE_A2' and item['activity'] == 'A')
        self.assertEqual((row['action_status'], row['overdue'], row['verification']), ('Open', True, 'Still present in current evidence'))
        summary = self.get('/api/sod/remediation')['summary']
        self.assertEqual(summary['overdue'], 1)
        revision = self.get('/api/sod/remediation')['revision']
        action = self.get('/api/sod/remediation')['actions'][0]
        done = dict(body, expected_revision=revision, action_id=action['id'], status='Completed', completion_evidence='Ticket closed')
        self.post('/api/sod/remediation/actions', done)
        row = next(item for item in self.get('/api/sod/remediation')['items'] if item['role'] == 'ROLE_A2' and item['activity'] == 'A')
        self.assertEqual((row['action_status'], row['verification']), ('Completed', 'Still present in current evidence'))
        self.assertEqual(len(self.get('/api/sod/remediation')['actions'][0]['history']), 2)

    def test_verification_after_refresh_requires_complete_source_evidence(self):
        remove = self.assignment_item('SYN_A', 'ROLE_A2')
        self.decide('assignment', [remove], 'Remove')
        view = self.get('/api/sod/remediation')
        self.post('/api/sod/remediation/actions', dict(context='current', expected_revision=view['revision'], actor='Owner', user='SYN_A',
                                                       assignment_id=remove['key'], role='ROLE_A2', recommended='Remove assignment', reason='Duplicate'))
        refreshed = snapshot()
        refreshed.users.users['SYN_A']['assignments'] = [a for a in refreshed.users.users['SYN_A']['assignments'] if a['role_name'] != 'ROLE_A2']
        cache._cache = refreshed
        verified = {r['verification'] for r in self.get('/api/sod/remediation')['items'] if r['role'] == 'ROLE_A2'}
        self.assertEqual(verified, set())
        self.assertEqual(self.get('/api/sod/remediation')['actions'][0]['verification'], 'Not present in current evidence')
        queue = self.get('/api/sod/queue', status='Resolved')
        self.assertEqual([item['ref'] for item in queue['items']], ['ROLE_A2'])
        csv = self.client.get('/api/sod/remediation/export', headers=H)
        self.assertEqual(csv.status_code, 200)

    def test_compensating_control_and_no_action_groups(self):
        self.decide('activity', [self.activity_item('SYN_B', 'B')], 'Conditional', controls='Dual control')
        self.decide('activity', [self.activity_item('SYN_B', 'A')], 'Approved')
        groups = {row['activity']: row['recommended'] for row in self.get('/api/sod/remediation')['items'] if row['user'] == 'SYN_B'}
        self.assertEqual(groups['B'], 'Apply compensating control')
        self.assertEqual(groups['A'], 'Maintain access')
        self.decide('acceptance', [self.acceptance_item('SYN_B', 'R1')], 'Accepted', approver='Approver')
        self.assertEqual(self.get('/api/sod/remediation', recommended='No action required')['total'], 1)


class QueueTests(GovernanceCase):
    def test_queue_status_filters_and_counts(self):
        queue = self.get('/api/sod/queue')
        self.assertEqual(queue['counts']['Pending'], queue['total'])
        self.decide('activity', [self.activity_item('SYN_A', 'A')], 'Remove')
        self.decide('activity', [self.activity_item('SYN_B', 'A')], 'Approved')
        counts = self.get('/api/sod/queue', kind='activity')['counts']
        self.assertEqual((counts['Removal required'], counts['Reviewed']), (1, 1))
        self.assertEqual(self.get('/api/sod/queue', status='Risk acceptance pending')['total'], 3)
        self.assertEqual(self.get('/api/sod/queue', kind='assignment', status='Pending')['total'], 5)
        self.assertEqual(self.client.get('/api/sod/queue/export', headers=H).status_code, 200)

    def test_user_queue_has_one_row_per_user_with_independent_progress(self):
        before = self.get('/api/sod/queue/users')
        self.assertEqual(before['total'], len({item['user'] for item in self.get('/api/sod/queue', limit=200)['items']}))
        self.assertTrue(all(row['decided'] == 0 and row['outstanding'] == row['total'] for row in before['items']))
        self.decide('activity', [self.activity_item('SYN_A', 'A')], 'Remove')
        after = {row['user']: row for row in self.get('/api/sod/queue/users')['items']}
        row = after['SYN_A']
        self.assertEqual((row['activity']['decided'], row['assignment']['decided'], row['acceptance']['decided'], row['removal']), (1, 0, 0, 1))
        self.assertEqual(row['outstanding'], row['total'] - 1)
        self.assertEqual(after['SYN_B']['decided'], 0)
        self.assertEqual([item['user'] for item in self.get('/api/sod/queue/users', progress='removal')['items']], ['SYN_A'])
        self.assertEqual(self.get('/api/sod/queue/users')['counts']['removal'], 1)
        self.assertNotIn('SYN_A', [item['user'] for item in self.get('/api/sod/queue/users', progress='complete')['items']])

    def test_subject_overview_lists_every_activity_assignment_and_risk_independent_of_focus(self):
        focused = self.subject('SYN_A', risk='R1')
        full = focused['overview']
        self.assertGreaterEqual(len(full['activities']), len(focused['activities']))
        self.assertTrue(full['assignments'] and full['risks'])
        self.assertEqual({item['risk_id'] for item in full['risks']}, set(self.subject('SYN_A')['overview']['risks'][i]['risk_id'] for i in range(len(full['risks']))))
        self.assertTrue(all({'id', 'decision', 'evidence_version', 'activities'} <= set(item) for item in full['assignments']))

    def test_decisions_without_verifiable_absence_stay_historical_not_resolved(self):
        self.decide('assignment', [self.assignment_item('SYN_A', 'ROLE_A2')], 'Remove')
        cache._cache = snapshot()
        cache._cache.users = UserState(users={})
        queue = self.get('/api/sod/queue', status='Historical')
        self.assertEqual([(item['kind'], item['ref'], item['lifecycle']) for item in queue['items']], [('assignment', 'ROLE_A2', 'Historical')])
        self.assertEqual(self.get('/api/sod/queue', status='Resolved')['total'], 0)

    def test_legacy_risk_decisions_remain_historical_and_are_not_reinterpreted(self):
        import sod_reviews as legacy
        finding = next(row for row in self.get('/api/sod/analysis', as_of=str(date.today()), limit=100)['items'] if row['subject'] == 'SYN_B')
        self.assertTrue(finding['current_potential'])
        self.assertEqual(self.subject('SYN_B', risk='R1')['risk']['acceptance'], 'Pending')
        self.assertEqual(legacy.read().contexts, {})


class OverviewTests(GovernanceCase):
    def test_overview_reports_distinct_counts_progress_and_refresh_changes(self):
        first = self.get('/api/sod/overview')['governance']
        self.assertEqual((first['users_with_conflicts'], first['user_risk_findings'], first['activities']), (2, 3, {'Pending': 5}))
        self.assertIsNone(first['change'])
        self.decide('activity', [self.activity_item('SYN_A', 'A')], 'Remove')
        again = self.get('/api/sod/overview')['governance']
        self.assertEqual((again['activities']['Removal required'], again['activities']['Pending']), (1, 4))
        # A source refresh that removes SYN_B changes the observed baseline and is reported once.
        refreshed = snapshot()
        refreshed.users.users.pop('SYN_B')
        cache._cache = refreshed
        settings = config.get_settings().model_copy(deep=True)
        settings.features.sod = True
        settings.data_lifecycle.sources['sod'] = SourceSnapshot(snapshot='b' * 64, path=str(self.root / 'x.csv'), imported_at='2026-10-28T00:00:00+00:00', checked_at='2026-10-28T00:00:00+00:00')
        config.save_configuration(settings, settings.revision)
        after = self.get('/api/sod/overview')['governance']
        self.assertEqual((after['change']['new'], after['change']['no_longer_detected'], after['users_with_conflicts']), (0, 1, 1))
        self.assertEqual(self.get('/api/sod/overview')['governance']['change'], after['change'])

    def test_overview_without_evidence_is_unavailable_not_zero(self):
        cache._cache.users = UserState(users={})
        self.assertEqual(self.get('/api/sod/overview')['governance']['available'], False)


class SecurityAndPrivacyTests(GovernanceCase):
    GET_PATHS = ['/api/sod/matrix/risk', '/api/sod/matrix/activity', '/api/sod/explorer/user_risk', '/api/sod/explorer/lookup/export', '/api/sod/queue',
                 '/api/sod/queue/export', '/api/sod/remediation', '/api/sod/remediation/export', '/api/sod/subject?user=x', '/api/sod/overview', '/api/sod/filter-options']

    def test_every_governance_route_requires_the_application_capability(self):
        for path in self.GET_PATHS:
            self.assertEqual(self.client.get(path).status_code, 403, path)
        for path, body in [('/api/sod/decisions/activity', {}), ('/api/sod/simulate', {}), ('/api/sod/remediation/actions', {}),
                           ('/api/sod/reports/remediation/pdf', {}), ('/api/sod/periods/' + 'a' * 32 + '/delete', {})]:
            self.assertEqual(self.client.post(path, json=body).status_code, 403, path)
        self.assertEqual(self.client.get('/api/sod/matrix/risk', headers={'X-SAP-Lens': 'wrong'}).status_code, 403)

    def test_decision_text_stays_out_of_diagnostics_and_portable_exports(self):
        marker = 'CONFIDENTIAL-JUSTIFICATION-MARKER'
        self.decide('activity', [self.activity_item('SYN_A', 'A')], 'Approved', controls='', justification=marker)
        diagnostics = self.client.get('/api/diagnostics/export', headers=H)
        portable = self.client.post('/api/configuration/export?include_private=false', json={}, headers=H)
        for response in (diagnostics, portable):
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(marker, response.text)
            self.assertNotIn(str(self.root), response.text)
        self.assertTrue(any(marker in path.read_text(encoding='utf-8') for path in self.root.glob('sod-decisions.json')))

    def test_exports_contain_no_filesystem_paths(self):
        self.decide('assignment', [self.assignment_item('SYN_A', 'ROLE_A2')], 'Remove')
        for path in ('/api/sod/explorer/access_list/export', '/api/sod/queue/export', '/api/sod/remediation/export'):
            text = self.client.get(path, headers=H).text
            self.assertNotIn(str(self.root), text, path)
            self.assertNotIn('sod-decisions', text, path)

    def test_unsupported_values_are_rejected_without_side_effects(self):
        for params in ({'context': 'not a context'}, {'validity': 'bogus'}, {'acceptance': 'Maybe'}, {'sort': 'bogus'}):
            self.assertEqual(self.client.get('/api/sod/matrix/risk', params=params, headers=H).status_code, 422, params)
        self.assertEqual(self.client.get('/api/sod/matrix/risk', params={'context': 'a' * 32}, headers=H).status_code, 404)
        self.assertEqual(self.client.get('/api/sod/explorer/other', headers=H).status_code, 422)
        self.assertEqual(decisions.read().revision, 0)


class RobustnessTests(GovernanceCase):
    def test_every_matrix_sort_and_grouping_combination_returns_valid_json(self):
        for kind in ('risk', 'activity'):
            for sort in ('subject', 'findings'):
                for group_by in ('user', 'group'):
                    for descending in ('false', 'true'):
                        response = self.client.get(f'/api/sod/matrix/{kind}', params={'sort': sort, 'group_by': group_by, 'descending': descending}, headers=H)
                        self.assertEqual(response.status_code, 200, (kind, sort, group_by, descending, response.text[:120]))
                        self.assertEqual(len(response.json()['rows']) > 0, True)
        most = self.risk_matrix(sort='findings')['rows']
        self.assertEqual([row['user'] for row in most], ['SYN_A', 'SYN_B'])
        self.assertEqual([row['user'] for row in self.risk_matrix(sort='findings', descending='true')['rows']], ['SYN_B', 'SYN_A'])

    def test_unexpected_server_failures_answer_as_json_not_plain_text(self):
        import routers.sod_governance as router_module
        original = router_module.scope.scoped
        router_module.scope.scoped = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('synthetic internal failure'))
        try:
            client = TestClient(create_app(session_token=H['X-SAP-Lens']), base_url='http://127.0.0.1:18743', raise_server_exceptions=False)
            response = client.get('/api/sod/matrix/risk', headers=H)
        finally:
            router_module.scope.scoped = original
        self.assertEqual(response.status_code, 500)
        self.assertTrue(response.headers['content-type'].startswith('application/json'))
        self.assertIn('failed unexpectedly', response.json()['detail'])
        self.assertNotIn('synthetic internal failure', response.text)
