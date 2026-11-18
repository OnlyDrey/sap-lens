"""Performance work keeps results identical: record comparison, snapshot encoding, memoized dates and totals, bounded matcher lifetime."""
import gc
import hashlib
import json
import os
import random
import sys
import tempfile
import unittest
import weakref
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cache
import config
import csv_lifecycle as lifecycle
import employee_directory as ed
import user_access
from analysis_errors import AnalysisValidationError


def reference_diff(source, before, after, include_changes=True):
    """The comparison as it was before the memory optimisation (JSON text per row, grouping of every row)."""
    groups = [defaultdict(list), defaultdict(list)]
    missing = 0
    for target, rows in zip(groups, (before, after)):
        for row in rows:
            clean = {k: v for k, v in row.items() if k != 'id'} if 'id' in row else row
            key = lifecycle.record_key(source, clean)
            if key is None:
                missing += 1
                key = ('missing',)
            target[key].append(clean)
    counts = dict(added=0, removed=0, modified=0, unchanged=0)
    changes, ambiguous = [], 0
    for key in sorted(set(groups[0]) | set(groups[1])):
        originals, buckets = {}, []
        for group in groups:
            bucket = Counter()
            for row in group.get(key, []):
                fingerprint = json.dumps(row, sort_keys=True, ensure_ascii=False)
                bucket[fingerprint] += 1
                originals[fingerprint] = row
            buckets.append(bucket)
        common = buckets[0] & buckets[1]
        counts['unchanged'] += sum(common.values())
        old, new = list((buckets[0] - common).elements()), list((buckets[1] - common).elements())
        if len(old) == len(new) == 1 and key != ('missing',):
            left, right = originals[old[0]], originals[new[0]]
            counts['modified'] += 1
            changes.append(('modified', tuple(sorted(f for f in set(left) | set(right) if left.get(f) != right.get(f))), json.dumps(left, sort_keys=True), json.dumps(right, sort_keys=True)))
        else:
            if old and new:
                ambiguous += 1
            for kind, values in (('removed', old), ('added', new)):
                counts[kind] += len(values)
                changes.extend((kind, (), json.dumps(originals[v], sort_keys=True), '') if kind == 'removed' else (kind, (), '', json.dumps(originals[v], sort_keys=True)) for v in values)
    return counts, ambiguous, missing, sorted(changes)


def normalized(result):
    changes = []
    for item in result['changes']:
        if item['type'] == 'modified':
            changes.append(('modified', tuple(sorted(f['field'] for f in item['fields'])), json.dumps(item['before'], sort_keys=True), json.dumps(item['after'], sort_keys=True)))
        elif item['type'] == 'removed':
            changes.append(('removed', (), json.dumps(item['before'], sort_keys=True), ''))
        else:
            changes.append(('added', (), '', json.dumps(item['after'], sort_keys=True)))
    counts = {k: result[k] for k in ('added', 'removed', 'modified', 'unchanged')}
    return counts, result['ambiguous_identifiers'], result['missing_identifiers'], sorted(changes)


def user_row(user, role, group='FIN', email=None, valid_to='99991231'):
    return {'USERNAME': user, 'ROLE_NAME': role, 'USER_GROUP': group, 'FIRST_NAME': '', 'LAST_NAME': '', 'EMAIL': email or f'{user.lower()}@example.test',
            'USER_VALID_FROM': '20200101', 'USER_VALID_TO': '99991231', 'ROLE_VALID_FROM': '20200101', 'ROLE_VALID_TO': valid_to, 'USER_LOCKED': '', 'USER_TYPE': 'A'}


