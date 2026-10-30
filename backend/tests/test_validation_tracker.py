"""The validation tracker CSV stays consistent and its workbook round trip never loses a reviewer decision."""
import copy
import importlib.util
import io
import re
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('validation_tracker', ROOT / 'scripts' / 'validation_tracker.py')
tracker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tracker)


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.rows = tracker.read()

    def test_repository_tracker_is_consistent_and_covers_every_area(self):
        self.assertEqual(tracker.problems(self.rows), [])
        self.assertEqual({row['Area'] for row in self.rows}, set(tracker.AREAS))
        self.assertEqual(len(tracker.AREAS), 18)

    def test_ids_are_stable_and_every_reference_exists(self):
        ids = [row['ID'] for row in self.rows]
        self.assertEqual(len(ids), len(set(ids)))
        for row in self.rows:
            for path in re.split(r';\s*|,\s*', row['Implementation reference']):
                if path and '/' in path:
                    self.assertTrue((ROOT / path).exists(), (row['ID'], path))

    def test_nothing_is_approved_without_evidence_and_unreviewed_items_stay_explicit(self):
        for row in self.rows:
            if row['Status'] == 'Approved':
                self.assertTrue(row['Notes and evidence'].strip(), row['ID'])
            if row['Status'] == 'Not reviewed':
                self.assertEqual((row['Retest status'], row['Classification']), ('Not started', 'Unclassified'), row['ID'])
        self.assertEqual(sum(row['Status'] == 'Approved' for row in self.rows), 0)  # approval is a person's decision

    def test_consistency_rules_reject_contradictory_rows(self):
        def one(**change):
            rows = copy.deepcopy(self.rows)
            rows[0].update(change)
            return tracker.problems(rows)
        self.assertTrue(one(Status='Bug'))                                   # a Bug needs notes and a defect classification
        self.assertEqual(one(Status='Bug', Classification='Current defect', **{'Notes and evidence': 'x'}), [])
        self.assertTrue(one(Status='Approved'))                              # approval needs evidence
        self.assertTrue(one(Status='Approved', **{'Notes and evidence': 'x', 'Retest status': 'Retest failed'}))
        self.assertTrue(one(Status='Sort of fine'))
        self.assertTrue(one(Classification='Current defect'))               # not reviewed cannot be a defect
        duplicate = copy.deepcopy(self.rows)
        duplicate[1]['ID'] = duplicate[0]['ID']
        self.assertTrue(any('duplicate' in message for message in tracker.problems(duplicate)))

    def test_workbook_is_reproducible_and_round_trips_every_row(self):
        first, second = tracker.workbook(self.rows), tracker.workbook(self.rows)
        self.assertEqual(first, second)
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertIn('xl/worksheets/sheet4.xml', archive.namelist())
        self.assertEqual(tracker.read_items_sheet(first), self.rows)

    def test_merge_copies_decisions_without_touching_definitions_and_rejects_bad_values(self):
        rows = copy.deepcopy(self.rows)
        edited = tracker.read_items_sheet(tracker.workbook(rows))
        edited[0].update({'Status': 'Needs improvement', 'Classification': 'Improvement opportunity', 'Priority': 'High', 'Notes and evidence': 'Seen in dark 375', 'Expected behavior': 'changed in Excel'})
        edited[1]['Status'] = 'Mostly fine'
        edited.append(dict(edited[0], ID='ZZ-999'))
        changed, rejected = tracker.merge(rows, edited)
        self.assertEqual(changed, [rows[0]['ID']])
        self.assertEqual((rows[0]['Status'], rows[0]['Priority'], rows[0]['Notes and evidence']), ('Needs improvement', 'High', 'Seen in dark 375'))
        self.assertEqual(rows[0]['Expected behavior'], self.rows[0]['Expected behavior'])  # definitions belong to the CSV
        self.assertEqual(rows[1]['Status'], 'Not reviewed')
        self.assertEqual(len(rejected), 2)
        self.assertEqual(tracker.problems(rows), [])
        self.assertEqual(len(rows), len(self.rows))  # merging never removes or adds rows

    def test_command_line_writes_the_workbook_and_merges_back(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_copy, workbook = Path(directory) / 'items.csv', Path(directory) / 'out.xlsx'
            tracker.write(self.rows, csv_copy)
            self.assertEqual(tracker.main(['--csv', str(csv_copy), 'check']), 0)
            self.assertEqual(tracker.main(['--csv', str(csv_copy), 'export', '--output', str(workbook)]), 0)
            edited = tracker.read_items_sheet(workbook.read_bytes())
            edited[2].update({'Status': 'Bug', 'Classification': 'Current defect', 'Notes and evidence': 'Broken'})
            workbook.write_bytes(tracker.workbook([{**row} for row in edited]))
            self.assertEqual(tracker.main(['--csv', str(csv_copy), 'merge', str(workbook)]), 0)
            merged = tracker.read(csv_copy)
            self.assertEqual(merged[2]['Status'], 'Bug')
            self.assertEqual([row for i, row in enumerate(merged) if i != 2], [row for i, row in enumerate(self.rows) if i != 2])


if __name__ == '__main__':
    unittest.main()
