"""SoD 2.0 review periods: approval workflow, frozen decisions, comparisons and guarded deletion."""
from datetime import date
import os
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cache
import sod_decisions as decisions
import sod_periods as periods
from test_sod_governance import GovernanceCase, snapshot


class PeriodV2Case(GovernanceCase):
    def new_period(self, name='Synthetic 2026'):
        revision = self.get('/api/sod/periods')['revision']
        result = self.post('/api/sod/periods', dict(name=name, start='2026-01-01', end='2026-12-31', evaluation_date='2026-10-27', expected_revision=revision))
        return result['period']['id']

    def move(self, pid, state, status=200, **extra):
        details = self.get(f'/api/sod/periods/{pid}')
        body = dict(state=state, expected_revision=details['revision'], expected_review_revision=details['review_revision'])
        body.update(dict(actor='Synthetic Actor'), **extra)
        return self.post(f'/api/sod/periods/{pid}/transition', body, status)

    def decide_everything(self, pid, acceptance='Accepted'):
        for user_name, names in (('SYN_A', 'ABC'), ('SYN_B', 'AB')):
            self.decide('activity', [self.activity_item(user_name, name, pid) for name in names], 'Approved', context=pid)
        for user_name, risk in (('SYN_A', 'R1'), ('SYN_A', 'R2'), ('SYN_B', 'R1')):
            self.decide('acceptance', [self.acceptance_item(user_name, risk, pid)], acceptance, context=pid, approver='Synthetic Approver')

    def approve(self, pid, **extra):
        values = dict(reviewer='Synthetic Reviewer', approver='Synthetic Approver', approval_date='2026-10-27', confirm=True)
        values.update(extra)
        return self.move(pid, 'Approved', **values)


