import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis_errors import AnalysisValidationError
from sod_import import HEADERS, SodImportProfile, build_sod, parse_sod


def records():
    base = dict(RISK='SYNTHETIC-R1', CRITICITY='H', TYPE='S', TEXT='Synthetic incompatible activities',
                ACTVT1='CREATE', ACTVT2='APPROVE', TTEXT='Synthetic transaction')
    return [dict(base, ACTIVITY_SLOT='ACTVT1', ACTIVITY='CREATE', TCODE='X001'),
            dict(base, ACTIVITY_SLOT='ACTVT2', ACTIVITY='APPROVE', TCODE='X002')]


class SodImportTests(unittest.TestCase):
    def write(self, rows, headers=HEADERS, encoding='utf-8', delimiter=','):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'synthetic.csv'
        with path.open('w', encoding=encoding, newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=headers, delimiter=delimiter)
            writer.writeheader()
            writer.writerows([{field: row[field] for field in headers} for row in rows])
        return path

    def test_parse_verified_slots_and_report(self):
        parsed = parse_sod(self.write(records()))
        self.assertEqual(parsed['version'], 1)
        self.assertEqual(parsed['source'], 'sod')
        self.assertEqual(parsed['report']['unique_records'], 2)
        risk = parsed['risks'][0]
        self.assertTrue(risk['supported'])
        self.assertEqual(risk['evaluation_policy'], 'sod-two-sided-v1')
        self.assertEqual(risk['activities']['ACTVT1'][0]['tcode'], 'X001')

    def test_duplicate_and_reordered_content_hash(self):
        original = parse_sod(self.write(records()))
        reordered = parse_sod(self.write(list(reversed(records())) + [records()[0]]))
        self.assertEqual(original['content_hash'], reordered['content_hash'])
        self.assertEqual(original['records'], reordered['records'])
        self.assertEqual(reordered['report']['duplicate_rows'], 1)

    def test_unknown_type_preserved_but_not_evaluable(self):
        rows = records()
        for row in rows:
            row['TYPE'] = 'FUTURE-TYPE'
        parsed = build_sod(rows)
        self.assertFalse(parsed['risks'][0]['supported'])
        self.assertIsNone(parsed['risks'][0]['evaluation_policy'])
        self.assertTrue(any('unsupported TYPE' in warning for warning in parsed['warnings']))

    def test_missing_description_warns_header_remains_required(self):
        rows = records()
        rows[0]['TTEXT'] = ''
        self.assertTrue(any('TTEXT' in warning for warning in parse_sod(self.write(rows))['warnings']))
        with self.assertRaises(AnalysisValidationError):
            parse_sod(self.write(rows, headers=HEADERS[:-1]))

    def test_invalid_records_rejected(self):
        mutations = [lambda row: row.update(ACTIVITY_SLOT='1'),
                     lambda row: row.update(ACTIVITY='WRONG'),
                     lambda row: row.update(TCODE=''),
                     lambda row: row.update(TCODE='X' * 513),
                     lambda row: row.update(TEXT='\x00invalid'),
                     lambda row: row.update(ACTVT2='CREATE')]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                rows = records()
                mutate(rows[0])
                with self.assertRaises(AnalysisValidationError):
                    build_sod(rows)
        with self.assertRaises(AnalysisValidationError):
            build_sod([])
        with self.assertRaises(AnalysisValidationError):
            build_sod(records()[:1])

    def test_conflicting_definitions_and_transaction_text_rejected(self):
        rows = records()
        rows[1]['CRITICITY'] = 'C'
        with self.assertRaises(AnalysisValidationError):
            build_sod(rows)
        rows = records()
        duplicate = dict(rows[0], TTEXT='Different description')
        with self.assertRaises(AnalysisValidationError):
            build_sod(rows + [duplicate])

    def test_encoding_delimiter_and_explicit_mapping(self):
        for encoding in ('utf-8-sig', 'utf-16', 'cp1252'):
            with self.subTest(encoding=encoding):
                rows = records()
                rows[0]['TTEXT'] = 'Blåbær'
                self.assertEqual(len(parse_sod(self.write(rows, encoding=encoding, delimiter=';'))['records']), 2)
        profile = SodImportProfile(id='custom', name='Custom', mapping={'RISK': 'RISK'})
        self.assertEqual(len(parse_sod(self.write(records()), profile)['risks']), 1)

    def test_limits_and_malformed_csv(self):
        with patch('sod_import.MAX_ROWS', 1):
            with self.assertRaises(AnalysisValidationError):
                build_sod(records())
        path = self.write(records())
        with patch('csv_import.MAX_BYTES', 1):
            with self.assertRaises(AnalysisValidationError):
                parse_sod(path)
        with path.open('a', encoding='utf-8') as stream:
            stream.write('too,few,columns\n')
        with self.assertRaises(AnalysisValidationError):
            parse_sod(path)

    def test_shared_transaction_on_both_sides_is_not_silently_removed(self):
        rows = records()
        rows[1]['TCODE'] = rows[0]['TCODE']
        parsed = build_sod(rows)
        self.assertEqual(len(parsed['records']), 2)
        self.assertTrue(any('definition overlap needs review' in warning for warning in parsed['warnings']))
        self.assertEqual(parsed['report']['warnings'], parsed['warnings'])
        self.assertEqual(parsed['report']['parsed_rows'], 2)
        self.assertEqual(parsed['report']['unique_records'], 2)
        self.assertEqual(parsed['report']['duplicate_rows'], 0)
        supplied = {'parsed_rows': 3, 'unique_records': 2, 'duplicate_rows': 1, 'warnings': ['Existing warning']}
        rebuilt = build_sod(rows, supplied)
        self.assertEqual(rebuilt['report']['parsed_rows'], 3)
        self.assertEqual(rebuilt['report']['duplicate_rows'], 1)
        self.assertIn('Existing warning', rebuilt['report']['warnings'])
        self.assertEqual(supplied['warnings'], ['Existing warning'])


if __name__ == '__main__':
    unittest.main()
