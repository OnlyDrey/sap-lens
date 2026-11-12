"""Functional Group catalogue, classification, history, integrity and backup validation."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi import HTTPException
import functional_groups as fg


class Store(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        patcher = patch.object(fg, 'config_dir', return_value=Path(self.directory.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.directory.cleanup)

    def group(self, name='Purchasing'):
        return fg.create_group(name)['id']


class Catalogue(Store):
    def test_names_are_unique_after_normalisation(self):
        self.group('Purchasing')
        for duplicate in ('purchasing', '  PURCHASING ', 'Purchasing'):
            with self.assertRaises(HTTPException) as caught:
                fg.create_group(duplicate)
            self.assertEqual(caught.exception.status_code, 409)

    def test_rename_description_archive_restore_and_counts(self):
        gid, other = self.group(), self.group('Logistics')
        fg.classify('U1', gid, 'r', 0, 'rev')
        fg.classify('U2', gid, 'r', 0, 'rev')
        self.assertEqual({g['name']: g['user_count'] for g in fg.list_groups()}, {'Purchasing': 2, 'Logistics': 0})
        with self.assertRaises(HTTPException):
            fg.update_group(gid, name='logistics')
        fg.update_group(gid, name='Procurement', description='Buying')
        fg.set_group_status(gid, 'archived')
        self.assertEqual(fg.list_groups(include_archived=False)[0]['id'], other)
        archived = next(g for g in fg.list_groups() if g['id'] == gid)
        self.assertEqual((archived['status'], archived['user_count'], archived['description']), ('archived', 2, 'Buying'))
        self.assertEqual(fg.set_group_status(gid, 'active')['status'], 'active')

    def test_archived_group_keeps_users_but_cannot_be_newly_assigned(self):
        gid = self.group()
        fg.classify('U1', gid, '', 0, 'rev')
        fg.set_group_status(gid, 'archived')
        with self.assertRaises(HTTPException):
            fg.classify('U2', gid, '', 0, 'rev')
        self.assertEqual(fg.classify('U1', gid, 'still valid', 1, 'rev')['status'], 'Confirmed')

    def test_invalid_names_are_rejected(self):
        for bad in ('', '   ', 'x' * 81, 'a\x01b'):
            with self.assertRaises(HTTPException):
                fg.create_group(bad)


class Classification(Store):
    def test_assign_confirm_remove_write_append_only_history_per_membership(self):
        a, b = self.group('A'), self.group('B')
        user, outcome = fg.add_membership('U1', a, 'start', 0, 'rev')
        self.assertEqual((user['revision'], outcome), (1, 'added'))
        fg.add_membership('U1', b, 'second function', 1, 'rev2')
        fg.remove_membership('U1', a, 'left the function', 2, 'rev')
        events = [(e['event'], e['previous_group'], e['new_group']) for e in reversed(fg.user_history('u1')['items'])]
        self.assertEqual(events, [('assigned', None, a), ('assigned', None, b), ('removed', a, None)])
        state = fg.public_user(fg.read(), 'U1')
        self.assertEqual([m['group_id'] for m in state['memberships']], [b])
        self.assertEqual(fg.user_history('U1')['items'][1]['actor'], 'rev2')

    def test_a_user_holds_several_groups_and_a_group_holds_several_users(self):
        a, b, c = self.group('A'), self.group('B'), self.group('C')
        fg.add_membership('U1', a, '', 0, 'r')
        fg.add_membership('U1', b, '', 1, 'r')
        fg.add_membership('U2', b, '', 0, 'r')
        data = fg.read()
        self.assertEqual(sorted(fg.public_user(data, 'U1')['group_ids']), sorted([a, b]))
        self.assertEqual(fg.counts(data), {a: 1, b: 2})
        self.assertEqual({g['id']: g['user_count'] for g in fg.list_groups()}[c], 0)
        unique_users = len({k for k, u in data['users'].items() if u['memberships']})
        self.assertEqual(unique_users, 2)  # two users, three memberships: aggregates must count users once
        single = fg.public_user(data, 'U2')
        self.assertEqual((single['group_id'], len(fg.public_user(data, 'U1')['memberships'])), (b, 2))
        self.assertIsNone(fg.public_user(data, 'U1')['group_id'])  # legacy singular field only when exactly one membership

    def test_adding_an_existing_membership_is_an_idempotent_noop_and_never_duplicates(self):
        a = self.group('A')
        fg.add_membership('U1', a, 'x', 0, 'r')
        before = json.dumps(fg.read(), sort_keys=True)
        user, outcome = fg.add_membership('U1', a, 'again', 1, 'r')
        self.assertEqual((outcome, user['revision'], len(user['memberships'])), ('unchanged', 1, 1))
        self.assertEqual(json.dumps(fg.read(), sort_keys=True), before)

    def test_removing_one_membership_keeps_the_others_and_their_confirmation(self):
        a, b = self.group('A'), self.group('B')
        fg.add_membership('U1', a, '', 0, 'first')
        fg.add_membership('U1', b, '', 1, 'second')
        kept = next(m for m in fg.public_user(fg.read(), 'U1')['memberships'] if m['group_id'] == b)
        fg.remove_membership('U1', a, 'no longer', 2, 'third')
        after = fg.public_user(fg.read(), 'U1')
        self.assertEqual([m['group_id'] for m in after['memberships']], [b])
        self.assertEqual((after['memberships'][0]['confirmed_by'], after['memberships'][0]['confirmed_at']), (kept['confirmed_by'], kept['confirmed_at']))
        with self.assertRaises(HTTPException):
            fg.remove_membership('U1', a, 'twice', 3, 'third')  # no longer a member

    def test_identity_is_case_insensitive_and_memberships_accumulate(self):
        a, b = self.group('A'), self.group('B')
        fg.add_membership('abc', a, '', 0, 'rev')
        fg.add_membership('ABC', b, '', 1, 'rev')
        data = fg.read()
        self.assertEqual(len(data['users']), 1)
        self.assertEqual(len(fg.public_user(data, 'Abc')['memberships']), 2)

    def test_stale_revision_never_overwrites(self):
        a, b = self.group('A'), self.group('B')
        fg.add_membership('U1', a, '', 0, 'rev')
        with self.assertRaises(HTTPException) as caught:
            fg.add_membership('U1', b, '', 0, 'other')
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(fg.public_user(fg.read(), 'U1')['group_id'], a)

    def test_unknown_group_and_clearing_nothing_are_refused(self):
        with self.assertRaises(HTTPException):
            fg.add_membership('U1', 'fg_000000000000', '', 0, 'rev')
        with self.assertRaises(HTTPException):
            fg.classify('U1', None, 'x', 0, 'rev')

    def test_legacy_single_group_operation_replaces_with_history_for_each_step(self):
        a, b = self.group('A'), self.group('B')
        fg.classify('U1', a, '', 0, 'r')
        fg.classify('U1', b, 'moved', 1, 'r')
        self.assertEqual(fg.public_user(fg.read(), 'U1')['group_ids'], [b])
        self.assertEqual([e['event'] for e in reversed(fg.user_history('U1')['items'])], ['assigned', 'removed', 'assigned'])
        fg.classify('U1', None, 'left', 2, 'r')
        self.assertEqual(fg.public_user(fg.read(), 'U1')['status'], 'Unassigned')

    def test_review_flag_marks_every_membership_and_each_is_reconfirmed_on_its_own(self):
        a, b = self.group('A'), self.group('B')
        self.assertFalse(fg.flag_for_review('U1', 'c1', 'Department changed'))  # nothing to reconfirm
        fg.add_membership('U1', a, '', 0, 'rev')
        fg.add_membership('U1', b, '', 1, 'rev')
        self.assertTrue(fg.flag_for_review('U1', 'c1', 'Department changed'))
        self.assertFalse(fg.flag_for_review('U1', 'c1', 'Department changed'))
        state = fg.public_user(fg.read(), 'U1')
        self.assertEqual((state['status'], sorted(m['status'] for m in state['memberships'])), ('Needs review', ['Needs review', 'Needs review']))
        done, outcome = fg.add_membership('U1', a, 'still purchasing', state['revision'], 'rev', 'c1')
        self.assertEqual(outcome, 'reconfirmed')
        self.assertEqual({m['group_id']: m['status'] for m in done['memberships']}, {a: 'Confirmed', b: 'Needs review'})
        self.assertEqual(done['status'], 'Needs review')  # one membership still needs its review
        self.assertFalse(fg.flag_for_review('U1', 'c1', 'Department changed'))
        self.assertTrue(fg.flag_for_review('U1', 'c2', 'Title changed'))  # only the Confirmed membership is flagged again
        events = [e['event'] for e in reversed(fg.user_history('U1')['items'])]
        self.assertEqual(events, ['assigned', 'assigned', 'review_required', 'review_required', 'reconfirmed', 'review_required'])

    def test_manager_change_is_signal_only(self):
        gid = self.group()
        fg.add_membership('U1', gid, '', 0, 'rev')
        self.assertTrue(fg.note_manager_change('U1', 'm1', 'Manager changed'))
        self.assertFalse(fg.note_manager_change('U1', 'm1', 'Manager changed'))
        state = fg.public_user(fg.read(), 'U1')
        self.assertEqual((state['status'], state['revision']), ('Confirmed', 1))

    def test_explicit_unassigned_review_outcome(self):
        fg.classify('U9', None, 'no function applies', 0, 'rev', 'c7')
        self.assertEqual(fg.public_user(fg.read(), 'U9')['status'], 'Unassigned')


class CoarseClock(Store):
    """Windows' wall clock can return the same value for events a few milliseconds apart. A genuine organizational change detected in the same
    tick as a confirmation must still require review (the safe direction), and a change must never be lost to a tie."""
    def test_change_in_the_same_clock_tick_as_the_confirmation_still_flags_review(self):
        stamp = '2026-05-01T10:00:00.015000+00:00'
        gid = self.group()
        with patch.object(fg, 'now', return_value=stamp):
            fg.classify('U1', gid, 'r', 0, 'rev')
        event = dict(id='e1', key='u1@example.test', detected_at=stamp, fields=['department'], previous_department='Finance', current_department='Procurement',
                     previous_title='', current_title='')
        self.assertEqual(fg.apply_organizational_changes({'U1': 'u1@example.test'}, [event], []), 1)
        self.assertEqual(fg.public_user(fg.read(), 'U1')['status'], 'Needs review')

    def test_manager_change_in_the_same_tick_is_recorded_once(self):
        stamp = '2026-05-01T10:00:00.015000+00:00'
        gid = self.group()
        with patch.object(fg, 'now', return_value=stamp):
            fg.classify('U1', gid, 'r', 0, 'rev')
        event = dict(id='m1', key='u1@example.test', detected_at=stamp, previous_manager='One', current_manager='Two')
        self.assertEqual(fg.apply_organizational_changes({'U1': 'u1@example.test'}, [], [event]), 1)
        self.assertEqual(fg.apply_organizational_changes({'U1': 'u1@example.test'}, [], [event]), 0)

    def test_an_older_change_is_still_ignored(self):
        gid = self.group()
        with patch.object(fg, 'now', return_value='2026-05-01T10:00:00.500000+00:00'):
            fg.classify('U1', gid, 'r', 0, 'rev')
        event = dict(id='e0', key='u1@example.test', detected_at='2026-05-01T09:59:59.000000+00:00', fields=['title'], previous_department='', current_department='',
                     previous_title='A', current_title='B')
        self.assertEqual(fg.apply_organizational_changes({'U1': 'u1@example.test'}, [event], []), 0)


class Migration(Store):
    """Format 1 (one group per user) is migrated without losing assignments, confirmation metadata, review state or history."""

    def legacy(self):
        gid = self.group('Legacy')
        stamp = fg.now()
        data = fg.read()
        data.update(format=1)
        data['users'] = {
            fg.user_key('U1'): dict(username='U1', group_id=gid, status='Confirmed', revision=3, confirmed_at=stamp, confirmed_by='Old Reviewer', rationale='r', updated_at=stamp, review=None, handled=['c0']),
            fg.user_key('U2'): dict(username='U2', group_id=gid, status='Needs review', revision=2, confirmed_at=stamp, confirmed_by='Rev', rationale='', updated_at=stamp,
                                   review=dict(change_id='c1', reason='Department changed', required_since=stamp), handled=[]),
            fg.user_key('U3'): dict(username='U3', group_id=None, status='Unassigned', revision=1, confirmed_at=None, confirmed_by='', rationale='none applies', updated_at=stamp, review=None, handled=['c9']),
        }
        data['history'] = [dict(id='a' * 32, event='assigned', user_key=fg.user_key('U1'), username='U1', previous_group=None, new_group=gid, previous_status='Unassigned',
                                new_status='Confirmed', actor='Old Reviewer', timestamp=stamp, reason='r', change_id='')]
        data['rules'] = [dict(id='fr_' + 'a' * 12, group_id=gid, department='Supply Chain', title_contains='', created=stamp)]
        return gid, data

    def test_every_assignment_becomes_one_membership_with_its_metadata(self):
        gid, data = self.legacy()
        migrated = fg.validate_storage(data)
        self.assertEqual(migrated['format'], fg.FORMAT)
        u1 = migrated['users'][fg.user_key('U1')]
        self.assertEqual((u1['revision'], u1['handled'], u1['memberships'][gid]['confirmed_by'], u1['memberships'][gid]['status']), (3, ['c0'], 'Old Reviewer', 'Confirmed'))
        self.assertEqual(migrated['users'][fg.user_key('U2')]['memberships'][gid]['review']['change_id'], 'c1')
        u3 = migrated['users'][fg.user_key('U3')]
        self.assertEqual((u3['memberships'], u3['revision'], u3['handled']), ({}, 1, ['c9']))
        self.assertEqual(migrated['history'], data['history'])

    def test_a_legacy_file_is_read_migrated_and_preserved_once_before_it_is_replaced(self):
        gid, data = self.legacy()
        path = Path(self.directory.name) / fg.FILE
        path.write_text(json.dumps(data))
        state = fg.public_user(fg.read(), 'U1')
        self.assertEqual((state['group_id'], state['revision']), (gid, 3))
        copy = path.with_name(path.name + '.format1.bak')
        self.assertEqual(json.loads(copy.read_text())['format'], 1)
        fg.add_membership('U3', gid, '', 1, 'r')  # first write persists format 2
        self.assertEqual(json.loads(path.read_text())['format'], fg.FORMAT)
        self.assertEqual(json.loads(copy.read_text())['format'], 1)
        self.assertEqual(len({k for k, u in fg.read()['users'].items() if gid in u['memberships']}), 3)

    def test_legacy_rules_keep_exact_department_matching(self):
        gid, data = self.legacy()
        rule = fg.validate_storage(data)['rules'][0]
        self.assertEqual(rule['department_mode'], 'equals')
        self.assertIsNotNone(fg.rule_matches(rule, 'supply chain', ''))
        self.assertIsNone(fg.rule_matches(rule, 'Supply Chain Planning', ''))  # not silently broadened


class Persistence(Store):
    def test_file_reads_and_replacements_share_the_storage_lock(self):
        from contextlib import contextmanager
        self.group()
        original_open, original_write = Path.open, fg.atomic_write

        @contextmanager
        def checked_open(path, *args, **kwargs):
            self.assertTrue(fg.lock._is_owned(), 'a Windows read handle must not overlap atomic replacement')
            with original_open(path, *args, **kwargs) as stream:
                yield stream
                self.assertTrue(fg.lock._is_owned(), 'close the read handle before releasing the lock')

        def checked_write(*args):
            self.assertTrue(fg.lock._is_owned(), 'replacement must use the same lock as readers')
            return original_write(*args)

        with patch.object(Path, 'open', checked_open), patch.object(fg, 'atomic_write', checked_write):
            data = fg.read()
            fg.write(data)

    def test_round_trip_and_validation(self):
        gid = self.group()
        fg.add_membership('U1', gid, 'r', 0, 'rev')
        reread = json.loads((Path(self.directory.name) / fg.FILE).read_text())
        self.assertIn(gid, fg.validate_storage(reread)['users'][fg.user_key('U1')]['memberships'])

    def test_validation_rejects_contradictions_and_broken_references(self):
        gid = self.group()
        fg.add_membership('U1', gid, '', 0, 'rev')
        base = json.loads((Path(self.directory.name) / fg.FILE).read_text())
        key = fg.user_key('U1')
        def broken(change):
            data = json.loads(json.dumps(base)); change(data)
            with self.assertRaises(ValueError):
                fg.validate_storage(data)
        broken(lambda d: d['users'][key]['memberships'].update({'fg_ffffffffffff': d['users'][key]['memberships'][gid]}))
        broken(lambda d: d['users'][key]['memberships'][gid].update(status='Unassigned'))
        broken(lambda d: d['users'][key]['memberships'][gid].update(status='Needs review'))  # needs a review record
        broken(lambda d: d['users'][key]['memberships'][gid].update(review=dict(change_id='c')))  # a review record needs the status
        broken(lambda d: d['users'][key].update(revision=0))
        broken(lambda d: d['history'][0].update(new_group='fg_ffffffffffff'))
        broken(lambda d: d.update(format=3))
        broken(lambda d: d['rules'].append(dict(id='fr_aaaaaaaaaaaa', group_id=gid, department='', title_contains='')))
        broken(lambda d: d['groups'].update({'fg_aaaaaaaaaaaa': dict(d['groups'][gid], id='fg_aaaaaaaaaaaa', name=' PURCHASING ')}))

    def test_corrupt_file_is_retained_and_reported(self):
        path = Path(self.directory.name) / fg.FILE
        path.write_text('{bad')
        with self.assertRaises(HTTPException) as caught:
            fg.read()
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(path.read_text(), '{bad')

    def test_missing_store_is_empty_and_existing_data_is_untouched(self):
        self.assertEqual(fg.read(), fg.empty())
        self.assertFalse((Path(self.directory.name) / fg.FILE).exists())

    def test_backup_validation_hook_and_restore_of_multiple_memberships(self):
        import application_backups as backups
        import maintenance as engine
        a, b = self.group('A'), self.group('B')
        fg.add_membership('U1', a, '', 0, 'rev')
        fg.add_membership('U1', b, '', 1, 'rev')
        root = Path(self.directory.name)
        backups.validate_store(root)  # valid store passes
        restored = fg.validate_storage(json.loads((root / fg.FILE).read_text()))
        self.assertEqual(sorted(restored['users'][fg.user_key('U1')]['memberships']), sorted([a, b]))
        data = json.loads((root / fg.FILE).read_text())
        data['users'][fg.user_key('U1')]['memberships']['fg_ffffffffffff'] = data['users'][fg.user_key('U1')]['memberships'][a]
        (root / fg.FILE).write_text(json.dumps(data))
        with self.assertRaises(engine.MaintenanceError):
            backups.validate_store(root)


class AccessAnalysis(unittest.TestCase):
    GROUP = dict(id='fg_000000000001', name='Purchasing', status='active')

    @staticmethod
    def state(spec):
        from types import SimpleNamespace
        def user(name, roles):
            return dict(username=name, assignments=[dict(role_name=r, valid_from=f, valid_to=t) for r, f, t in roles])
        return SimpleNamespace(users=SimpleNamespace(users={n.upper(): user(n, r) for n, r in spec.items()}))

    def run_analysis(self, spec, members=None):
        from functional_group_analysis import analyse
        return analyse(self.state(spec), members or list(spec), self.GROUP)

    def test_common_uncommon_and_deviations_use_unique_active_pairs(self):
        base = [('Z_BUY', '20000101', '99991231'), ('Z_PO', '20000101', '99991231')]
        spec = {f'U{i}': list(base) for i in range(5)}
        spec['U5'] = base + [('Z_PAY', '20000101', '99991231'),
                             ('Z_PO', '20000101', '99991231'),   # duplicate interval of a held role: counted once
                             ('Z_OLD', '20000101', '20010101')]  # expired: ignored
        result = self.run_analysis(spec)
        roles = {r['role']: r for r in result['roles']}
        self.assertEqual((roles['Z_BUY']['users'], roles['Z_BUY']['kind']), (6, 'common'))
        self.assertEqual((roles['Z_PAY']['users'], roles['Z_PAY']['kind'], round(roles['Z_PAY']['frequency'], 3)), (1, 'uncommon', 0.167))
        self.assertNotIn('Z_OLD', roles)
        self.assertEqual(roles['Z_PO']['users'], 6)
        self.assertEqual([(u['username'], u['additional_roles']) for u in result['users'] if u['additional_roles']], [('U5', ['Z_PAY'])])
        self.assertEqual((result['deviations'], result['eligible'], result['distinct_roles']), (1, 6, 3))

    def test_drilldown_lists_exactly_the_compared_holders_under_the_same_rules(self):
        base = [('Z_BUY', '20000101', '99991231')]
        spec = {f'U{i}': list(base) for i in range(5)}
        spec['U5'] = base + [('Z_PAY', '20000101', '99991231'), ('Z_OLD', '20000101', '20010101')]
        result = self.run_analysis(spec, members=[*spec, 'GHOST'])
        roles = {r['role']: r for r in result['roles']}
        self.assertEqual(roles['Z_PAY']['holders'], ['U5'])                                  # the expired role has no holder row at all
        self.assertEqual(roles['Z_BUY']['holders'], [f'U{i}' for i in range(6)])
        self.assertEqual([c['username'] for c in result['compared']], [f'U{i}' for i in range(6)])   # the same 6 users used for every frequency
        self.assertEqual(result['eligible'], len(result['compared']))
        self.assertNotIn('GHOST', [c['username'] for c in result['compared']])             # a member without a SAP record is never invented into the population
        self.assertEqual(result['not_in_import'], ['GHOST'])
        self.assertTrue(all(len(r['holders']) == r['users'] for r in result['roles']))

    def test_missing_common_roles_and_deterministic_order(self):
        full = [('A', '20000101', '99991231'), ('B', '20000101', '99991231')]
        spec = {'U1': full, 'U2': full, 'U3': full, 'U4': [full[0]]}
        first = self.run_analysis(spec)
        self.assertEqual(self.run_analysis(dict(reversed(list(spec.items())))), first)
        self.assertEqual([(u['username'], u['missing_common_roles']) for u in first['users'] if u['missing_common_roles']], [('U4', ['B'])])

    def test_small_groups_and_incomplete_coverage_are_limitations_not_conclusions(self):
        result = self.run_analysis({'U1': [('A', '20000101', '99991231')], 'U2': [('B', '20000101', '99991231')]}, members=['U1', 'U2', 'GHOST'])
        self.assertFalse(result['comparable'])
        self.assertEqual(result['not_in_import'], ['GHOST'])
        self.assertTrue(any('not in the SAP user import' in text for text in result['limitations']))
        self.assertTrue(any('at least 3' in text for text in result['limitations']))
        self.assertTrue(all(r['kind'] == 'not compared' for r in result['roles']))
        self.assertTrue(all(not u['additional_roles'] and not u['missing_common_roles'] for u in result['users']))

    def test_endpoint_is_read_only_and_reports_unknown_groups(self):
        import test_account_review as base
        case = type('Case', (), {})()
        case.write_users = lambda: base.AccountReviewTests.write_users(case)
        base.AccountReviewTests.setUp(case)
        try:
            self.assertEqual(case.client.get('/api/functional-groups/analysis/fg_000000000000', headers=base.H).status_code, 404)
            gid = case.client.post('/api/functional-groups', headers=base.H, json=dict(name='Finance')).json()['id']
            for name in ('DEMO_NORMAL', 'DEMO_OPEN'):
                case.client.put(f'/api/functional-groups/users/{name}', headers=base.H, json=dict(group_id=gid, reviewer='R', rationale='', expected_revision=0))
            result = case.client.get(f'/api/functional-groups/analysis/{gid}', headers=base.H).json()
            self.assertEqual((result['members'], result['eligible'], result['comparable']), (2, 2, False))
            self.assertEqual(fg.public_user(fg.read(), 'DEMO_NORMAL')['revision'], 1)  # analysis changed nothing
        finally:
            base.AccountReviewTests.tearDown(case)


class Suggestions(Store):
    def test_rules_match_by_contains_explain_and_consolidate_per_group(self):
        buy, plan = self.group('Purchasing'), self.group('Planning')
        fg.add_rule(buy, department='Supply Chain', title_contains='Purchaser')
        fg.add_rule(buy, title_contains='buyer')
        fg.add_rule(plan, title_contains='planner')
        result = fg.suggest('Global supply  chain operations', 'Senior PURCHASER and Buyer')
        self.assertEqual(result['status'], 'suggested')
        self.assertEqual([g['group_name'] for g in result['groups']], ['Purchasing'])  # two rules, one consolidated group
        self.assertEqual(result['groups'][0]['reasons'], ['Directory Department contains Supply Chain', 'Job Title contains Purchaser', 'Job Title contains buyer'])
        self.assertEqual(len(result['matches']), 2)
        self.assertEqual(fg.suggest('Supply Chain', 'Buyer')['groups'][0]['group_name'], 'Purchasing')  # the title-only rule applies

    def test_and_semantics_and_missing_directory_attributes(self):
        gid = self.group()
        rule = fg.add_rule(gid, department='Supply', title_contains='Purchaser')
        self.assertIsNone(fg.rule_matches(rule, 'Supply Chain', 'Buyer'))  # both conditions are required
        self.assertIsNone(fg.rule_matches(rule, 'Finance', 'Purchaser'))
        self.assertIsNone(fg.rule_matches(rule, '', 'Purchaser'))  # an empty attribute never satisfies a stated condition
        self.assertIsNone(fg.rule_matches(rule, None, None))
        self.assertIsNotNone(fg.rule_matches(rule, 'SUPPLY chain', 'purchaser'))
        title_only = fg.add_rule(gid, title_contains='x')
        self.assertIsNotNone(fg.rule_matches(title_only, '', 'xy'))  # unstated conditions are not required

    def test_multiple_groups_are_all_suggested_and_held_groups_are_marked(self):
        buy, plan = self.group('Purchasing'), self.group('Planning')
        fg.add_rule(buy, department='Supply')
        fg.add_rule(plan, title_contains='planner')
        result = fg.suggest('Supply Chain', 'Planner', None, held=[buy])
        self.assertEqual({g['group_name']: g['already_member'] for g in result['groups']}, {'Purchasing': True, 'Planning': False})
        self.assertEqual(result['status'], 'suggested')

    def test_archived_groups_and_empty_conditions_are_not_suggested(self):
        gid = self.group()
        with self.assertRaises(HTTPException):
            fg.add_rule(gid)
        fg.add_rule(gid, department='Buying')
        with self.assertRaises(HTTPException):
            fg.add_rule(gid, department=' buying ')
        self.assertEqual(fg.suggest('Buying', '')['status'], 'suggested')
        fg.set_group_status(gid, 'archived')
        self.assertEqual(fg.suggest('Buying', '')['status'], 'none')

    def test_update_rule_changes_conditions_and_converts_a_legacy_rule(self):
        gid = self.group()
        rule = fg.add_rule(gid, department='Buying', department_mode='equals')
        self.assertIsNone(fg.rule_matches(rule, 'Global Buying', ''))
        updated = fg.update_rule(rule['id'], gid, 'Buying', '', 'contains')
        self.assertIsNotNone(fg.rule_matches(updated, 'Global Buying', ''))
        with self.assertRaises(HTTPException):
            fg.update_rule(rule['id'], gid, '', '', 'contains')
        with self.assertRaises(HTTPException):
            fg.update_rule('fr_000000000000', gid, 'x', '', 'contains')

    def test_delete_rule(self):
        gid = self.group()
        rule = fg.add_rule(gid, department='X')
        fg.delete_rule(rule['id'])
        self.assertEqual(fg.list_rules(), [])
        with self.assertRaises(HTTPException):
            fg.delete_rule(rule['id'])


class ManagerDetection(unittest.TestCase):
    def test_only_known_to_different_known_manager_is_a_change(self):
        import position_changes as changes
        from test_position_changes import directory, person
        before = [person('a@example.test', ManagerMail='m1@example.test', ManagerName='One'), person('b@example.test', ManagerMail='m1@example.test'),
                  person('c@example.test'), person('d@example.test', ManagerMail='m1@example.test'), person('e@example.test', ManagerMail='m1@example.test')]
        after = [person('a@example.test', ManagerMail='M2@example.test', ManagerName='Two'), person('b@example.test', ManagerMail=' M1@Example.test '),
                 person('c@example.test', ManagerMail='m2@example.test'), person('d@example.test'), person('f@example.test', ManagerMail='m2@example.test')]
        events = changes.detect_managers(directory(*before), directory(*after + [person('e@example.test', ManagerMail='m1@example.test')]), '2026-01-01T00:00:00+00:00')
        self.assertEqual([(e['key'], e['previous_manager'], e['current_manager']) for e in events], [('a@example.test', 'One', 'Two')])
        self.assertEqual(changes.detect_managers(directory(*before), directory(*before), 'x'), [])  # identical import

    def test_incomplete_replacement_and_ambiguous_identities_create_nothing(self):
        import position_changes as changes
        from test_position_changes import directory, person
        before = [person(f'u{i}@example.test', ManagerMail='m1@example.test') for i in range(6)]
        self.assertEqual(changes.detect_managers(directory(*before), directory(person('u0@example.test', ManagerMail='m2@example.test')), 'x'), [])
        duplicate = [person('d@example.test', ManagerMail='m1@example.test'), person('d@example.test', ManagerMail='m1@example.test')]
        moved = [person('d@example.test', ManagerMail='m2@example.test'), person('d@example.test', ManagerMail='m2@example.test')]
        self.assertEqual(changes.detect_managers(directory(*duplicate), directory(*moved), 'x'), [])


class Api(unittest.TestCase):
    """Router behaviour on a synthetic dataset (reuses the Account Review fixture)."""
    def setUp(self):
        import test_account_review as base
        self.write_users = lambda: base.AccountReviewTests.write_users(self)
        base.AccountReviewTests.setUp(self)
        from review_identity import profile
        profile('Rev',0)
        self.base = base

    def tearDown(self):
        self.base.AccountReviewTests.tearDown(self)

    def call(self, method, path, **kwargs):
        return self.client.request(method, '/api/functional-groups' + path, headers=self.base.H, **kwargs)

    def test_group_lifecycle_and_classification_over_http(self):
        created = self.call('POST', '', json=dict(name='Purchasing', description='Buying')).json()
        self.assertEqual(self.call('POST', '', json=dict(name=' purchasing ')).status_code, 409)
        user = '/users/DEMO_NORMAL'
        self.assertEqual(self.call('GET', user).json()['classification']['status'], 'Unassigned')
        self.assertEqual(self.call('PUT', '/users/NOPE', json=dict(group_id=created['id'], reviewer='R', expected_revision=0)).status_code, 404)
        self.assertEqual(self.call('PUT', user, json=dict(group_id=created['id'], expected_revision=999)).status_code, 409)  # stale revision remains protected
        saved = self.call('PUT', user, json=dict(group_id=created['id'], reviewer='Rev', rationale='Buys', expected_revision=0))
        self.assertEqual(saved.json()['status'], 'Confirmed')
        self.assertEqual(self.call('PUT', user, json=dict(group_id=None, reviewer='Rev', expected_revision=1)).status_code, 422)  # rationale to clear
        self.assertEqual(self.call('PUT', user, json=dict(group_id=created['id'], reviewer='Rev', expected_revision=0)).status_code, 409)
        detail = self.call('GET', user).json()
        self.assertEqual(detail['directory']['match_status'], 'matched')
        self.assertEqual(self.call('GET', '/history/demo_normal').json()['total'], 1)
        self.assertEqual(self.call('POST', f'/{created["id"]}/archive').json()['status'], 'archived')
        self.assertEqual(self.call('GET', '').json()['items'][0]['user_count'], 1)

    def organisation(self, department, title, manager):
        from test_position_changes import directory, person
        return directory(person('normal@example.test', department, title, ManagerMail=manager, ManagerName=manager.split('@')[0]))

    def test_failed_sync_preserves_classification_and_logs_only_safe_diagnostics(self):
        import position_changes as changes
        gid = self.call('POST', '', json=dict(name='Purchasing')).json()['id']
        user = '/users/DEMO_NORMAL'
        self.call('PUT', user, json=dict(group_id=gid, reviewer='Rev', rationale='Buys', expected_revision=0))
        before = fg.read()
        changes.record_safely(self.organisation('Finance', 'Accountant', 'm1@example.test'),
                              self.organisation('Procurement', 'Accountant', 'm1@example.test'))
        problem = PermissionError(13, 'private-synthetic-path-and-person')
        problem.winerror = 32
        with patch.object(fg, 'atomic_write', side_effect=problem), self.assertLogs('sap-lens', level='WARNING') as logs:
            response = self.call('GET', user)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(fg.read(), before)
        self.assertIn('category=PermissionError errno=13 winerror=32', '\n'.join(logs.output))
        self.assertNotIn('private-synthetic-path-and-person', '\n'.join(logs.output))
        # A later successful synchronization must persist the original event exactly once.
        self.assertEqual(self.call('GET', user).json()['classification']['status'], 'Needs review')
        self.assertEqual(len([e for e in fg.user_history('DEMO_NORMAL')['items'] if e['event'] == 'review_required']), 1)

    def test_organizational_changes_require_reconfirmation_without_losing_the_group(self):
        import position_changes as changes
        gid = self.call('POST', '', json=dict(name='Purchasing')).json()['id']
        user = '/users/DEMO_NORMAL'
        self.call('PUT', user, json=dict(group_id=gid, reviewer='Rev', rationale='Buys', expected_revision=0))
        base = self.organisation('Finance', 'Accountant', 'm1@example.test')
        changes.record_safely(base, self.organisation('Procurement', 'Accountant', 'm1@example.test'))
        state = self.call('GET', user).json()['classification']
        self.assertEqual((state['status'], state['group_id'], state['revision']), ('Needs review', gid, 2))
        self.assertIn('Directory Department changed from Finance to Procurement', state['review']['reason'])
        events = self.call('GET', '/history/DEMO_NORMAL').json()
        self.call('GET', user); self.client.get('/api/account-review', headers=self.base.H)  # repeated reads change nothing
        self.assertEqual(self.call('GET', '/history/DEMO_NORMAL').json()['total'], events['total'])
        done = self.call('PUT', user, json=dict(group_id=gid, reviewer='Rev', rationale='Still buying', expected_revision=2, change_id=state['review']['change_id']))
        self.assertEqual(done.json()['status'], 'Confirmed')
        changes.record_safely(base, self.organisation('Procurement', 'Accountant', 'm1@example.test'))  # same organizational state again
        self.assertEqual(self.call('GET', user).json()['classification']['status'], 'Confirmed')
        changes.record_safely(self.organisation('Procurement', 'Accountant', 'm1@example.test'), self.organisation('Procurement', 'Logistics Lead', 'm1@example.test'))
        self.assertEqual(self.call('GET', user).json()['classification']['status'], 'Needs review')  # a genuine new change

    def test_manager_change_is_a_separate_signal(self):
        import position_changes as changes
        gid = self.call('POST', '', json=dict(name='Purchasing')).json()['id']
        user = '/users/DEMO_NORMAL'
        self.call('PUT', user, json=dict(group_id=gid, reviewer='Rev', rationale='Buys', expected_revision=0))
        changes.record_safely(self.organisation('Finance', 'Accountant', 'm1@example.test'), self.organisation('Finance', 'Accountant', 'm2@example.test'))
        self.assertEqual(self.call('GET', user).json()['classification']['status'], 'Confirmed')
        history = self.call('GET', '/history/DEMO_NORMAL').json()['items']
        self.assertEqual([e['event'] for e in history], ['manager_changed', 'assigned'])
        self.assertIn('Manager changed from m1 to m2', history[0]['reason'])
        row = next(r for r in self.client.get('/api/account-review?search=DEMO_NORMAL', headers=self.base.H).json()['items'])
        self.assertTrue(row['manager_change']['open'] and row['needs_review'] and row['position_change'] is None)
        self.assertEqual(row['manager']['name'], '')

    def review(self, query=''):
        return self.client.get('/api/account-review' + query, headers=self.base.H).json()

    def test_account_review_rows_filters_and_options(self):
        gid = self.call('POST', '', json=dict(name='Finance')).json()['id']
        self.call('PUT', '/users/DEMO_NORMAL', json=dict(group_id=gid, reviewer='Rev', rationale='', expected_revision=0))
        row = next(r for r in self.review('?search=DEMO_NORMAL')['items'])
        self.assertEqual((row['functional_group']['name'], row['classification']['status'], row['classification_review']), ('Finance', 'Confirmed', False))
        self.assertEqual(self.review('?search=DEMO_OPEN')['items'][0]['classification']['status'], 'Unassigned')
        everything = self.review('?limit=100')
        self.assertEqual({r['username'] for r in self.review(f'?functional_groups={gid}')['items']}, {'DEMO_NORMAL'})
        unassigned = {r['username'] for r in self.review('?functional_groups=unassigned&limit=100')['items']}
        self.assertEqual(unassigned, {r['username'] for r in everything['items']} - {'DEMO_NORMAL'})
        both = self.review(f'?functional_groups={gid}&functional_groups=unassigned&limit=100')
        self.assertEqual(both['total'], everything['total'])  # OR within a filter
        self.assertEqual(self.review(f'?functional_groups={gid}&review_states=Approved for deactivation')['total'], 0)  # AND between filters
        self.assertEqual({o['value'] for o in everything['functional_group_options']}, {'unassigned', gid})
        self.assertTrue(everything['manager_options'])
        self.assertEqual(self.review('?managers=nobody@example.test')['total'], 0)

    def test_classification_review_is_a_finding_and_counts_as_requiring_review(self):
        import position_changes as changes
        gid = self.call('POST', '', json=dict(name='Finance')).json()['id']
        self.call('PUT', '/users/DEMO_NORMAL', json=dict(group_id=gid, reviewer='Rev', rationale='', expected_revision=0))
        changes.record_safely(self.organisation('Finance', 'Accountant', 'm1@example.test'), self.organisation('Sales', 'Accountant', 'm1@example.test'))
        queue = self.review('?findings=functional_group_review')
        self.assertEqual([r['username'] for r in queue['items']], ['DEMO_NORMAL'])
        row = queue['items'][0]
        self.assertTrue(row['classification_review'] and row['needs_review'])
        # The SAP role decision model is untouched: a role decision does not confirm the classification.
        saved = self.client.post('/api/account-review/decision/DEMO_NORMAL', headers=self.base.H, json=dict(state='No action required', reviewer='Rev', rationale='Roles fine', evidence_version=row['evidence_version']))
        self.assertEqual(saved.status_code, 200, saved.text)
        after = self.review('?findings=functional_group_review')['items'][0]
        self.assertEqual((after['classification']['status'], after['review_state']), ('Needs review', 'No action required'))

    def users(self, query):
        result = self.client.get('/api/access/users?limit=100&' + query, headers=self.base.H)
        self.assertEqual(result.status_code, 200, result.text)
        return {u['username'] for u in result.json()['items']}

    def test_user_access_filters_by_group_and_manager_server_side(self):
        gid = self.call('POST', '', json=dict(name='Finance')).json()['id']
        empty = self.call('POST', '', json=dict(name='Empty')).json()['id']
        self.call('PUT', '/users/DEMO_NORMAL', json=dict(group_id=gid, reviewer='Rev', rationale='', expected_revision=0))
        everyone = self.users('')
        listed = {u['username']: u for u in self.client.get('/api/access/users?limit=100', headers=self.base.H).json()['items']}
        self.assertEqual((listed['DEMO_NORMAL']['functional_group']['name'], listed['DEMO_NORMAL']['classification_status'], listed['DEMO_OPEN']['functional_group']), ('Finance', 'Confirmed', None))
        self.assertEqual(self.users(f'functional_groups={gid}'), {'DEMO_NORMAL'})
        self.assertEqual(self.users('functional_groups=unassigned'), everyone - {'DEMO_NORMAL'})
        self.assertEqual(self.users(f'functional_groups={gid}&functional_groups=unassigned'), everyone)
        self.assertEqual(self.users(f'functional_groups={empty}'), set())
        self.assertEqual(self.users(f'functional_groups={gid}&search=DEMO_OPEN'), set())  # AND with the existing search filter
        self.assertEqual(self.users('managers=none'), everyone)  # no imported manager links in this directory
        self.assertEqual(self.users('managers=boss@example.test'), set())
        page = self.client.get('/api/access/users?limit=1&offset=0&functional_groups=unassigned', headers=self.base.H).json()
        self.assertEqual((page['total'], len(page['items'])), (len(everyone) - 1, 1))  # totals follow the filter, not the page

    def test_options_and_sod_username_expansion(self):
        import cache
        import organization
        from routers.employees import available
        gid = self.call('POST', '', json=dict(name='Finance')).json()['id']
        empty = self.call('POST', '', json=dict(name='Empty')).json()['id']
        self.call('PUT', '/users/DEMO_NORMAL', json=dict(group_id=gid, reviewer='Rev', rationale='', expected_revision=0))
        options = self.call('GET', '/options').json()
        counts = {o['value']: o['count'] for o in options['functional_groups']}
        self.assertEqual((counts[gid], counts[empty], counts['unassigned']), (1, 0, len(self.users('')) - 1))
        state = cache.get_snapshot()
        expand = lambda names, groups: organization.expand_usernames(state, available(state), names, groups, [])
        self.assertEqual(expand([], [gid]), ['DEMO_NORMAL'])
        self.assertEqual(expand(['demo_normal', 'DEMO_OPEN'], [gid]), ['DEMO_NORMAL'])  # intersects the explicit user list, case-insensitively
        self.assertEqual(expand(['DEMO_OPEN'], [gid]), [organization.NO_USER])  # nothing selected still filters everything out
        self.assertEqual(expand(['DEMO_OPEN'], []), ['DEMO_OPEN'])  # no organizational filter: unchanged

    def test_rules_over_http(self):
        gid = self.call('POST', '', json=dict(name='Finance')).json()['id']
        rule = self.call('POST', '/rules', json=dict(group_id=gid, department='Finance')).json()
        self.assertEqual(rule['department_mode'], 'contains')
        self.assertEqual(self.call('GET', '/rules').json()['items'][0]['group_name'], 'Finance')
        self.assertEqual(self.call('POST', '/rules', json=dict(group_id=gid, department='')).status_code, 422)   # a condition is required
        updated = self.call('PUT', f'/rules/{rule["id"]}', json=dict(group_id=gid, department='Fin', title_contains='Acc', department_mode='equals'))
        self.assertEqual((updated.status_code, updated.json()['department_mode']), (200, 'equals'))
        self.assertEqual(self.call('DELETE', f'/rules/{rule["id"]}').status_code, 200)

    def directory_with_departments(self):
        import csv as csvlib
        import cache as cachelib
        import employee_directory as store
        rows = {'NORMAL': ('Global Supply Chain Operations', 'Senior Purchaser'), 'LOCKED': ('Supply Chain Planning', 'Planner'), 'OPEN': ('Finance', 'Accountant')}
        with self.directory.open('w', encoding='utf-8', newline='') as handle:
            writer = csvlib.DictWriter(handle, fieldnames=self.base.HEADERS, delimiter=';'); writer.writeheader()
            for name, (department, title) in rows.items():
                writer.writerow(dict(Name='Demo ' + name, Mail=name.lower() + '@example.test', Enabled='true', Department=department, Title=title))
            writer.writerow(dict(Name='Stranger', Mail='stranger@example.test', Enabled='true', Department='Supply Chain', Title='Buyer'))  # Directory only: no SAP user
        store.clear() if hasattr(store, 'clear') else None
        self.base.store.clear(); cachelib.load_cache()

    def test_rule_match_counts_preview_and_selection_distinguish_sap_linked_users(self):
        self.directory_with_departments()
        gid = self.call('POST', '', json=dict(name='Supply')).json()['id']
        other = self.call('POST', '', json=dict(name='Planning')).json()['id']
        rule = self.call('POST', '/rules', json=dict(group_id=gid, department='supply chain')).json()
        legacy = self.call('POST', '/rules', json=dict(group_id=gid, department='Supply Chain Planning', department_mode='equals')).json()
        listed = {r['id']: r for r in self.call('GET', '/rules?counts=true').json()['items']}
        self.assertEqual((listed[rule['id']]['match_count'], listed[rule['id']]['not_linked_count']), (2, 1))   # NORMAL + LOCKED are linked; the stranger is not
        self.assertEqual(listed[legacy['id']]['match_count'], 1)                                                  # exact: only LOCKED
        self.call('POST', '/memberships', json=dict(username='DEMO_LOCKED', group_id=other, reviewer='Rev', rationale='plans', expected_revision=0))
        self.call('POST', '/memberships', json=dict(username='DEMO_NORMAL', group_id=gid, reviewer='Rev', rationale='buys', expected_revision=0))
        page = self.call('GET', f'/rules/{rule["id"]}/matches').json()
        rows = {r['username']: r for r in page['items']}
        self.assertEqual(sorted(rows), ['DEMO_LOCKED', 'DEMO_NORMAL'])
        self.assertTrue(rows['DEMO_NORMAL']['already_member'])
        self.assertFalse(rows['DEMO_LOCKED']['already_member'])
        self.assertEqual([g['name'] for g in rows['DEMO_LOCKED']['groups']], ['Planning'])           # other memberships are shown, not replaced
        self.assertEqual((page['not_linked_total'], page['not_linked'][0]['full_name']), (1, 'Stranger'))
        self.assertEqual(self.call('GET', f'/rules/{rule["id"]}/matches?only_new=true').json()['total'], 1)
        self.assertEqual(self.call('GET', f'/rules/{rule["id"]}/matches?search=planning').json()['total'], 1)
        self.assertEqual(self.call('GET', f'/rules/{rule["id"]}/matches?limit=1&offset=1').json()['items'][0]['username'], 'DEMO_NORMAL')
        selection = self.call('GET', f'/rules/{rule["id"]}/matches/selection?only_new=true').json()
        self.assertEqual(selection['usernames'], ['DEMO_LOCKED'])
        self.assertEqual(self.call('GET', '/rules/fr_000000000000/matches').status_code, 404)

    def test_suggestions_in_user_details_consolidate_and_mark_held_groups(self):
        self.directory_with_departments()
        supply = self.call('POST', '', json=dict(name='Supply')).json()['id']
        buyers = self.call('POST', '', json=dict(name='Buyers')).json()['id']
        self.call('POST', '/rules', json=dict(group_id=supply, department='Supply'))
        self.call('POST', '/rules', json=dict(group_id=supply, title_contains='Purchaser'))
        self.call('POST', '/rules', json=dict(group_id=buyers, title_contains='purchaser'))
        self.call('POST', '/memberships', json=dict(username='DEMO_NORMAL', group_id=supply, reviewer='Rev', expected_revision=0))
        detail = self.call('GET', '/users/DEMO_NORMAL').json()
        groups = {g['group_name']: g for g in detail['suggestion']['groups']}
        self.assertEqual(sorted(groups), ['Buyers', 'Supply'])
        self.assertTrue(groups['Supply']['already_member'])
        self.assertFalse(groups['Buyers']['already_member'])
        self.assertEqual(len(groups['Supply']['rule_ids']), 2)                                          # two rules, one entry
        self.assertEqual(fg.public_user(fg.read(), 'DEMO_NORMAL')['group_ids'], [supply])               # nothing was assigned by suggesting

    def test_members_endpoint_lists_status_directory_context_and_other_groups(self):
        self.directory_with_departments()
        a = self.call('POST', '', json=dict(name='A')).json()['id']
        b = self.call('POST', '', json=dict(name='B')).json()['id']
        self.call('POST', '/memberships', json=dict(username='DEMO_NORMAL', group_id=a, reviewer='Rev', rationale='x', expected_revision=0))
        self.call('POST', '/memberships', json=dict(username='DEMO_NORMAL', group_id=b, reviewer='Rev2', rationale='y', expected_revision=1))
        self.call('POST', '/memberships', json=dict(username='DEMO_LOCKED', group_id=a, reviewer='Rev', expected_revision=0))
        fg.flag_for_review('DEMO_LOCKED', 'c1', 'Department changed')
        page = self.call('GET', f'/{a}/members').json()
        rows = {r['username']: r for r in page['items']}
        self.assertEqual((page['total'], sorted(rows)), (2, ['DEMO_LOCKED', 'DEMO_NORMAL']))
        normal = rows['DEMO_NORMAL']
        self.assertEqual((normal['department'], normal['title'], normal['identity'], normal['status'], normal['confirmed_by'], normal['other_groups']),
                         ('Global Supply Chain Operations', 'Senior Purchaser', 'matched', 'Confirmed', 'Rev', ['B']))
        self.assertTrue(normal['confirmed_at'])
        self.assertEqual(rows['DEMO_LOCKED']['status'], 'Needs review')
        self.assertEqual(self.call('GET', f'/{a}/members?status=Needs review').json()['total'], 1)
        self.assertEqual(self.call('GET', f'/{a}/members?search=senior').json()['total'], 1)
        self.assertEqual(self.call('GET', f'/{b}/members').json()['total'], 1)                           # B holds only the shared member
        self.assertEqual(self.call('GET', '/fg_000000000000/members').status_code, 404)
        empty = self.call('POST', '', json=dict(name='Empty')).json()['id']
        self.assertEqual(self.call('GET', f'/{empty}/members').json()['items'], [])

    def test_membership_endpoints_add_remove_and_are_idempotent(self):
        a = self.call('POST', '', json=dict(name='A')).json()['id']
        b = self.call('POST', '', json=dict(name='B')).json()['id']
        body = dict(username='DEMO_NORMAL', group_id=a, reviewer='Rev', rationale='x', expected_revision=0)
        self.assertEqual(self.call('POST', '/memberships', json=dict(body, expected_revision=999)).status_code, 409)
        self.assertEqual(self.call('POST', '/memberships', json=dict(body, username='NOPE')).status_code, 404)
        first = self.call('POST', '/memberships', json=body).json()
        self.assertEqual((first['outcome'], first['classification']['revision']), ('added', 1))
        again = self.call('POST', '/memberships', json=dict(body, expected_revision=1)).json()
        self.assertEqual((again['outcome'], again['classification']['revision']), ('unchanged', 1))
        self.call('POST', '/memberships', json=dict(body, group_id=b, expected_revision=1))
        self.assertEqual(self.call('POST', '/memberships/remove', json=dict(body, rationale='', expected_revision=2)).status_code, 422)
        removed = self.call('POST', '/memberships/remove', json=dict(body, expected_revision=2, rationale='left')).json()['classification']
        self.assertEqual(removed['group_ids'], [b])
        groups = {g['id']: g['user_count'] for g in self.call('GET', '').json()['items']}
        self.assertEqual((groups[a], groups[b]), (0, 1))
        self.assertEqual(self.call('GET', '/history/DEMO_NORMAL').json()['total'], 3)


if __name__ == '__main__':
    unittest.main()
