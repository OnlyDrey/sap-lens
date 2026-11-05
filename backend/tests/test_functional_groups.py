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


if __name__ == '__main__':
    unittest.main()
