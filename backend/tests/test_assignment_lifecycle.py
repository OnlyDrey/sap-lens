"""Review revalidation across source revisions: unchanged, changed, removed, reappearing and ambiguous assignments; history is never rewritten."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import assignment_lifecycle as lifecycle
import cache
import config
import sod_decisions as decisions
import sod_governance as governance
import sod_scope as scope
from config_models import SourceSnapshot
from test_sod_analysis_api import assignment
from test_sod_governance import GovernanceCase, snapshot


class LifecycleCase(GovernanceCase):
    def setUp(self):
        super().setUp()
        self.revision_number = 0
        self.publish()

    def publish(self, drop=(), drop_users=(), replace=None, sod=True):
        """A new users revision: same fixture dataset minus some assignments/users, as a refresh would activate it."""
        state = snapshot()
        for user, roles in dict(drop).items() if isinstance(drop, dict) else {}.items():
            state.users.users[user]['assignments'] = [a for a in state.users.users[user]['assignments'] if a['role_name'] not in roles]
        for user in drop_users:
            del state.users.users[user]
        for user, assignments in (replace or {}).items():
            state.users.users[user]['assignments'] = assignments
        if not sod:
            state.sod = {}
        self.revision_number += 1
        settings = config.get_settings().model_copy(deep=True)
        marker = f'{self.revision_number:064x}'
        settings.data_lifecycle.sources['users'] = SourceSnapshot(snapshot=marker, path=str(self.root / 'users.csv'), imported_at='2026-10-27T00:00:00+00:00', checked_at='2026-10-27T00:00:00+00:00')
        config.save_configuration(settings, settings.revision)
        cache._cache = state
        return lifecycle.observe()

    def keep(self, user='SYN_A', role='ROLE_A1', activity='A'):
        item = self.assignment_item(user, role, activity)
        self.decide('assignment', [item], 'Keep')
        return item

    def row(self, user='SYN_A', role='ROLE_A1'):
        return next((r for r in self.subject(user)['overview']['assignments'] if r['role'] == role), None)

    def events(self):
        return decisions.read().model_dump()


class Revalidation(LifecycleCase):
    def test_unchanged_assignments_keep_their_decision_and_nothing_is_recorded(self):
        item = self.keep()
        self.assertEqual(self.publish(), 0)
        self.assertEqual(self.row()['decision'], 'Keep')
        self.assertEqual(lifecycle.read().items, {})
        self.assertEqual(self.publish(), 0)                                           # a further identical revision changes nothing either
        self.assertEqual(self.row()['id'], item['key'])

    def test_a_changed_assignment_is_a_new_identity_and_never_inherits_the_decision(self):
        self.keep()
        self.publish(replace={'SYN_A': [assignment('ROLE_A1', end='2030-12-31'), assignment('ROLE_A2'), assignment('ROLE_B'), assignment('ROLE_C')]})
        changed = self.row()
        self.assertEqual((changed['decision'], changed['valid_to']), ('Pending', '2030-12-31'))      # different validity: not the reviewed assignment

    def test_a_removed_assignment_is_recorded_and_its_decision_is_preserved(self):
        item = self.keep()
        before = self.events()
        self.assertEqual(self.publish(drop={'SYN_A': {'ROLE_A1'}}), 1)
        self.assertIsNone(self.row())
        self.assertEqual(lifecycle.read().items[item['key']].state, 'absent')
        self.assertEqual(self.events(), before)                                                 # decision events and evidence are untouched
        history = self.get('/api/sod/decisions/assignment/history', key=item['key'])
        self.assertEqual(len(history['items'] if 'items' in history else history['events']), 1)

    def test_a_reappearing_assignment_requires_a_new_review(self):
        item = self.keep()
        self.publish(drop={'SYN_A': {'ROLE_A1'}})
        before = self.events()
        self.assertEqual(self.publish(), 1)
        row = self.row()
        self.assertEqual(row['decision'], 'Outdated')                                           # the old approval does not silently return
        self.assertEqual(row['decision_summary']['basis'], governance.REAPPEARED)
        self.assertTrue(row['decision_summary']['stale'])
        self.assertEqual(self.events(), before)                                                 # status is derived; history is not modified
        self.assertIn(item['key'], lifecycle.reappeared())
        self.decide('assignment', [self.assignment_item('SYN_A', 'ROLE_A1')], 'Keep')           # a new decision after the reappearance is current again
        self.assertEqual(self.row()['decision'], 'Keep')
        self.publish()
        self.assertEqual(self.row()['decision'], 'Keep')
        history = self.get('/api/sod/decisions/assignment/history', key=item['key'])
        self.assertEqual(len(history['items'] if 'items' in history else history['events']), 2)

    def test_an_outdated_reappearance_does_not_grant_activity_coverage_or_approval(self):
        self.keep('SYN_A', 'ROLE_A1'); self.keep('SYN_A', 'ROLE_A2')
        self.publish(drop={'SYN_A': {'ROLE_A1'}}); self.publish()
        activity = next(r for r in self.subject('SYN_A')['overview']['activities'] if r['activity'] == 'A')
        self.assertEqual(activity['decision_summary']['label'], 'Approved')                     # ROLE_A2 is still validly kept
        self.decide('assignment', [self.assignment_item('SYN_A', 'ROLE_A2')], 'Pending')
        activity = next(r for r in self.subject('SYN_A')['overview']['activities'] if r['activity'] == 'A')
        self.assertNotEqual(activity['decision_summary']['label'], 'Approved')                  # the reappeared one no longer supports approval

    def test_a_disappearing_and_returning_user_does_not_inherit_decisions(self):
        self.keep('SYN_A', 'ROLE_A1'); self.keep('SYN_A', 'ROLE_B', 'B')
        self.publish(drop_users=('SYN_A',))
        self.assertEqual({v.state for v in lifecycle.read().items.values()}, {'absent'})
        self.publish()
        rows = {r['role']: r['decision'] for r in self.subject('SYN_A')['overview']['assignments']}
        self.assertEqual((rows['ROLE_A1'], rows['ROLE_B']), ('Outdated', 'Outdated'))           # the username may belong to someone else now

    def test_ambiguous_mapping_changes_nothing_in_either_direction(self):
        item = self.keep()
        partly = [dict(assignment('ROLE_A2'), match_status='unmatched'), assignment('ROLE_B'), assignment('ROLE_C')]
        self.assertEqual(self.publish(replace={'SYN_A': partly}), 0)                            # ROLE_A1 missing, but the user is only partly mapped
        self.assertNotIn(item['key'], lifecycle.read().items)
        self.assertEqual(self.publish(), 0)                                                     # back in the data: it was never marked absent, so no reappearance
        self.assertEqual(self.row()['decision'], 'Keep')

    def test_unavailable_sod_or_users_never_marks_anything(self):
        self.keep()
        self.assertEqual(self.publish(drop={'SYN_A': {'ROLE_A1'}}, sod=False), 'unassessable')
        self.assertEqual(lifecycle.read().items, {})

    def test_observation_is_idempotent_per_revision(self):
        self.keep()
        self.publish(drop={'SYN_A': {'ROLE_A1'}})
        revision = lifecycle.read().revision
        self.assertEqual(lifecycle.observe(), 'current')
        self.assertEqual(lifecycle.read().revision, revision)

    def test_frozen_assessments_ignore_later_reappearance(self):
        item = self.keep()
        self.publish(drop={'SYN_A': {'ROLE_A1'}}); self.publish()
        bundle = scope.load('current')
        live = scope.states_for(bundle, scope.model_for(bundle))['assignment'][item['key']][0]
        self.assertEqual(live, 'Outdated')
        bundle['frozen'] = True                                                                 # a frozen period keeps its captured lifecycle
        frozen = scope.states_for(bundle, scope.model_for(bundle))['assignment'][item['key']][0]
        self.assertEqual(frozen, 'Keep')

    def test_unreadable_lifecycle_memory_degrades_to_no_reappearance_marks(self):
        self.keep()
        self.publish(drop={'SYN_A': {'ROLE_A1'}}); self.publish()
        lifecycle._path().write_text('{not json')
        with self.assertLogs('sap-lens', 'WARNING'):
            self.assertEqual(lifecycle.reappeared(), {})
        self.assertEqual(self.row()['decision'], 'Keep')                                        # the original behaviour, not an error

    def test_only_decided_assignments_are_tracked(self):
        self.keep('SYN_A', 'ROLE_A1')
        self.publish(drop={'SYN_A': {'ROLE_A1', 'ROLE_B'}})
        self.assertEqual(len(lifecycle.read().items), 1)


if __name__ == '__main__':
    unittest.main()
