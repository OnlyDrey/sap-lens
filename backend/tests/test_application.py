"""Regression coverage for local settings, security boundaries and cache generations."""
import csv
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cache
import config
from fastapi.testclient import TestClient
from main import app

HEADERS = {'X-SAP-Lens': '1'}
COLUMNS = ['FUNCTION_KEY', 'AGR_NAME', 'TEXT', 'CHILD_AGR', 'CHILD_AGR_TEXT', 'TCODE', 'TTEXT']


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {
            'SAP_LENS_CONFIG_DIR': str(self.root / 'config'), 'DATA_CSV_PATH': '',
        })
        self.environment.start()
        config.get_settings.cache_clear()
        cache._cache = cache._CacheState()
        self.client_context = TestClient(app, base_url='http://127.0.0.1:18743')
        self.client = self.client_context.__enter__()
        self.csv = self.root / 'roles.csv'
        self.write_csv('OLD')

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.environment.stop()
        config.get_settings.cache_clear()
        self.temp.cleanup()

    def write_csv(self, tcode):
        with self.csv.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(COLUMNS)
            writer.writerow(['FI', 'A', 'Finance, demo', 'SHARED', 'Shared\nrole', tcode, 'Display'])
            writer.writerow(['MM', 'B', 'Materials', 'SHARED', 'Shared', tcode, 'Display'])
            writer.writerow(['FI', 'A', 'Finance', 'UNIQUE', 'Unique', 'UNIQUE', 'Unique'])

    def save(self, path=None):
        return self.client.post('/api/settings', json={'data_csv_path': str(path or self.csv)}, headers=HEADERS)

    def test_first_run_and_persistence(self):
        self.assertEqual(self.client.get('/health').json()['status'], 'needs_configuration')
        self.assertEqual(self.client.get('/api/roles').json(), [])
        self.assertEqual(self.save().status_code, 200)
        config.get_settings.cache_clear()
        self.assertEqual(config.get_settings().data_csv_path, str(self.csv))
        self.assertEqual(self.client.get('/health').json()['cached_roles'], 2)
        detail = self.client.get('/api/roles/A').json()
        self.assertEqual(detail['text'], 'Finance, demo')
        self.assertEqual(len(detail['single_roles']), 2)
        self.assertEqual(len(self.client.get('/api/roles?function_key=FI').json()), 1)
        result = self.client.post('/api/compare', json={'roles': ['A', 'B']}, headers=HEADERS)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['shared_tcodes'][0]['tcode'], 'OLD')

    def test_refresh_replaces_tcode_index(self):
        self.save()
        self.assertEqual(len(self.client.get('/api/roles?tcode=OLD').json()), 2)
        self.write_csv('NEW')
        self.assertEqual(self.client.post('/api/refresh', headers=HEADERS).status_code, 200)
        self.assertEqual(self.client.get('/api/roles?tcode=OLD').json(), [])
        self.assertEqual(len(self.client.get('/api/roles?tcode=NEW').json()), 2)

    def test_bad_file_preserves_data_and_settings(self):
        self.save()
        original = (self.root / 'config/settings.json').read_bytes()
        bad = self.root / 'bad.csv'
        bad.write_text('WRONG,COLUMNS\na,b\n')
        self.assertEqual(self.save(bad).status_code, 400)
        self.assertEqual(self.save(self.root / 'missing.csv').status_code, 400)
        self.assertEqual((self.root / 'config/settings.json').read_bytes(), original)
        self.assertEqual(len(self.client.get('/api/roles').json()), 2)
        self.assertEqual(len(self.client.get('/api/roles?tcode=OLD').json()), 2)

    def test_persistence_failure_preserves_cache(self):
        self.save()
        self.write_csv('NEW')
        with patch('data_loader.save_data_path', side_effect=OSError('Disk full')):
            self.assertEqual(self.save().status_code, 400)
        self.assertEqual(len(self.client.get('/api/roles?tcode=OLD').json()), 2)
        self.assertEqual(self.client.get('/api/roles?tcode=NEW').json(), [])

    def test_browser_security_boundary(self):
        self.assertEqual(self.client.post('/api/refresh').status_code, 403)
        for origin in ['https://attacker.example', 'null', 'http://localhost:3000']:
            headers = {**HEADERS, 'Origin': origin}
            self.assertEqual(self.client.post('/api/refresh', headers=headers).status_code, 403)
            self.assertEqual(self.client.get('/api/settings', headers=headers).status_code, 403)
        self.assertEqual(self.client.get('/api/roles', headers={'Host': 'attacker.example'}).status_code, 400)
        allowed = self.client.options('/api/settings', headers={
            'Origin': 'http://127.0.0.1:18743', 'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'X-SAP-Lens,Content-Type'})
        self.assertEqual(allowed.status_code, 200)
        for url in ['https://example.com/roles.csv', 'file:///etc/passwd']:
            self.assertEqual(self.client.post('/api/settings', json={'data_csv_path': url}, headers=HEADERS).status_code, 400)

    def test_unreadable_and_malformed_csv_have_safe_errors(self):
        self.save()
        with patch('cache.load_cache', side_effect=PermissionError('/private/path')):
            result = self.save()
        self.assertEqual(result.status_code, 400)
        self.assertIn('permissions', result.json()['detail'])
        self.assertNotIn('/private/path', result.text)
        self.csv.write_text('FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT\n"unfinished')
        self.assertEqual(self.save().status_code, 400)
        self.assertEqual(len(self.client.get('/api/roles').json()), 2)
        self.assertEqual(self.client.post('/api/settings', json={'data_csv_path': 'relative.csv'}, headers=HEADERS).status_code, 400)

    def test_comparison_limits_and_duplicates(self):
        self.save()
        for names in [[], ['A'], ['A'] * 6]:
            self.assertEqual(self.client.post('/api/compare', json={'roles': names}, headers=HEADERS).status_code, 422)
        self.assertEqual(self.client.post('/api/compare', json={'roles': ['A', 'A']}, headers=HEADERS).status_code, 400)

    def test_large_chunked_requests_are_rejected(self):
        response = self.client.post('/api/settings', content=iter([b'x' * 10000, b'y' * 10000]),
                                    headers={**HEADERS, 'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 413)

    def test_snapshot_stays_consistent_after_reload(self):
        self.save()
        previous = cache.get_snapshot()
        self.write_csv('NEW')
        self.client.post('/api/refresh', headers=HEADERS)
        self.assertIn('OLD', previous.tcode_index)
        self.assertNotIn('NEW', previous.tcode_index)
        self.assertIn('NEW', cache.get_snapshot().tcode_index)

    def test_corrupt_settings_do_not_block_first_run(self):
        folder = self.root / 'config'
        folder.mkdir()
        (folder / 'settings.json').write_text('{invalid')
        config.get_settings.cache_clear()
        self.assertEqual(config.get_settings().data_csv_path, '')
        self.assertEqual(self.save().status_code, 200)
        self.assertEqual(json.loads((folder / 'settings.json').read_text())['data_csv_path'], str(self.csv))


if __name__ == '__main__':
    unittest.main()
