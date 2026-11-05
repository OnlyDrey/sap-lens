"""Employee Directory: fingerprinted unchanged fast path, authenticated derived copy, shared SAP/AD identity matching, change detection."""
import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cache
import config
import csv_lifecycle
import employee_directory as ed
import persistent_cache
import source_store

HEADER = 'USERNAME,ROLE_NAME,EMAIL,USER_GROUP,USER_VALID_FROM,USER_VALID_TO,ROLE_VALID_FROM,ROLE_VALID_TO'.split(',')
ROLES = 'FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT\nFI,Z:FI,Finance,Z:FI:READ,Read,FB03,Display\n'


def employee(number, **changes):
    row = {'Site': 'HQ', 'Name': f'Employee {number}', 'SamAccountName': f'emp{number}', 'UserPrincipalName': f'emp{number}@example.test', 'Mail': f'u{number}@example.test',
           'Department': f'D{number % 3}', 'Title': 'Analyst', 'Enabled': 'True', 'DistinguishedName': f'CN=emp{number},OU=Staff,DC=example,DC=test',
           'ManagerDN': 'CN=emp0,OU=Staff,DC=example,DC=test' if number else '', 'ManagerName': 'Employee 0' if number else '', 'ManagerSamAccountName': 'emp0' if number else '',
           'ManagerMail': 'u0@example.test' if number else '', 'ManagerDepartment': 'D0' if number else '', 'ManagerTitle': 'Analyst' if number else '', 'ManagerLookupStatus': ''}
    row.update(changes)
    return row


class Case(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(self.root / 'private'), 'DATA_CSV_PATH': ''}); patcher.start(); self.addCleanup(patcher.stop)
        config.get_settings.cache_clear(); cache.clear_cache(); self.addCleanup(config.get_settings.cache_clear); self.addCleanup(cache.clear_cache)
        ed.store.directory = None; ed.store.path = ''; ed.store.attempted_path = None
        (self.root / 'roles.csv').write_text(ROLES)
        with (self.root / 'users.csv').open('w', newline='') as stream:
            writer = csv.writer(stream); writer.writerow(HEADER)
            writer.writerows([f'U{u:03d}', 'Z:FI:READ', f'u{u}@example.test', 'FIN', '20200101', '99991231', '20200101', '99991231'] for u in range(12))
        self.directory = self.root / 'directory.csv'
        self.write([employee(n) for n in range(12)])
        settings = config.get_settings().model_copy(deep=True)
        settings.data_csv_path, settings.user_csv_path, settings.employee_csv_path = str(self.root / 'roles.csv'), str(self.root / 'users.csv'), str(self.directory)
        settings.features.employee_directory = True
        settings.source_modes.employees = 'dynamic'
        config.save_configuration(settings, settings.revision)
        csv_lifecycle.load(config.get_settings(), operation='refresh', strict=True)
        cache.clear_cache(); ed.store.directory = None; ed.store.attempted_path = None
        csv_lifecycle.load(config.get_settings(), operation='startup', strict=True)

    def write(self, rows):
        with self.directory.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=ed.HEADERS, delimiter=';'); writer.writeheader(); writer.writerows(rows)

    def refresh(self):
        return csv_lifecycle.load(config.get_settings(), operation='refresh', strict=True)

    def status(self, report):
        row = next(item for item in report['sources'] if item['source'] == 'employees')
        return row['status'], row.get('fast_path', False)


