"""Position changes: Department/Title differences between validated directory snapshots drive priority Account Review."""
import hashlib
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import account_review as review
import position_changes as changes
from employee_directory import HEADERS, Directory
import test_account_review
H = test_account_review.H


def directory(*people, name='dir.csv'):
    rows = []
    for i, person in enumerate(people):
        row = {header: '' for header in HEADERS}
        row.update(person, id=str(i))
        rows.append(row)
    return Directory(rows, name, hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest())


def person(mail, department='Finance', title='Accountant', **extra):
    return dict(Name='Demo ' + mail.split('@')[0], Mail=mail, Department=department, Title=title, SamAccountName=mail.split('@')[0], Enabled='true', **extra)


NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc).isoformat()


class DetectionRules(unittest.TestCase):
    def detect(self, before, after):
        return changes.detect(directory(*before), directory(*after), NOW)

    def test_department_and_title_changes_keep_previous_current_values_and_generations(self):
        before = [person('a@example.test'), person('b@example.test'), person('c@example.test')]
        after = [person('a@example.test', department='Procurement'), person('b@example.test', title='Senior Accountant'), person('c@example.test', 'Sales', 'Rep')]
        events, notices = self.detect(before, after)
        self.assertEqual(notices, [])
        by_key = {event['key']: event for event in events}
        self.assertEqual(by_key['a@example.test']['fields'], ['department'])
        self.assertEqual((by_key['a@example.test']['previous_department'], by_key['a@example.test']['current_department']), ('Finance', 'Procurement'))
        self.assertEqual(by_key['b@example.test']['fields'], ['title'])
        self.assertEqual((by_key['b@example.test']['previous_title'], by_key['b@example.test']['current_title']), ('Accountant', 'Senior Accountant'))
        self.assertEqual(by_key['c@example.test']['fields'], ['department', 'title'])
        self.assertEqual(len({event['source_generation'] for event in events}), 1)
        self.assertNotEqual(events[0]['source_generation'], events[0]['previous_generation'])
        self.assertEqual(events[0]['detected_at'], NOW)

    def test_manager_formatting_missing_values_and_new_employees_never_create_a_change(self):
        before = [person('a@example.test', ManagerName='Old Boss'), person('b@example.test'), person('c@example.test'), person('d@example.test', department='')]
        after = [person('a@example.test', ManagerName='New Boss'), person('b@example.test', department='  finance ', title='ACCOUNTANT'),
                 person('c@example.test', department='', title=''), person('d@example.test', department='Sales'), person('new@example.test', 'Sales', 'Rep')]
        self.assertEqual(self.detect(before, after)[0], [])

    def test_ambiguous_identities_are_skipped(self):
        before = [person('a@example.test'), person('a@example.test', 'Other')]
        after = [person('a@example.test', 'Procurement'), person('a@example.test', 'Other')]
        self.assertEqual(self.detect(before, after)[0], [])

    def test_incomplete_imports_do_not_produce_changes(self):
        before = [person(f'u{i}@example.test') for i in range(10)]
        events, notices = self.detect(before, [person('u0@example.test', 'Sales')])
        self.assertEqual(events, [])
        self.assertIn('far fewer records', notices[0])
        after = [person(f'u{i}@example.test', department='', title='Lead') for i in range(10)]
        events, notices = self.detect(before, after)
        self.assertEqual({event['fields'][0] for event in events}, {'title'})
        self.assertIn('mostly empty department', notices[0])

    def test_identical_snapshots_and_missing_baseline_are_silent(self):
        same = [person('a@example.test')]
        self.assertEqual(self.detect(same, same), ([], []))
        self.assertEqual(changes.detect(None, directory(*same), NOW), ([], []))