class Comparison(unittest.TestCase):
    def test_the_optimised_comparison_equals_the_reference_on_randomised_sources(self):
        rng = random.Random(11)
        for round_number in range(60):
            base = [user_row(f'U{rng.randrange(40):03d}', f'Z:R{rng.randrange(6)}', rng.choice(['FIN', 'MM', 'fin'])) for _ in range(rng.randrange(0, 120))]
            after = list(base)
            for _ in range(rng.randrange(0, 15)):
                action = rng.choice(['drop', 'change', 'add', 'duplicate', 'blank'])
                if action == 'drop' and after:
                    after.pop(rng.randrange(len(after)))
                elif action == 'change' and after:
                    row = dict(after.pop(rng.randrange(len(after)))); row[rng.choice(['EMAIL', 'ROLE_VALID_TO', 'USER_TYPE'])] = f'x{rng.randrange(5)}'; after.append(row)
                elif action == 'add':
                    after.append(user_row(f'U{rng.randrange(60):03d}', f'Z:R{rng.randrange(8)}'))
                elif action == 'duplicate' and after:
                    after.append(dict(rng.choice(after)))
                else:
                    after.append(user_row('', 'Z:R1'))
            rng.shuffle(after)
            with self.subTest(round=round_number):
                self.assertEqual(normalized(lifecycle.diff_records('users', base, after)), reference_diff('users', base, after))

    def test_directory_rows_with_bookkeeping_ids_compare_without_the_id(self):
        def employee(n, **extra):
            return {'id': str(n), 'SamAccountName': f'emp{n}', 'DistinguishedName': f'CN=emp{n}', 'Mail': f'e{n}@example.test', 'Department': 'D', **extra}
        before = [employee(n) for n in range(30)]
        after = [dict(employee(n), id=str(29 - n)) for n in range(30)]           # same records, different bookkeeping ids and order
        after[5] = employee(5, Department='Audit'); after.pop(9)
        self.assertEqual(normalized(lifecycle.diff_records('employees', before, after)), reference_diff('employees', before, after))

    def test_a_no_change_comparison_groups_nothing(self):
        rows = [user_row(f'U{n:03d}', 'Z:R1') for n in range(500)]
        with patch.object(lifecycle, 'defaultdict', wraps=defaultdict) as groups:
            result = lifecycle.diff_records('users', rows, [dict(row) for row in reversed(rows)])
        self.assertEqual((result['unchanged'], result['added'], result['removed'], result['modified']), (500, 0, 0, 0))
        self.assertEqual(result['changes'], [])
        self.assertTrue(groups.called)                                           # the (empty) groups exist, but no row was grouped


