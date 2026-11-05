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
    def test_assign_change_confirm_remove_write_append_only_history(self):
        a, b = self.group('A'), self.group('B')
        self.assertEqual(fg.classify('U1', a, 'start', 0, 'rev')['revision'], 1)
        fg.classify('U1', b, 'moved', 1, 'rev2')
        fg.classify('U1', b, 'checked', 2, 'rev')
        fg.classify('U1', None, 'left the function', 3, 'rev')
        events = [e['event'] for e in reversed(fg.user_history('u1')['items'])]
        self.assertEqual(events, ['assigned', 'changed', 'confirmed', 'removed'])
        changed = fg.user_history('U1')['items'][2]
        self.assertEqual((changed['previous_group'], changed['new_group'], changed['actor'], changed['reason']), (a, b, 'rev2', 'moved'))
        self.assertEqual(fg.public_user(fg.read(), 'U1')['status'], 'Unassigned')

    def test_identity_is_case_insensitive_and_one_group_per_user(self):
        a, b = self.group('A'), self.group('B')
        fg.classify('abc', a, '', 0, 'rev')
        fg.classify('ABC', b, '', 1, 'rev')
        data = fg.read()
        self.assertEqual(len(data['users']), 1)
        self.assertEqual(fg.public_user(data, 'Abc')['group_id'], b)

    def test_stale_revision_never_overwrites(self):
        a, b = self.group('A'), self.group('B')
        fg.classify('U1', a, '', 0, 'rev')
        with self.assertRaises(HTTPException) as caught:
            fg.classify('U1', b, '', 0, 'other')
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(fg.public_user(fg.read(), 'U1')['group_id'], a)

    def test_unknown_group_and_clearing_nothing_are_refused(self):
        with self.assertRaises(HTTPException):
            fg.classify('U1', 'fg_000000000000', '', 0, 'rev')
        with self.assertRaises(HTTPException):
            fg.classify('U1', None, 'x', 0, 'rev')

    def test_review_flag_keeps_group_and_is_idempotent_per_change(self):
        gid = self.group()
        self.assertFalse(fg.flag_for_review('U1', 'c1', 'Department changed'))  # no classification: nothing to reconfirm
        fg.classify('U1', gid, '', 0, 'rev')
        self.assertTrue(fg.flag_for_review('U1', 'c1', 'Department changed'))
        self.assertFalse(fg.flag_for_review('U1', 'c1', 'Department changed'))
        state = fg.public_user(fg.read(), 'U1')
        self.assertEqual((state['status'], state['group_id'], state['review']['change_id']), ('Needs review', gid, 'c1'))
        done = fg.classify('U1', gid, 'still purchasing', state['revision'], 'rev', 'c1')
        self.assertEqual((done['status'], done['review']), ('Confirmed', None))
        self.assertFalse(fg.flag_for_review('U1', 'c1', 'Department changed'))  # same import again does not reset
        self.assertTrue(fg.flag_for_review('U1', 'c2', 'Title changed'))
        events = [e['event'] for e in reversed(fg.user_history('U1')['items'])]
        self.assertEqual(events, ['assigned', 'review_required', 'reconfirmed', 'review_required'])

    def test_manager_change_is_signal_only(self):
        gid = self.group()
        fg.classify('U1', gid, '', 0, 'rev')
        self.assertTrue(fg.note_manager_change('U1', 'm1', 'Manager changed'))
        self.assertFalse(fg.note_manager_change('U1', 'm1', 'Manager changed'))
        state = fg.public_user(fg.read(), 'U1')
        self.assertEqual((state['status'], state['revision']), ('Confirmed', 1))

    def test_explicit_unassigned_review_outcome(self):
        fg.classify('U9', None, 'no function applies', 0, 'rev', 'c7')
        self.assertEqual(fg.public_user(fg.read(), 'U9')['status'], 'Unassigned')


class Persistence(Store):
    def test_round_trip_and_validation(self):
        gid = self.group()
        fg.classify('U1', gid, 'r', 0, 'rev')
        reread = json.loads((Path(self.directory.name) / fg.FILE).read_text())
        self.assertEqual(fg.validate_storage(reread)['users'][fg.user_key('U1')]['group_id'], gid)

    def test_validation_rejects_contradictions_and_broken_references(self):
        gid = self.group()
        fg.classify('U1', gid, '', 0, 'rev')
        base = json.loads((Path(self.directory.name) / fg.FILE).read_text())
        key = fg.user_key('U1')
        def broken(change):
            data = json.loads(json.dumps(base)); change(data)
            with self.assertRaises(ValueError):
                fg.validate_storage(data)
        broken(lambda d: d['users'][key].update(group_id='fg_ffffffffffff'))
        broken(lambda d: d['users'][key].update(status='Unassigned'))
        broken(lambda d: d['users'][key].update(status='Needs review'))
        broken(lambda d: d['users'][key].update(revision=0))
        broken(lambda d: d['history'][0].update(new_group='fg_ffffffffffff'))
        broken(lambda d: d.update(format=2))
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

    def test_backup_validation_hook(self):
        import application_backups as backups
        import maintenance as engine
        gid = self.group()
        fg.classify('U1', gid, '', 0, 'rev')
        root = Path(self.directory.name)
        backups.validate_store(root)  # valid store passes
        data = json.loads((root / fg.FILE).read_text())
        data['users'][fg.user_key('U1')]['group_id'] = 'fg_ffffffffffff'
        (root / fg.FILE).write_text(json.dumps(data))
        with self.assertRaises(engine.MaintenanceError):
            backups.validate_store(root)


class Suggestions(Store):
    def test_rules_match_explain_and_report_ambiguity(self):
        buy, plan = self.group('Purchasing'), self.group('Planning')
        fg.add_rule(buy, department='Supply Chain', title_contains='Purchaser')
        fg.add_rule(plan, title_contains='planner')
        result = fg.suggest('supply  chain', 'Senior PURCHASER')
        self.assertEqual((result['status'], result['matches'][0]['group_name']), ('suggested', 'Purchasing'))
        self.assertEqual(result['matches'][0]['reasons'], ['Directory Department = Supply Chain', 'Job Title contains Purchaser'])
        self.assertEqual(fg.suggest('Supply Chain', 'Buyer')['status'], 'none')  # department alone does not satisfy a combined rule
        both = fg.suggest('Supply Chain', 'Purchaser and Planner')
        self.assertEqual((both['status'], len(both['matches'])), ('ambiguous', 2))

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
        self.assertEqual(self.call('PUT', user, json=dict(group_id=created['id'], expected_revision=0)).status_code, 422)  # reviewer required
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

    def test_rules_over_http(self):
        gid = self.call('POST', '', json=dict(name='Finance')).json()['id']
        rule = self.call('POST', '/rules', json=dict(group_id=gid, department='Finance')).json()
        self.assertEqual(self.call('GET', '/rules').json()['items'][0]['group_name'], 'Finance')
        self.assertEqual(self.call('DELETE', f'/rules/{rule["id"]}').status_code, 200)


if __name__ == '__main__':
    unittest.main()
