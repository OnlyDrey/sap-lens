"""SoD Matrix source inspection: read-only counts, column interpretation, validation checks, warnings and import metadata."""
import csv
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
import cache
import config
from csv_lifecycle import load
from employee_directory import store
from main import create_app
from sod_import import HEADERS, inspection, parse_sod

H = {'X-SAP-Lens': 'synthetic-inspection-session'}


def rows(risk='SYN01', second='SYN_B', risk_type='S', ttext='Synthetic transaction', extra=()):
    result = [dict(RISK=risk, CRITICITY='H', TYPE=risk_type, TEXT='Synthetic two-sided review', ACTVT1='SYN_A', ACTVT2=second, ACTIVITY_SLOT=slot, ACTIVITY=activity, TCODE=code, TTEXT=ttext)
              for slot, activity, code in (('ACTVT1', 'SYN_A', 'SYN01'), ('ACTVT2', second, 'SYN02'))]
    return result + list(extra)


def write(path, data, fields=HEADERS):
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(data)


class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(self.root / 'config'), 'DATA_CSV_PATH': ''})
        self.env.start(); config.get_settings.cache_clear(); cache.clear_cache(); store.clear()
        self.path = self.root / 'matrix.csv'
        write(self.path, rows())
        self.client = TestClient(create_app(session_token=H['X-SAP-Lens']), base_url='http://127.0.0.1:18743')

    def tearDown(self):
        cache.clear_cache(); store.clear(); config.get_settings.cache_clear(); self.env.stop(); self.temp.cleanup()

    def activate(self):
        settings = config.get_settings().model_copy(deep=True)
        settings.sod_csv_path = str(self.path); settings.source_modes.sod = 'static'; settings.features.sod = True
        return load(settings, operation='import', strict=True, force=('sod',))

    def get(self, path):
        response = self.client.get(path, headers=H)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def post(self, path, body, status=200):
        response = self.client.post(path, json=body, headers=H)
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def test_inspection_counts_interprets_columns_and_flags_quality_issues(self):
        data = rows(extra=rows(risk='SYN02', risk_type='X', ttext='') + rows()[:1])  # an unsupported risk, a missing TTEXT and a duplicate row
        write(self.path, data)
        result = inspection(parse_sod(self.path))
        self.assertEqual([item['column'] for item in result['columns']], list(HEADERS))
        self.assertTrue(all(item['detected'] and item['meaning'] for item in result['columns']))
        self.assertFalse(next(item for item in result['columns'] if item['column'] == 'TTEXT')['required'])
        counts = result['counts']
        self.assertEqual((counts['parsed_rows'], counts['records'], counts['duplicate_rows'], counts['risks'], counts['evaluated_risks'], counts['unsupported_risks']), (5, 4, 1, 2, 1, 1))
        self.assertEqual((counts['activities'], counts['transactions']), (2, 2))
        self.assertEqual((result['criticality'], result['types']), ({'H': 2}, {'S': 1, 'X': 1}))
        status = {item['name']: item['status'] for item in result['checks']}
        self.assertEqual((status['Documented columns'], status['Evaluated risk types'], status['Duplicate rows'], status['Transaction descriptions']), ('passed', 'warning', 'warning', 'warning'))
        self.assertTrue(any('unsupported TYPE' in warning for warning in result['warnings']))

    def test_active_snapshot_inspection_reports_metadata_and_is_read_only(self):
        self.assertEqual(self.get('/api/data-sources/sod/inspection')['loaded'], False)
        self.activate()
        before = (cache.get_snapshot().sod['content_hash'], config.get_settings().revision, dict(config.get_settings().data_lifecycle.sources))
        result = self.get('/api/data-sources/sod/inspection')
        self.assertTrue(result['loaded'])
        self.assertEqual((result['counts']['records'], result['counts']['risks']), (2, 1))
        meta = result['metadata']
        self.assertEqual((meta['mode'], meta['path'], meta['feature_enabled']), ('static', str(self.path), True))
        self.assertTrue(meta['imported_at'] and meta['checked_at'] and meta['snapshot'])
        self.assertEqual(before, (cache.get_snapshot().sod['content_hash'], config.get_settings().revision, dict(config.get_settings().data_lifecycle.sources)))

    def test_the_route_requires_the_application_session(self):
        self.assertEqual(self.client.get('/api/data-sources/sod/inspection').status_code, 403)


if __name__ == '__main__':
    unittest.main()