class WorkflowTests(PeriodV2Case):
    def test_new_periods_use_the_v2_model_and_independent_decision_contexts(self):
        first, second = self.new_period('First'), self.new_period('Second')
        self.assertEqual(self.get(f'/api/sod/periods/{first}')['model'], 2)
        self.decide_everything(first)
        self.assertEqual(self.get(f'/api/sod/periods/{first}')['outstanding']['blocking'], 0)
        self.assertEqual(self.get(f'/api/sod/periods/{second}')['outstanding']['blocking'], 8)
        self.assertEqual(self.get('/api/sod/queue', context='current')['counts']['Pending'], self.get('/api/sod/queue', context='current')['total'])

    def test_pending_decisions_block_ready_for_approval_until_decided(self):
        pid = self.new_period()
        self.move(pid, 'In review')
        self.move(pid, 'Ready for approval', status=409)
        self.decide_everything(pid, acceptance='Rejected')
        self.move(pid, 'Ready for approval')
        self.assertEqual(self.get('/api/sod/queue', context=pid, status='Awaiting approval')['total'], 8)

    def test_reviewer_and_approver_must_differ_and_actor_is_recorded(self):
        pid = self.new_period()
        self.decide_everything(pid)
        self.move(pid, 'In review')
        self.move(pid, 'Ready for approval', actor='  ', status=422)
        self.move(pid, 'Ready for approval')
        self.move(pid, 'Approved', status=422, reviewer='Same Person', approver='same person', approval_date='2026-10-27', confirm=True)
        self.move(pid, 'Approved', status=422, reviewer='A', approver='B', approval_date='2026-10-27', confirm=False)
        result = self.approve(pid)
        self.assertEqual(result['period']['state'], 'Approved')
        history = self.get(f'/api/sod/periods/{pid}')['period']['history']
        self.assertEqual([item['to_state'] for item in history], ['In review', 'Ready for approval', 'Approved'])
        self.assertTrue(all(item['actor'] == 'Synthetic Actor' for item in history))

    def test_rejection_requires_reason_returns_to_review_and_keeps_history(self):
        pid = self.new_period()
        self.decide_everything(pid)
        self.move(pid, 'In review')
        self.move(pid, 'Ready for approval')
        self.move(pid, 'Rejected', status=422)
        rejected = self.move(pid, 'Rejected', reason='Controls insufficient for SYN_A')
        self.assertEqual(rejected['period']['rejection_reason'], 'Controls insufficient for SYN_A')
        self.move(pid, 'Approved', status=422, reviewer='A', approver='B', approval_date='2026-10-27', confirm=True)
        self.move(pid, 'In review')
        self.assertEqual([item['to_state'] for item in self.get(f'/api/sod/periods/{pid}')['period']['history']][-2:], ['Rejected', 'In review'])

    def test_approval_freezes_decisions_and_evidence_against_later_changes(self):
        pid = self.new_period()
        self.decide_everything(pid)
        for state in ('In review', 'Ready for approval'):
            self.move(pid, state)
        approved = self.approve(pid)['period']
        frozen = self.get(f'/api/sod/matrix/risk', context=pid)
        self.assertTrue(frozen['frozen'])
        self.assertFalse(frozen['reviewable'])
        self.assertEqual(frozen['rows'][0]['cells']['R1']['acceptance'], 'Accepted')
        # Live evidence and live decisions change; the approved snapshot does not.
        cache._cache = snapshot()
        cache._cache.users.users.pop('SYN_A')
        self.decide('activity', [self.activity_item('SYN_B', 'A')], 'Remove')
        again = self.get('/api/sod/matrix/risk', context=pid)
        self.assertEqual(again['totals'], frozen['totals'])
        self.assertEqual(again['rows'][0]['cells']['R1']['acceptance'], 'Accepted')
        self.assertEqual(self.get(f'/api/sod/periods/{pid}')['period']['snapshot'], approved['snapshot'])
        view = self.get('/api/sod/matrix/risk', context=pid)
        body = dict(context=pid, expected_revision=view['revision'], expected_generation=view['generation'], items=[self.activity_item('SYN_B', 'A', pid)],
                    decision='Remove', reviewer='R', justification='x')
        self.post('/api/sod/decisions/activity', body, 409)
        self.move(pid, 'In review', status=409)
        self.post(f'/api/sod/periods/{pid}/recapture', dict(expected_revision=self.get('/api/sod/periods')['revision'], confirm=True), 409)

    def test_closing_an_approved_period_is_final_and_requires_confirmation(self):
        pid = self.new_period()
        self.decide_everything(pid)
        for state in ('In review', 'Ready for approval'):
            self.move(pid, state)
        self.approve(pid)
        self.move(pid, 'Closed', status=422)
        self.assertEqual(self.move(pid, 'Closed', confirm=True)['period']['state'], 'Closed')
        self.move(pid, 'In review', status=409)

    def test_decisions_in_a_period_never_touch_current_or_other_periods(self):
        first, second = self.new_period('A'), self.new_period('B')
        self.decide('activity', [self.activity_item('SYN_A', 'A', first)], 'Remove', context=first)
        self.assertEqual(next(row for row in self.subject('SYN_A', context=second)['activities'] if row['activity'] == 'A')['decision'], 'Pending')
        self.assertEqual(next(row for row in self.subject('SYN_A')['activities'] if row['activity'] == 'A')['decision'], 'Pending')

    def test_comparison_includes_decision_changes_for_v2_periods(self):
        first = self.new_period('Before')
        self.decide('activity', [self.activity_item('SYN_A', 'A', first)], 'Approved', context=first)
        second = self.new_period('After')
        result = self.get('/api/sod/periods/compare', left=first, right=second)
        self.assertIn('decision_changes', result)
        change = next(item for item in result['decision_changes'] if (item['user'], item['ref'], item['kind']) == ('SYN_A', 'A', 'activity'))
        self.assertEqual((change['before'], change['after']), ('Approved', 'Pending'))


