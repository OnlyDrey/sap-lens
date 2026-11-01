"""The validation tracker CSV stays consistent, nothing is approved automatically, the earlier records survive the migration and the workbook round trip never loses a decision."""
import copy
import csv
import importlib.util
import io
import re
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('validation_tracker', ROOT / 'scripts' / 'validation_tracker.py')
tracker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tracker)

REQUIRED = ['ID', 'Area', 'Page/component', 'Validation criterion', 'Priority', 'Status', 'Manual approval', 'Automated test evidence', 'Last validated date', 'Build/commit',
            'Notes', 'Linked issue or finding', 'Potential future improvement']


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.rows = tracker.read()

    def test_repository_tracker_is_consistent_and_covers_the_22_functional_areas(self):
        self.assertEqual(tracker.problems(self.rows), [])
        self.assertEqual(len(tracker.AREAS), 22)
        self.assertEqual({row['Area'] for row in self.rows}, set(tracker.AREAS))  # every area has items
        self.assertEqual(tracker.COLUMNS[:len(REQUIRED)], REQUIRED)
        self.assertEqual(tracker.STATUSES, ['Not tested', 'Passed', 'Failed', 'Needs improvement', 'Blocked', 'Not applicable'])

    def test_the_tracker_is_versioned_while_other_csv_files_stay_ignored(self):
        self.assertEqual(subprocess.run(['git', 'check-ignore', '-q', 'docs/validation/validation-items.csv'], cwd=ROOT).returncode, 1)
        self.assertEqual(subprocess.run(['git', 'check-ignore', '-q', 'docs/validation/other.csv'], cwd=ROOT).returncode, 0)
        self.assertEqual(subprocess.run(['git', 'check-ignore', '-q', 'role-export.csv'], cwd=ROOT).returncode, 0)

    def test_ids_are_stable_unique_and_every_reference_exists(self):
        ids = [row['ID'] for row in self.rows]
        self.assertEqual(len(ids), len(set(ids)))
        for required in ('R7-01', 'R7-05', 'R8-01', 'R8-02'):
            self.assertIn(required, ids)
        for row in self.rows:
            for path in re.split(r';\s*|,\s*', row['Implementation reference']):
                if path and '/' in path:
                    self.assertTrue((ROOT / path).exists(), (row['ID'], path))

    def test_nothing_is_approved_or_dated_by_the_tooling(self):
        for row in self.rows:
            if row['Manual approval'] == 'Approved':
                self.assertEqual(row['Status'], 'Passed', row['ID'])
                self.assertTrue(row['Last validated date'] and row['Notes'].strip(), row['ID'])
            if row['Status'] == 'Not tested':
                self.assertEqual((row['Manual approval'], row['Last validated date'], row['Retest status']), ('Pending', '', 'Not started'), row['ID'])
        self.assertEqual(sum(row['Manual approval'] == 'Approved' for row in self.rows), 0)  # approval is a person's decision
        new = {row['ID']: row for row in self.rows if row['ID'].startswith(('R7-', 'R8-'))}
        self.assertTrue(all(row['Manual approval'] == 'Pending' and row['Last validated date'] == '' for row in new.values()))

    def test_implemented_items_name_existing_automated_evidence_and_stay_unapproved(self):
        implemented = [row for row in self.rows if row['Implementation status'] == 'Implemented']
        self.assertGreaterEqual(len(implemented), 20)
        for row in implemented:
            files = re.findall(r'[\w./-]+\.(?:spec\.ts|py)', row['Automated test evidence'])
            self.assertTrue(files, row['ID'])
            for name in files:
                self.assertTrue((ROOT / name).exists(), (row['ID'], name))
            self.assertNotEqual(row['Manual approval'], 'Approved', row['ID'])  # implementation is not acceptance

    def test_earlier_records_survive_the_migration_field_by_field(self):
        legacy = tracker.migrate_legacy([dict(zip(tracker.LEGACY_COLUMNS, [
            'UI-099', 'Global UI and shared components', 'Components', 'Buttons', 'Expected', 'Needs improvement', 'Low', 'Improvement opportunity', 'Seen', 'doc.md', 'Implemented', 'a.spec.ts', 'Look', 'Limit', 'Not started']))])[0]
        self.assertEqual((legacy['Status'], legacy['Priority'], legacy['Classification'], legacy['Notes'], legacy['Automated test evidence'], legacy['Manual validation steps'], legacy['Known limitations']),
                         ('Needs improvement', 'Low', 'Improvement opportunity', 'Seen', 'a.spec.ts', 'Look', 'Limit'))
        self.assertEqual(legacy['Page/component'], 'Components › Buttons')
        for old, new in {'Not reviewed': ('Not tested', 'Pending'), 'Approved': ('Passed', 'Approved'), 'Bug': ('Failed', 'Pending'), 'Blocked': ('Blocked', 'Pending'), 'Not applicable': ('Not applicable', 'Not applicable')}.items():
            row = tracker.migrate_legacy([dict(zip(tracker.LEGACY_COLUMNS, ['UI-099', 'Dashboard', 'p', 'c', 'e', old, 'Not set', 'Unclassified', 'n', 'r', 'Not assessed', '', '', '', 'Not started']))])[0]
            self.assertEqual((row['Status'], row['Manual approval']), new)
        self.assertTrue(all(tracker.map_area(dict(zip(tracker.LEGACY_COLUMNS, ['X-01', area, 'p', 'c', 'e', 'Not reviewed', 'Not set', 'Unclassified', '', '', 'Not assessed', '', '', '', 'Not started']))) in tracker.AREAS
                            for area in ['Global UI and shared components', 'Dashboard', 'User Access', 'SoD Risk Matrix and Activity Matrix', 'Settings', 'Data Management', 'Deployment and Security', 'SoD Remediation']))

    def test_consistency_rules_reject_contradictory_rows(self):
        def one(**change):
            rows = copy.deepcopy(self.rows)
            rows[0].update(change)
            return tracker.problems(rows)
        self.assertTrue(one(Status='Failed'))                                # a failed item needs notes and a defect classification
        self.assertEqual(one(Status='Failed', Classification='Current defect', Notes='x'), [])
        self.assertTrue(one(**{'Manual approval': 'Approved'}))              # approval needs a passed status, a date and notes
        self.assertTrue(one(Status='Passed', Notes='x'))                     # a passed item records its date
        self.assertEqual(one(Status='Passed', Notes='x', **{'Last validated date': '2026-01-02'}), [])
        self.assertEqual(one(Status='Passed', Notes='x', **{'Last validated date': '2026-01-02', 'Manual approval': 'Approved'}), [])
        self.assertTrue(one(Status='Passed', Notes='x', **{'Last validated date': '02.01.2026'}))
        self.assertTrue(one(Status='Sort of fine'))
        self.assertTrue(one(Classification='Current defect'))               # a not tested item cannot be a defect
        self.assertTrue(one(Area='Somewhere else'))
        duplicate = copy.deepcopy(self.rows)
        duplicate[1]['ID'] = duplicate[0]['ID']
        self.assertTrue(any('duplicate' in message for message in tracker.problems(duplicate)))

    def test_workbook_is_reproducible_structured_and_round_trips_every_row(self):
        first, second = tracker.workbook(self.rows), tracker.workbook(self.rows)
        self.assertEqual(first, second)
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            self.assertIsNone(archive.testzip())
            names = set(archive.namelist())
            self.assertTrue({'xl/worksheets/sheet4.xml', 'xl/tables/table1.xml', 'xl/styles.xml'} <= names)
            workbook = archive.read('xl/workbook.xml').decode()
            self.assertEqual(re.findall(r'<sheet name="([^"]+)"', workbook), ['Summary', 'Items', 'Defects and Findings', 'Future Improvements'])
            items = archive.read('xl/worksheets/sheet2.xml').decode()
            self.assertIn('state="frozen"', items)  # frozen header
            for column in ('Status', 'Priority', 'Manual approval'):
                self.assertIn(f'<c r="{tracker._column(tracker.COLUMNS.index(column))}1"', items)
            self.assertEqual(items.count('<dataValidation '), 6)  # drop-downs
            self.assertIn('conditionalFormatting', items)
            self.assertIn('COUNTIFS', archive.read('xl/worksheets/sheet1.xml').decode())  # live summary formulas
        self.assertEqual(tracker.read_items_sheet(first), self.rows)

    def test_the_committed_workbook_matches_the_csv(self):
        committed = ROOT / 'docs' / 'validation' / 'validation-tracker.xlsx'
        self.assertTrue(committed.exists(), 'run: python scripts/validation_tracker.py export --output docs/validation/validation-tracker.xlsx')
        fresh = zipfile.ZipFile(io.BytesIO(tracker.workbook(self.rows)))
        with zipfile.ZipFile(committed) as archive:
            self.assertEqual(sorted(archive.namelist()), sorted(fresh.namelist()))
            for name in fresh.namelist():  # compare contents, not compressed bytes, so another zlib build cannot fail the check
                self.assertEqual(archive.read(name), fresh.read(name), f'{name} is stale: regenerate the workbook after editing the CSV')

    def test_summary_sheet_lists_every_area_and_the_backlog_sheets_follow_the_rows(self):
        data = tracker.workbook(self.rows)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            summary = archive.read('xl/worksheets/sheet1.xml').decode()
            defects = archive.read('xl/worksheets/sheet3.xml').decode()
            ideas = archive.read('xl/worksheets/sheet4.xml').decode()
        for area in tracker.AREAS:
            self.assertIn(f'>{area}<', summary)
        expected = [row['ID'] for row in self.rows if row['Status'] in {'Failed', 'Needs improvement', 'Blocked'} or row['Classification'] == 'Current defect' or (row['Linked issue or finding'].strip() and row['Status'] != 'Passed')]
        self.assertEqual(len(re.findall(r'<row ', defects)) - 1, len(expected))
        wanted = [row for row in self.rows if row['Potential future improvement'].strip() or row['Classification'] == 'Improvement opportunity']
        self.assertEqual(len(re.findall(r'<row ', ideas)) - 1, len(wanted))
        self.assertGreaterEqual(len(wanted), 4)

    def test_merge_copies_decisions_without_touching_definitions_and_rejects_bad_values(self):
        rows = copy.deepcopy(self.rows)
        edited = tracker.read_items_sheet(tracker.workbook(rows))
        edited[0].update({'Status': 'Needs improvement', 'Classification': 'Improvement opportunity', 'Priority': 'High', 'Notes': 'Seen in dark 375', 'Validation criterion': 'changed in Excel'})
        edited[1]['Status'] = 'Mostly fine'
        edited.append(dict(edited[0], ID='ZZ-999'))
        changed, rejected = tracker.merge(rows, edited)
        self.assertEqual(changed, [rows[0]['ID']])
        self.assertEqual((rows[0]['Status'], rows[0]['Priority'], rows[0]['Notes']), ('Needs improvement', 'High', 'Seen in dark 375'))
        self.assertEqual(rows[0]['Validation criterion'], self.rows[0]['Validation criterion'])  # definitions belong to the CSV
        self.assertEqual(rows[1]['Status'], self.rows[1]['Status'])
        self.assertEqual(len(rejected), 2)
        self.assertEqual(tracker.problems(rows), [])
        self.assertEqual(len(rows), len(self.rows))  # merging never removes or adds rows

    def test_command_line_migrates_checks_exports_and_merges_back(self):
        with tempfile.TemporaryDirectory() as directory:
            earlier, current, book = Path(directory) / 'earlier.csv', Path(directory) / 'items.csv', Path(directory) / 'out.xlsx'
            with open(earlier, 'w', newline='', encoding='utf-8') as handle:
                writer = csv.writer(handle, lineterminator='\n')
                writer.writerow(tracker.LEGACY_COLUMNS)
                writer.writerow(['UI-099', 'Dashboard', 'Dashboard', 'KPI', 'Shows KPIs', 'Not reviewed', 'Not set', 'Unclassified', '', 'docs/features/DASHBOARD.md', 'Not assessed', '', '', '', 'Not started'])
            self.assertTrue(tracker.is_legacy(earlier))
            self.assertEqual(tracker.main(['--csv', str(earlier), 'migrate']), 0)
            self.assertFalse(tracker.is_legacy(earlier))
            self.assertEqual(tracker.main(['--csv', str(earlier), 'migrate']), 0)  # idempotent
            self.assertEqual(tracker.read(earlier)[0]['Status'], 'Not tested')
            tracker.write(self.rows, current)
            self.assertEqual(tracker.main(['--csv', str(current), 'check']), 0)
            self.assertEqual(tracker.main(['--csv', str(current), 'export', '--output', str(book)]), 0)
            edited = tracker.read_items_sheet(book.read_bytes())
            edited[2].update({'Status': 'Failed', 'Classification': 'Current defect', 'Notes': 'Broken'})
            book.write_bytes(tracker.workbook([{**row} for row in edited]))
            self.assertEqual(tracker.main(['--csv', str(current), 'merge', str(book)]), 0)
            merged = tracker.read(current)
            self.assertEqual(merged[2]['Status'], 'Failed')
            self.assertEqual([row for i, row in enumerate(merged) if i != 2], [row for i, row in enumerate(self.rows) if i != 2])


if __name__ == '__main__':
    unittest.main()