class Encoding(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        patcher = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': self.temp.name}); patcher.start(); self.addCleanup(patcher.stop)
        config.get_settings.cache_clear(); self.addCleanup(config.get_settings.cache_clear)

    def test_streamed_snapshots_are_byte_identical_to_the_former_encoding_and_keep_their_identity(self):
        rng = random.Random(5)
        rows = [{'B': 'é' * rng.randrange(3) + str(i), 'A': 'x y"\\', 'C': '日本'} for i in range(4500)]
        for value in (dict(version=1, source='users', records=rows, report={'z': 1, 'a': [1, 2]}), dict(version=1, source='sod', records=rows[:5], report={}), dict(zlist=list(range(4001)), a=1)):
            expected = json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode('utf-8')
            identity = lifecycle.write_private('snapshots', value)
            self.assertEqual(identity, hashlib.sha256(expected).hexdigest())
            self.assertEqual(lifecycle.private_path('snapshots', identity).read_bytes(), expected)
            self.assertEqual(lifecycle.write_private('snapshots', value), identity)      # idempotent
        self.assertEqual([p.name for p in lifecycle.private_path('snapshots', '0' * 64).parent.glob('*.tmp')], [])

    def test_a_failed_write_leaves_no_partial_file_and_the_limit_is_enforced(self):
        with patch.object(lifecycle, 'MAX_PRIVATE_BYTES', 100):
            with self.assertRaises(ValueError):
                lifecycle.write_private('snapshots', dict(version=1, records=[{'a': 'x' * 50}] * 10))
        folder = lifecycle.private_path('snapshots', '0' * 64).parent
        self.assertEqual(list(folder.glob('*')), [])

    def test_an_existing_corrupt_target_is_repaired(self):
        value = dict(version=1, records=[{'a': '1'}])
        identity = lifecycle.write_private('snapshots', value)
        lifecycle.private_path('snapshots', identity).write_bytes(b'corrupt')
        self.assertEqual(lifecycle.write_private('snapshots', value), identity)
        self.assertEqual(lifecycle.read_private('snapshots', identity)['records'], [{'a': '1'}])


class Memoisation(unittest.TestCase):
    def test_sap_date_results_are_memoised_but_errors_are_not_swallowed_or_cached(self):
        self.assertEqual(user_access.sap_date('20240229'), date(2024, 2, 29))
        self.assertEqual(user_access.sap_date('2024-02-29'), date(2024, 2, 29))
        self.assertIsNone(user_access.sap_date('00000000'))
        for _ in range(2):
            with self.assertRaises(AnalysisValidationError):
                user_access.sap_date('20241301')
        before = user_access.sap_date.cache_info().hits
        user_access.sap_date('20240229')
        self.assertEqual(user_access.sap_date.cache_info().hits, before + 1)

    def state(self):
        today = date.today()
        def fmt(day):
            return day.strftime('%Y%m%d')
        records = []
        users = {}
        for number in range(30):
            end = today + timedelta(days=(-5 if number % 3 == 0 else 10 if number % 3 == 1 else 400))
            start = today + timedelta(days=(30 if number % 7 == 0 else -100))
            for role in range(3):
                item = dict(valid_from=fmt(start), valid_to=fmt(end if role else today - timedelta(days=1)), role_name=f'R{role}', user_key=f'U{number}')
                records.append(item)
                users.setdefault(f'U{number}', dict(assignments=[])).setdefault('assignments', []).append(item)
        return user_access.UserState(users=users, assignments=records), today

    def test_dataset_status_counts_equal_direct_counting_and_follow_the_day(self):
        state, today = self.state()
        direct = Counter(user_access.interval_status(user_access.sap_date(a['valid_from']), user_access.sap_date(a['valid_to']), today) for a in state.assignments)
        self.assertEqual(dict(user_access.assignment_status_counts(state, today)), dict(direct))
        self.assertIs(user_access.assignment_status_counts(state, today), user_access.assignment_status_counts(state, today))
        later = today + timedelta(days=20)
        recomputed = Counter(user_access.interval_status(user_access.sap_date(a['valid_from']), user_access.sap_date(a['valid_to']), later) for a in state.assignments)
        self.assertEqual(dict(user_access.assignment_status_counts(state, later)), dict(recomputed))
        other, _ = self.state()
        self.assertIsNot(user_access.assignment_status_counts(other, today), user_access.assignment_status_counts(state, later))

    def test_export_totals_equal_the_list_lengths_for_every_filter_combination(self):
        from routers import access
        state, today = self.state()
        snapshot = type('Snapshot', (), {'users': state})()
        for filters in ({'show_expired': False, 'status': ''}, {'show_expired': True, 'status': ''}, {'show_expired': False, 'status': 'expired'}, {'show_expired': False, 'status': 'active'}):
            for key in state.users:
                with self.subTest(filters=filters, key=key):
                    self.assertEqual(access.audit_assignment_count(snapshot, key, filters, today), len(access.audit_assignments(snapshot, key, filters, today)))


class MatcherLifetime(unittest.TestCase):
    def test_repeated_refreshes_do_not_retain_replaced_datasets_or_matchers(self):
        def rows(n):
            return [{'id': str(i), 'Site': '', 'Name': f'N{i}', 'SamAccountName': f's{i}', 'UserPrincipalName': '', 'Mail': f'u{i}@example.test', 'Department': f'D{n}', 'Title': '', 'Enabled': 'True',
                     'DistinguishedName': f'CN=s{i}', 'ManagerDN': '', 'ManagerName': '', 'ManagerSamAccountName': '', 'ManagerMail': '', 'ManagerDepartment': '', 'ManagerTitle': '',
                     'ManagerLookupStatus': ''} for i in range(20)]
        def users():
            return user_access.UserState(users={f'U{i}': dict(username=f'U{i}', emails=[f'u{i}@example.test'], names=set(), groups=set(), accounts=[], assignments=[]) for i in range(20)})
        sap = users()
        old_directories, old_matchers = [], []
        for generation in range(6):
            directory = ed.Directory(rows(generation), 'f.csv', 'a' * 64)
            matcher = ed.identity_matcher(sap, directory)
            matcher(sap.users['U1'])
            old_directories.append(weakref.ref(directory)); old_matchers.append(weakref.ref(matcher))
            del directory, matcher
        gc.collect()
        self.assertEqual(sum(ref() is not None for ref in old_directories), 1)            # only the current pair is held, by the SAP dataset
        self.assertEqual(sum(ref() is not None for ref in old_matchers), 1)
        self.assertEqual(len(sap.__dict__['_identity_matchers']), 1)
        reference = weakref.ref(sap)
        del sap
        gc.collect()
        self.assertIsNone(reference())                                                    # a replaced SAP dataset takes its matcher and directory with it
        gc.collect()
        self.assertEqual(sum(ref() is not None for ref in old_directories), 0)

    def test_the_matcher_is_not_part_of_a_derived_cache_entry(self):
        import pickle
        state = user_access.UserState(users={'U1': dict(username='U1', emails=['a@example.test'], names=set(), groups=set(), accounts=[], assignments=[])})
        ed.identity_matcher(state, ed.Directory([], 'f.csv', 'a' * 64))
        self.assertIn('_identity_matchers', state.__dict__)
        self.assertNotIn(b'_identity_matchers', pickle.dumps(state))
        self.assertNotIn('_identity_matchers', pickle.loads(pickle.dumps(state)).__dict__)
        import copy
        self.assertNotIn('_identity_matchers', copy.copy(state).__dict__)
        self.assertTrue(cache)


if __name__ == '__main__':
    unittest.main()