class DeletionTests(PeriodV2Case):
    def impact(self, pid):
        return self.get(f'/api/sod/periods/{pid}/deletion-impact')

    def delete(self, pid, name, status=200, **extra):
        revision = self.get('/api/sod/periods')['revision']
        body = dict(expected_revision=revision, confirm_name=name, actor='Synthetic Actor')
        body.update(extra)
        return self.post(f'/api/sod/periods/{pid}/delete', body, status)

    def test_empty_draft_is_permanently_deleted_after_typed_confirmation(self):
        pid = self.new_period('Empty draft')
        impact = self.impact(pid)
        self.assertEqual((impact['mode'], impact['counts']['decisions'], impact['name']), ('permanent', 0, 'Empty draft'))
        snapshot_id = self.get(f'/api/sod/periods/{pid}')['period']['snapshot']
        self.delete(pid, 'empty draft', status=422)
        self.delete(pid, '', status=422)
        result = self.delete(pid, 'Empty draft')
        self.assertEqual(result['deleted']['mode'], 'permanent')
        self.assertEqual([item['id'] for item in self.get('/api/sod/periods')['items']], [])
        self.assertEqual(self.get('/api/sod/periods')['deletions'][-1]['name'], 'Empty draft')
        self.assertEqual(self.client.get(f'/api/sod/periods/{pid}', headers={'X-SAP-Lens': 'synthetic-governance-session'}).status_code, 404)
        from csv_lifecycle import private_path
        self.assertFalse(private_path('snapshots', snapshot_id).exists())

    def test_listing_reports_review_progress_without_counting_pending_work_as_done(self):
        pid = self.new_period('Progress')
        before = next(item for item in self.get('/api/sod/periods')['items'] if item['id'] == pid)['progress']
        self.assertEqual((before['decided'], before['blocking'] > 0), (0, True))
        self.assertGreater(before['total'], 0)
        self.decide('activity', [self.activity_item('SYN_A', 'A', pid)], 'Approved', context=pid)
        after = next(item for item in self.get('/api/sod/periods')['items'] if item['id'] == pid)['progress']
        self.assertEqual((after['decided'], after['total']), (1, before['total']))
        self.assertEqual(after['blocking'], before['blocking'] - 1)
        self.decide_everything(pid)
        done = next(item for item in self.get('/api/sod/periods')['items'] if item['id'] == pid)['progress']
        self.assertEqual((done['decided'], done['blocking']), (done['total'], 0))

    def test_period_with_recorded_work_is_archived_not_destroyed(self):
        pid = self.new_period('In progress')
        self.decide('activity', [self.activity_item('SYN_A', 'A', pid)], 'Approved', context=pid)
        impact = self.impact(pid)
        self.assertEqual((impact['mode'], impact['counts']['decisions']), ('archive', 1))
        self.delete(pid, 'In progress', status=422)
        result = self.delete(pid, 'In progress', confirm_impact=True)
        self.assertEqual(result['deleted']['mode'], 'archived')
        self.assertEqual(self.get('/api/sod/periods')['items'], [])
        self.assertEqual([item['id'] for item in self.get('/api/sod/periods', include_archived=True)['items']], [pid])
        self.assertEqual(decisions.context_summary(pid)['activity'], 1)
        self.assertEqual(self.client.get('/api/sod/matrix/risk', params={'context': pid}, headers={'X-SAP-Lens': 'synthetic-governance-session'}).status_code, 404)

    def approved_period(self, name):
        pid = self.new_period(name)
        self.decide_everything(pid)
        for state in ('In review', 'Ready for approval'):
            self.move(pid, state)
        self.approve(pid)
        return pid

    def test_approved_period_can_be_deleted_only_with_reason_history_confirmation_and_stays_in_the_audit_trail(self):
        pid = self.approved_period('Approved one')
        impact = self.impact(pid)
        self.assertEqual((impact['mode'], impact['requires_reason'], impact['requires_history_confirmation']), ('archive', True, True))
        self.assertTrue(impact['warnings'])
        before = self.get(f'/api/sod/periods/{pid}')
        events = decisions.context_summary(pid)['events']
        self.assertGreater(events, 0)
        self.delete(pid, 'Approved one', status=422, confirm_impact=True)
        self.delete(pid, 'Approved one', status=422, confirm_impact=True, confirm_history=True)
        self.delete(pid, 'Approved one', status=422, confirm_impact=True, reason='Duplicate review')
        result = self.delete(pid, 'Approved one', confirm_impact=True, confirm_history=True, reason='Duplicate review')
        self.assertEqual((result['deleted']['mode'], result['deleted']['reason'], result['deleted']['frozen']), ('archived', 'Duplicate review', True))
        self.assertEqual(self.get('/api/sod/periods')['items'], [])
        archived = self.get('/api/sod/periods', include_archived=True)['items'][0]
        self.assertEqual((archived['state'], archived['history'][-1]['to_state'], archived['history'][-1]['note']), ('Approved', 'Archived', 'Duplicate review'))
        self.assertEqual(archived['approver'], before['period']['approver'])
        self.assertEqual(decisions.context_summary(pid)['events'], events)
        from csv_lifecycle import private_path
        self.assertTrue(private_path('snapshots', before['period']['snapshot']).exists())
        self.assertEqual(self.client.get(f'/api/sod/periods/{pid}/deletion-impact', headers={'X-SAP-Lens': 'synthetic-governance-session'}).status_code, 404)

    def test_period_with_issued_reports_and_dependent_baselines_is_archived_without_touching_the_report_log(self):
        draft = self.new_period('Referenced draft')
        decisions.log_report(draft, 'pdf', 'SoD Access Review', 'For review', '1.0', 'e' * 64)
        impact = self.impact(draft)
        self.assertEqual((impact['mode'], impact['requires_history_confirmation'], impact['requires_reason']), ('archive', True, False))
        self.delete(draft, 'Referenced draft', status=422, confirm_impact=True)
        self.delete(draft, 'Referenced draft', confirm_impact=True, confirm_history=True)
        self.assertEqual(len(decisions.context_summary(draft)['reports']), 1)
        other = self.new_period('Baseline')
        third = self.new_period('Compared')
        decisions.log_report(third, 'pdf', 'SoD Access Review', 'Draft', '1.0', 'f' * 64, previous_period_id=other)
        impact = self.impact(other)
        self.assertEqual((impact['mode'], len(impact['dependents'])), ('archive', 1))
        self.assertTrue(any('baseline' in warning for warning in impact['warnings']))
        self.delete(other, 'Baseline', confirm_impact=True, confirm_history=True)
        self.assertEqual(len(decisions.context_summary(third)['reports']), 1)
        self.assertEqual(decisions.context_summary(third)['reports'][0]['previous_period_id'], other)
        self.assertEqual([item['id'] for item in self.get('/api/sod/periods')['items']], [third])

    def test_closed_period_deletion_does_not_change_other_periods_or_current_decisions(self):
        pid = self.approved_period('To close')
        self.move(pid, 'Closed', confirm=True)
        keep = self.new_period('Keep')
        self.decide('activity', [self.activity_item('SYN_A', 'A', keep)], 'Approved', context=keep)
        before = decisions.context_summary(keep)['events']
        self.delete(pid, 'To close', confirm_impact=True, confirm_history=True, reason='Created in error')
        self.assertEqual(decisions.context_summary(keep)['events'], before)
        self.assertEqual([item['id'] for item in self.get('/api/sod/periods')['items']], [keep])

    def test_comparison_of_remaining_periods_works_after_deletion(self):
        first, second, third = self.new_period('One'), self.new_period('Two'), self.new_period('Three')
        self.delete(second, 'Two')
        result = self.get('/api/sod/periods/compare', left=first, right=third)
        self.assertEqual(result['summary']['Unchanged'], 3)
        response = self.client.get('/api/sod/periods/compare', params={'left': first, 'right': second}, headers={'X-SAP-Lens': 'synthetic-governance-session'})
        self.assertEqual(response.status_code, 404)

    def test_stale_revision_deletion_is_rejected_and_nothing_is_orphaned(self):
        pid = self.new_period('Stale')
        body = dict(expected_revision=0, confirm_name='Stale', actor='A')
        self.post(f'/api/sod/periods/{pid}/delete', body, 409)
        self.assertEqual(len(self.get('/api/sod/periods')['items']), 1)
        summary = decisions.context_summary(pid)
        self.assertEqual((summary['events'], summary['actions'], summary['reports']), (0, 0, []))


