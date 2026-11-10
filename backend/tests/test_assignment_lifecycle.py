"""Review revalidation across source revisions: unchanged, changed, removed, reappearing and ambiguous assignments; history is never rewritten."""
import sys
from pathlib import Path
import unittest
import unittest.mock

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
        self.assertTrue(all(item.state == 'present' and not item.reappeared_at for item in lifecycle.read().items.values()))
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

    def test_only_decided_assignments_are_tracked(self):
        self.keep('SYN_A', 'ROLE_A1')
        self.publish(drop={'SYN_A': {'ROLE_A1', 'ROLE_B'}})
        self.assertEqual(len(lifecycle.read().items), 1)


def person(email=None, first='', last=''):
    return dict(emails={email} if email else set(), names={(first, last)} if first or last else set())


class Hardening(LifecycleCase):
    def with_people(self, **people):
        """Publish the same assignments with identity evidence (SAP e-mail / names) per user."""
        state = snapshot()
        for name, evidence in people.items():
            state.users.users[name].update(evidence)
        cache._cache = state
        self.revision_number += 1
        settings = config.get_settings().model_copy(deep=True)
        settings.data_lifecycle.sources['users'] = SourceSnapshot(snapshot=f'{self.revision_number:064x}', path=str(self.root / 'users.csv'), imported_at='2026-10-27T00:00:00+00:00', checked_at='2026-10-27T00:00:00+00:00')
        config.save_configuration(settings, settings.revision)
        return lifecycle.observe()

    def basis(self):
        return self.row()['decision_summary']['basis']

    def health(self, **params):
        for name, record in cache.get_snapshot().users.users.items():       # the synthetic fixture lacks the fields Data Health reads
            record.update(username=name, names=record.get('names', set()))
            for account in record['accounts']:
                account.setdefault('user_type', 'A')
        cache.get_snapshot().users.report = {'parsed_rows': 1}
        return self.get('/api/data-health', **params)

    # identity evidence ----------------------------------------------------------------------------------------------------------------
    def test_a_username_whose_email_and_name_changed_completely_does_not_inherit_the_decision(self):
        self.with_people(SYN_A=person('ann@example.test', 'Ann', 'Alpha'))
        self.keep()
        self.with_people(SYN_A=person('ann@example.test', 'Ann', 'Alpha'))
        before = self.events()
        self.assertEqual(self.row()['decision'], 'Keep')
        self.assertEqual(self.with_people(SYN_A=person('bob@example.test', 'Bob', 'Beta')), 1)
        self.assertEqual((self.row()['decision'], self.basis()), ('Outdated', lifecycle.IDENTITY))
        self.assertEqual(self.events(), before)
        self.decide('assignment', [self.assignment_item('SYN_A', 'ROLE_A1')], 'Keep')       # the new reviewer decision is current again
        self.assertEqual(self.row()['decision'], 'Keep')

    def test_continuity_survives_a_renamed_mailbox_or_a_changed_surname_but_not_both(self):
        self.with_people(SYN_A=person('ann@example.test', 'Ann', 'Alpha'))
        self.keep(); self.with_people(SYN_A=person('ann@example.test', 'Ann', 'Alpha'))
        self.assertEqual(self.with_people(SYN_A=person('ann.alpha@example.test', 'Ann', 'Alpha')), 0)    # same name, new mailbox
        self.assertEqual(self.with_people(SYN_A=person('ann.alpha@example.test', 'Ann', 'Gamma')), 0)    # same mailbox, new surname
        self.assertEqual(self.row()['decision'], 'Keep')

    def test_missing_or_shared_identity_evidence_proves_nothing_in_either_direction(self):
        self.with_people(SYN_A=person('ann@example.test', 'Ann', 'Alpha'))
        self.keep(); self.with_people(SYN_A=person('ann@example.test', 'Ann', 'Alpha'))
        self.assertEqual(self.with_people(SYN_A=person()), 0)                              # export without e-mail/name
        self.assertEqual(self.with_people(SYN_A=person('x@example.test'), SYN_B=person('x@example.test')), 0)   # a shared mailbox identifies nobody
        self.assertEqual(self.row()['decision'], 'Keep')

    # integrity of the lifecycle memory ------------------------------------------------------------------------------------------------
    def damage(self, how):
        path = lifecycle._path()
        if how == 'garbage':
            path.write_text('{not json')
        elif how == 'checksum':
            import json
            body = json.loads(path.read_text()); body['observed_source'] = 'tampered'; path.write_text(json.dumps(body))
        elif how == 'missing':
            path.unlink()

    def test_damaged_missing_or_tampered_memory_makes_every_assignment_decision_outdated_not_current(self):
        self.keep('SYN_A', 'ROLE_A1'); self.keep('SYN_A', 'ROLE_B', 'B')
        self.publish()
        before = self.events()
        for how, state in (('garbage', 'corrupt'), ('checksum', 'corrupt'), ('missing', 'missing')):
            with self.subTest(how):
                lifecycle.rebaseline('Admin One')
                self.assertEqual(self.row()['decision'], 'Keep')
                self.damage(how)
                lifecycle._cache.clear()
                self.assertEqual(lifecycle.load()[1], state)
                rows = {r['role']: r for r in self.subject('SYN_A')['overview']['assignments']}
                self.assertEqual((rows['ROLE_A1']['decision'], rows['ROLE_B']['decision']), ('Outdated', 'Outdated'))
                self.assertEqual(rows['ROLE_A1']['decision_summary']['basis'], lifecycle.UNAVAILABLE)
                self.assertEqual(lifecycle.observe(), 'blocked')                              # never repaired silently
                self.assertEqual(self.events(), before)

    def test_undecided_assignments_and_other_review_kinds_are_untouched_by_damaged_memory(self):
        self.decide('activity', [self.activity_item('SYN_A', 'A')], 'Approved')
        lifecycle._path().write_text('garbage')
        lifecycle._cache.clear()
        activity = next(r for r in self.subject('SYN_A')['overview']['activities'] if r['activity'] == 'A')
        self.assertEqual(activity['decision'], 'Approved')
        self.assertTrue(all(r['decision'] == 'Pending' for r in self.subject('SYN_A')['overview']['assignments']))

    def test_an_old_backup_restored_over_newer_memory_is_stale_and_fails_safe(self):
        self.keep(); self.publish()
        older = lifecycle._path().read_bytes()
        self.publish(drop={'SYN_A': {'ROLE_A1'}}); self.publish()                              # absent, then reappeared: revision moved on
        self.assertEqual(self.row()['decision'], 'Outdated')
        lifecycle._path().write_bytes(older)                                                  # an older backup comes back
        lifecycle._cache.clear()
        data, state, detail = lifecycle.load()
        self.assertEqual(state, 'stale')
        self.assertIn('older than', detail)
        self.assertEqual(self.basis(), lifecycle.UNAVAILABLE)

    def test_a_backup_from_before_the_feature_over_an_established_installation_is_missing_not_trusted(self):
        self.keep(); self.publish()
        self.assertEqual(self.row()['decision'], 'Keep')
        lifecycle._path().unlink(); lifecycle._cache.clear()                                   # restore replaced the JSON roots; the store (kept) remembers
        self.assertEqual(lifecycle.load()[1], 'missing')
        self.assertEqual(self.row()['decision'], 'Outdated')

    def test_a_fresh_or_upgraded_installation_without_any_memory_starts_a_baseline_silently(self):
        import shutil
        self.keep()
        lifecycle._path().unlink(missing_ok=True)
        shutil.rmtree(lifecycle.store_db_dir(), ignore_errors=True) if hasattr(lifecycle, 'store_db_dir') else None
        import store_db
        shutil.rmtree(store_db.directory(), ignore_errors=True)
        lifecycle._cache.clear(); lifecycle._established.clear()
        self.assertEqual(lifecycle.load()[1], 'ok')                                           # nothing was ever established: behave as before
        self.assertEqual(self.row()['decision'], 'Keep')

    def test_files_written_before_checksums_existed_are_accepted_and_sealed_on_the_next_write(self):
        self.keep(); self.publish(drop={'SYN_A': {'ROLE_A1'}})
        import json
        body = json.loads(lifecycle._path().read_text()); body.pop('digest'); lifecycle._path().write_text(json.dumps(body)); lifecycle._cache.clear()
        self.assertEqual(lifecycle.load()[1], 'ok')
        self.publish(); self.assertTrue(json.loads(lifecycle._path().read_text())['digest'])

    def test_a_valid_lifecycle_file_restored_to_another_installation_is_trusted(self):
        import tempfile
        import os
        from unittest.mock import patch as patch_env
        self.keep(); self.publish(drop={'SYN_A': {'ROLE_A1'}})
        raw = lifecycle._path().read_bytes()
        with tempfile.TemporaryDirectory() as other, patch_env.dict(os.environ, {'SAP_LENS_CONFIG_DIR': other}):
            config.get_settings.cache_clear()
            (Path(other) / 'assignment-lifecycle.json').write_bytes(raw)
            self.assertEqual(lifecycle.load()[1], 'ok')
        config.get_settings.cache_clear()

    def test_rebaseline_is_explicit_keeps_the_damaged_copy_and_restores_applicability(self):
        self.keep(); self.publish()
        lifecycle._path().write_text('garbage'); lifecycle._cache.clear()
        self.assertEqual(self.post('/api/storage/lifecycle/rebaseline', {'confirm': False}, 422)['detail'][0]['type'] if False else self.client.post('/api/storage/lifecycle/rebaseline', json={'confirm': False}, headers={'X-SAP-Lens': 'synthetic-governance-session'}).status_code, 422)
        self.assertEqual(self.row()['decision'], 'Outdated')                                   # unchanged until an administrator acts
        result = self.post('/api/storage/lifecycle/rebaseline', {'confirm': True})
        self.assertEqual(result['review_continuity']['state'], 'ok')
        self.assertTrue(list(lifecycle._path().parent.glob('assignment-lifecycle.json.before-rebaseline-*')))
        self.assertEqual(self.row()['decision'], 'Keep')
        self.assertTrue(lifecycle.read().baseline['by'])

    def test_problems_surface_in_data_health_diagnostics_and_storage_status(self):
        self.keep(); self.publish()
        health = {f['id']: f for f in self.health()['findings']}
        self.assertEqual((health['lifecycle_integrity']['count'], health['reappeared_assignments']['count']), (0, 0))
        lifecycle._path().write_text('garbage'); lifecycle._cache.clear()
        health = {f['id']: f for f in self.health()['findings']}
        self.assertEqual((health['lifecycle_integrity']['count'], health['lifecycle_integrity']['severity']), (1, 'warning'))
        items = self.health(finding='lifecycle_integrity')['items']
        self.assertEqual((items[0]['username'], items[0]['identifier']), ('SYN_A', 'ROLE_A1'))
        self.assertEqual(self.get('/api/storage/status')['review_continuity']['state'], 'corrupt')
        self.assertEqual(self.get('/api/diagnostics/export')['review_continuity'], 'corrupt')

    def test_reappeared_assignments_awaiting_review_are_listed_until_a_new_decision(self):
        self.keep(); self.publish(drop={'SYN_A': {'ROLE_A1'}}); self.publish()
        listed = self.health(finding='reappeared_assignments')
        self.assertEqual([(i['username'], i['identifier'], i['reason']) for i in listed['items']], [('SYN_A', 'ROLE_A1', 'reappeared')])
        self.decide('assignment', [self.assignment_item('SYN_A', 'ROLE_A1')], 'Keep')
        self.assertEqual(self.health(finding='reappeared_assignments')['items'], [])

    def test_exports_keep_their_schema_and_status_value_while_the_api_explains_the_reason(self):
        self.keep(); self.publish(drop={'SYN_A': {'ROLE_A1'}}); self.publish()
        response = self.client.get('/api/sod/explorer/access_list/export', headers={'X-SAP-Lens': 'synthetic-governance-session'})
        header, *rows = response.text.strip().splitlines()
        self.assertIn('ASSIGNMENT_REVIEW', header)
        self.assertEqual(header.lstrip('\ufeff').count(';') + 1, 11)                          # same 11 columns as before
        self.assertTrue(any('"ROLE_A1"' in row and '"Outdated"' in row for row in rows))      # the status value is unchanged; no column was added
        self.assertEqual(self.basis(), governance.REAPPEARED)

    def test_status_reads_do_not_reparse_the_file_for_every_request(self):
        self.keep(); self.publish()
        lifecycle.applicability()
        with unittest.mock.patch.object(Path, 'read_bytes', side_effect=AssertionError('re-read')):
            for _ in range(5):
                lifecycle.applicability()


if __name__ == '__main__':
    unittest.main()