class ReviewIntegration(unittest.TestCase):
    setUp, tearDown, write_users = (test_account_review.AccountReviewTests.setUp, test_account_review.AccountReviewTests.tearDown, test_account_review.AccountReviewTests.write_users)

    def record(self, **fields):
        before = directory(person('open@example.test'), person('normal@example.test'), name='before.csv')
        after = directory(person('open@example.test', **fields), person('normal@example.test'), name='after.csv')
        return changes.record(before, after)

    def row(self, query='', username='DEMO_OPEN'):
        data = self.client.get('/api/account-review' + query, headers=H).json()
        return data, next(item for item in data['items'] if item['username'] == username)

    def test_open_change_gets_priority_and_reuses_the_account_review_decision(self):
        self.assertEqual(self.record(department='Procurement'), 1)
        self.assertEqual(self.record(department='Procurement'), 0)  # re-detecting the same replacement adds nothing
        data, row = self.row('?finding=position_change&sort=priority')
        self.assertEqual([item['username'] for item in data['items']], ['DEMO_OPEN'])
        self.assertEqual(data['summary']['position_changes'], 1)
        self.assertEqual((row['priority'], row['review_state'], row['position_change']['open']), ('High', 'Needs review', True))
        self.assertEqual((row['position_change']['previous_department'], row['position_change']['current_department']), ('Finance', 'Procurement'))
        everyone = self.client.get('/api/account-review?sort=priority', headers=H).json()['items']
        self.assertEqual(everyone[0]['username'], 'DEMO_OPEN')
        dashboard = {m['id']: m for m in self.client.get('/api/dashboard', headers=H).json()['metrics']}
        self.assertEqual((dashboard['position_changes']['value'], dashboard['position_changes']['destination']), (1, 'review'))
        saved = self.client.post('/api/account-review/decision/DEMO_OPEN', headers=H, json=dict(state='No action required', reviewer='Reviewer', rationale='Role change confirmed with the manager.', evidence_version=row['evidence_version']))
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.client.get('/api/account-review?finding=position_change', headers=H).json()['items'], [])  # reviewed, so no longer an open position change
        _, row = self.row()
        self.assertFalse(row['position_change']['open'])
        self.assertEqual((row['review_state'], row['priority']), ('No action required', 'Normal' if row['needs_review'] else 'None'))
        self.assertEqual(self.client.get('/api/account-review/history/DEMO_OPEN', headers=H).json()['total'], 0)  # no duplicate decision was created
        dashboard = {m['id']: m for m in self.client.get('/api/dashboard', headers=H).json()['metrics']}
        self.assertEqual(dashboard['position_changes']['value'], 0)

    def test_a_later_change_reopens_the_review_and_old_changes_expire(self):
        self.record(department='Procurement')
        _, row = self.row()
        self.client.post('/api/account-review/decision/DEMO_OPEN', headers=H, json=dict(state='No action required', reviewer='R', rationale='ok', evidence_version=row['evidence_version']))
        before = directory(person('open@example.test', 'Procurement'), name='second-before.csv')
        changes.record(before, directory(person('open@example.test', 'Procurement', 'Lead'), name='second-after.csv'))
        _, row = self.row()
        self.assertTrue(row['position_change']['open'])
        self.assertEqual(row['position_change']['fields'], ['title'])
        events = changes.read()['events']
        old = datetime.now(timezone.utc) - timedelta(days=changes.RECENT_DAYS + 5)
        self.assertEqual(changes.latest_recent(events, old.date())['open@example.test']['fields'], ['title'])
        self.assertEqual(changes.latest_recent(events, (datetime.now(timezone.utc) + timedelta(days=200)).date()), {})

    def test_unmatched_or_ambiguous_identities_are_not_attributed_to_a_sap_user(self):
        before = directory(person('stranger@example.test'), name='b.csv')
        changes.record(before, directory(person('stranger@example.test', 'Sales'), name='a.csv'))
        data = self.client.get('/api/account-review?finding=position_change', headers=H).json()
        self.assertEqual(data['items'], [])

    def test_unreadable_store_never_blocks_review(self):
        (Path(review.config_dir()) / 'position-changes.json').write_text('{broken')
        self.assertEqual(self.client.get('/api/account-review', headers=H).status_code, 200)
        self.assertEqual(changes.read(), dict(events=[], notice='Position change records could not be read.'))
        self.assertEqual(changes.record_safely(directory(person('a@example.test')), directory(person('a@example.test', 'X'))), 1)


if __name__ == '__main__':
    unittest.main()