class RestartTests(PeriodV2Case):
    def test_decisions_actions_and_frozen_period_restore_in_a_fresh_process(self):
        import json
        import subprocess
        pid = self.new_period('Restart period')
        self.decide_everything(pid)
        remove = self.assignment_item('SYN_A', 'ROLE_A2', 'A', pid)
        self.decide('assignment', [remove], 'Remove', context=pid)
        view = self.get('/api/sod/remediation', context=pid)
        self.post('/api/sod/remediation/actions', dict(context=pid, expected_revision=view['revision'], actor='Owner', user='SYN_A', assignment_id=remove['key'], role='ROLE_A2',
                                                         recommended='Remove assignment', reason='Duplicate coverage', owner='Access team'))
        for state in ('In review', 'Ready for approval'):
            self.move(pid, state)
        self.approve(pid)
        expected = self.get(f'/api/sod/periods/{pid}')
        script = ('import json,sys;import sod_decisions as d,sod_periods as p;'
                  'data=d.read();details=p.details(sys.argv[1]);'
                  'print(json.dumps(dict(events=sum(len(e) for k in data.contexts[sys.argv[1]].values() for e in k.values()),actions=len(data.actions),'
                  'state=details["period"]["state"],checksum=details["checksum"],frozen=len(details["snapshot"]["decisions"]["actions"]))))')
        result = subprocess.run([sys.executable, '-B', '-c', script, pid], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, env=os.environ.copy())
        self.assertEqual(result.returncode, 0, result.stderr)
        restored = json.loads(result.stdout)
        self.assertEqual((restored['state'], restored['checksum'], restored['actions'], restored['frozen']), ('Approved', expected['checksum'], 1, 1))
        self.assertEqual(restored['events'], 5 + 3 + 1)