class FastPath(Case):
    def test_an_unchanged_directory_is_neither_parsed_compared_nor_matched_again(self):
        before = ed.store.directory
        with patch.object(ed, 'parse_directory', wraps=ed.parse_directory) as parse, patch.object(csv_lifecycle, 'diff_records', wraps=csv_lifecycle.diff_records) as diff:
            report = self.refresh()
        self.assertEqual(self.status(report), ('unchanged', True))
        self.assertEqual(parse.call_count, 0)
        self.assertEqual([call for call in diff.call_args_list if call.args[1] or call.args[2]], [])      # only the empty zero-delta helper
        self.assertIs(ed.store.directory, before)

    def test_a_changed_directory_takes_the_full_path_records_the_change_and_a_new_fingerprint(self):
        rows = [employee(n) for n in range(12)]; rows[3] = employee(3, Department='Finance')
        self.write(rows)
        report = self.refresh()
        self.assertEqual(self.status(report), ('updated', False))
        item = next(row for row in report['sources'] if row['source'] == 'employees')
        self.assertEqual((item['modified'], item['added'], item['removed']), (1, 0, 0))
        self.assertEqual(self.status(self.refresh()), ('unchanged', True))                              # the new content is now the fingerprinted baseline

    def test_each_relevant_field_change_is_detected(self):
        for field, value in (('SamAccountName', 'renamed'), ('UserPrincipalName', 'other@example.test'), ('Enabled', 'False'), ('Department', 'Audit'), ('Title', 'Director'),
                             ('ManagerDN', 'CN=emp5,OU=Staff,DC=example,DC=test'), ('ManagerSamAccountName', 'emp5'), ('ManagerMail', 'u5@example.test')):
            with self.subTest(field=field):
                rows = [employee(n) for n in range(12)]; rows[4] = employee(4, **{field: value})
                self.write(rows)
                item = next(row for row in self.refresh()['sources'] if row['source'] == 'employees')
                self.assertEqual((item['status'], item['modified']), ('updated', 1))
                self.write([employee(n) for n in range(12)])
                self.refresh()

    def test_unknown_fingerprints_and_parser_changes_take_the_full_path_once(self):
        snapshot = config.get_settings().employee_snapshot_id
        source_store.set_directory_fingerprint(snapshot, 'f' * 64)                                       # as left by an earlier release or a different parser
        self.assertEqual(self.status(self.refresh()), ('unchanged', False))
        self.assertEqual(self.status(self.refresh()), ('unchanged', True))
        with patch.object(persistent_cache, 'code_digest', return_value='1' * 64):                       # parser code changed
            self.assertEqual(self.status(self.refresh()), ('unchanged', False))

    def test_a_missing_store_is_not_an_error(self):
        import shutil, store_db
        shutil.rmtree(store_db.directory())
        self.assertEqual(self.status(self.refresh()), ('unchanged', False))
        self.assertEqual(self.status(self.refresh()), ('unchanged', True))

    def test_position_changes_are_recorded_for_real_changes_and_not_for_unchanged_checks(self):
        with patch('position_changes.record_safely') as record:
            self.refresh()
            record.assert_not_called()
            rows = [employee(n) for n in range(12)]; rows[2] = employee(2, Title='Manager')
            self.write(rows); self.refresh()
            record.assert_called_once()

    def test_removed_and_reappearing_accounts_are_handled(self):
        rows = [employee(n) for n in range(12) if n != 6]
        self.write(rows)
        item = next(row for row in self.refresh()['sources'] if row['source'] == 'employees')
        self.assertEqual((item['status'], item['removed']), ('updated', 1))
        matcher = ed.identity_matcher(cache.get_snapshot().users, ed.store.directory)
        self.assertEqual(matcher(cache.get_snapshot().users.users['U006'])['status'], 'unmatched')       # no stale mapping to the removed account
        self.write([employee(n) for n in range(12)])
        item = next(row for row in self.refresh()['sources'] if row['source'] == 'employees')
        self.assertEqual((item['status'], item['added']), ('updated', 1))
        matcher = ed.identity_matcher(cache.get_snapshot().users, ed.store.directory)
        self.assertEqual(matcher(cache.get_snapshot().users.users['U006'])['status'], 'matched')

    def test_startup_with_a_damaged_snapshot_still_reports_it_even_with_a_derived_copy(self):
        snapshot = config.get_settings().employee_snapshot_id
        self.assertEqual(self.status(self.refresh()), ('unchanged', True))
        self.assertTrue(persistent_cache.get('directory', persistent_cache.dependency_key(snapshot=snapshot, code=persistent_cache.code_digest('employee_directory.py'))) is not None)
        ed.snapshot_path(snapshot).write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            ed.read_snapshot(snapshot)                                                                    # the file is verified before any derived copy is used


class DerivedCopy(Case):
    def key(self):
        return persistent_cache.dependency_key(snapshot=config.get_settings().employee_snapshot_id, code=persistent_cache.code_digest('employee_directory.py'))

    def test_a_derived_copy_skips_parsing_but_equals_a_fresh_build(self):
        snapshot = config.get_settings().employee_snapshot_id
        ed.read_snapshot(snapshot)
        with patch.object(ed, 'validate_snapshot', wraps=ed.validate_snapshot) as validate:
            again = ed.read_snapshot(snapshot)
        self.assertEqual(validate.call_count, 0)
        persistent_cache.clear()
        fresh = ed.read_snapshot(snapshot)
        self.assertEqual((again.rows, again.digest, again.imported_at), (fresh.rows, fresh.digest, fresh.imported_at))
        self.assertEqual({key: {k: [r['id'] for r in v] for k, v in index.items()} for key, index in again.indexes.items()},
                         {key: {k: [r['id'] for r in v] for k, v in index.items()} for key, index in fresh.indexes.items()})

    def test_a_tampered_derived_copy_is_rejected_and_rebuilt(self):
        import store_db
        snapshot = config.get_settings().employee_snapshot_id
        ed.read_snapshot(snapshot)
        connection = store_db.connect(); connection.execute("UPDATE derived SET payload=? WHERE kind='directory'", (b'not signed',)); connection.close()
        with self.assertLogs('sap-lens', 'WARNING'):
            directory = ed.read_snapshot(snapshot)
        self.assertEqual(len(directory.rows), 12)


class Matcher(Case):
    def test_matches_equal_direct_matching_and_are_computed_once_per_dataset_pair(self):
        users, directory = cache.get_snapshot().users, ed.store.directory
        matcher = ed.identity_matcher(users, directory)
        owners = ed.sap_email_owners(users.users.values())
        for user in users.users.values():
            self.assertEqual(matcher(user), ed.match_sap_identity(directory, user, owners))
        self.assertIs(ed.identity_matcher(users, directory), matcher)
        with patch.object(ed, 'match_sap_identity', side_effect=AssertionError('recomputed')):
            for user in users.users.values():
                matcher(user)

    def test_a_replaced_directory_or_sap_dataset_never_serves_the_old_mapping(self):
        users, directory = cache.get_snapshot().users, ed.store.directory
        old = ed.identity_matcher(users, directory)
        rows = [employee(n) for n in range(12)]; rows[1] = employee(1, Mail='someone.else@example.test')
        self.write(rows); self.refresh()
        new_directory = ed.store.directory
        self.assertIsNot(new_directory, directory)
        fresh = ed.identity_matcher(cache.get_snapshot().users, new_directory)
        self.assertIsNot(fresh, old)
        self.assertEqual(fresh(cache.get_snapshot().users.users['U001'])['status'], 'unmatched')
        self.assertEqual(old(users.users['U001'])['status'], 'matched')                                  # the old pair is untouched, never reused for the new one

    def test_shared_sap_addresses_stay_ambiguous(self):
        users = cache.get_snapshot().users
        users.users['U002']['emails'] = list(users.users['U001']['emails'])
        users.__dict__.pop('_identity_matchers', None)
        matcher = ed.identity_matcher(users, ed.store.directory)
        self.assertEqual(matcher(users.users['U001'])['status'], 'ambiguous_sap_email')


if __name__ == '__main__':
    unittest.main()
