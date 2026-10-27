"""Synthetic SoD source/local separation, safe persistence and catalogue API."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cache
import config
from config_models import SourceSnapshot
from csv_lifecycle import write_private
from sod_import import build_sod
import sod_catalogue as catalogue
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from routers.sod import router


def rows(risk='SYN01', description='Synthetic two-sided risk'):
    base = dict(RISK=risk, CRITICITY='H', TYPE='S', TEXT=description,
                ACTVT1='SYN_A', ACTVT2='SYN_B', TTEXT='Synthetic transaction')
    return [dict(base, ACTIVITY_SLOT='ACTVT1', ACTIVITY='SYN_A', TCODE='X001'),
            dict(base, ACTIVITY_SLOT='ACTVT2', ACTIVITY='SYN_B', TCODE='X002')]


class SodCatalogueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(self.root / 'config'), 'DATA_CSV_PATH': ''})
        self.env.start()
        config.get_settings.cache_clear(); cache.clear_cache()
        catalogue._historical_definitions.cache_clear()
        app = FastAPI(); app.include_router(router)
        self.client = TestClient(app)

    def tearDown(self):
        config.get_settings.cache_clear(); cache.clear_cache()
        catalogue._historical_definitions.cache_clear()
        self.env.stop(); self.temp.cleanup()

    def publish(self, records):
        source = build_sod(records)
        identity = write_private('snapshots', dict(version=1, source='sod', records=source['records'], report=source['report']))
        settings = config.get_settings().model_copy(deep=True)
        reference = SourceSnapshot(snapshot=identity, path='/synthetic/matrix.csv', imported_at='2026-01-01T12:00:00+00:00', checked_at='2026-01-01T12:00:00+00:00')
        settings.sod_csv_path = reference.path
        settings.data_lifecycle.sources['sod'] = reference
        settings.data_lifecycle.sod_history.append(reference)
        config.save_configuration(settings, settings.revision)
        cache._cache = cache._CacheState(sod=source)
        return source

    def save(self, item, **changes):
        return catalogue.save(item['risk_id'], {**item['local'], **changes}, catalogue.read().revision, item['definition_version'])

    def test_new_risks_are_enabled_without_invented_local_descriptions(self):
        self.publish(rows())
        result = catalogue.catalogue(); item = result['items'][0]
        self.assertTrue(item['new']); self.assertTrue(item['local']['enabled'])
        self.assertEqual(item['description_review_status'], 'Needs description review')
        self.assertEqual(item['local']['explanation_en'], '')
        self.assertEqual(item['source']['source_text'], 'Synthetic two-sided risk')
        self.assertEqual(result['summary']['enabled'], 1)
        self.assertNotIn('/synthetic', json.dumps(result))

    def test_metadata_and_disable_survive_a_fresh_python_process(self):
        self.publish(rows()); item = catalogue.catalogue()['items'][0]
        self.save(item, enabled=False, explanation_no='Syntetisk forklaring', mitigating_controls_en='Synthetic dual approval', description_review_status='Reviewed')
        saved = catalogue.catalogue()['items'][0]
        self.assertFalse(saved['new']); self.assertFalse(saved['local']['enabled'])
        self.assertEqual(saved['description_review_status'], 'Reviewed')
        script = "import sod_catalogue; item=sod_catalogue.read().entries['SYN01']; assert not item.metadata.enabled; assert item.metadata.explanation_no=='Syntetisk forklaring'"
        result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, 'Fresh-process catalogue persistence failed')

    def test_source_changes_preserve_metadata_and_require_description_revalidation(self):
        self.publish(rows()); self.save(catalogue.catalogue()['items'][0], display_name='Synthetic local title', notes='Synthetic note', enabled=False, description_review_status='Reviewed')
        self.publish(rows(description='Changed synthetic source'))
        item = catalogue.catalogue()['items'][0]
        self.assertTrue(item['source_changed'])
        self.assertEqual(item['description_review_status'], 'Needs description review')
        self.assertEqual(item['local']['display_name'], 'Synthetic local title')
        self.assertFalse(item['local']['enabled'])
        self.assertEqual(item['source']['source_text'], 'Changed synthetic source')

    def test_removed_risks_remain_historical_and_reappear_with_local_choices(self):
        self.publish(rows()); self.save(catalogue.catalogue()['items'][0], enabled=False, notes='Retain synthetic history')
        self.publish(rows('SYN02'))
        items = {item['risk_id']: item for item in catalogue.catalogue()['items']}
        self.assertFalse(items['SYN01']['current']); self.assertFalse(items['SYN01']['local']['enabled'])
        self.assertTrue(items['SYN02']['new']); self.assertTrue(items['SYN02']['local']['enabled'])
        self.publish(rows())
        old = next(item for item in catalogue.catalogue()['items'] if item['risk_id'] == 'SYN01')
        self.assertTrue(old['current']); self.assertFalse(old['local']['enabled'])
        self.assertEqual(old['local']['notes'], 'Retain synthetic history')

    def test_bulk_requires_confirmation_and_keeps_description_review_separate(self):
        self.publish(rows() + rows('SYN02'))
        with self.assertRaises(HTTPException) as caught:
            catalogue.bulk(False, 0)
        self.assertEqual(caught.exception.status_code, 422)
        self.assertFalse((self.root / 'config' / 'sod-catalogue.json').exists())
        result = catalogue.bulk(False, 0, True)
        self.assertEqual(result['updated'], 2)
        items = catalogue.catalogue()['items']
        self.assertTrue(all(not item['local']['enabled'] for item in items))
        self.assertTrue(all(item['description_review_status'] == 'Needs description review' for item in items))
        catalogue.bulk(True, result['revision'])
        self.assertTrue(all(item['local']['enabled'] for item in catalogue.catalogue()['items']))

    def test_bulk_does_not_acknowledge_changed_descriptions(self):
        self.publish(rows()); self.save(catalogue.catalogue()['items'][0], description_review_status='Reviewed')
        self.publish(rows(description='Changed source'))
        catalogue.bulk(False, catalogue.read().revision, True)
        item = catalogue.catalogue()['items'][0]
        self.assertTrue(item['source_changed'])
        self.assertEqual(item['description_review_status'], 'Needs description review')

    def test_stale_revision_and_definition_cannot_overwrite_metadata(self):
        self.publish(rows()); first = catalogue.catalogue()['items'][0]
        self.save(first, notes='Saved note')
        with self.assertRaises(HTTPException):
            catalogue.save('SYN01', first['local'], 0, first['definition_version'])
        self.publish(rows(description='Changed source'))
        with self.assertRaises(HTTPException):
            catalogue.save('SYN01', first['local'], 1, first['definition_version'])
        self.assertEqual(catalogue.read().entries['SYN01'].metadata.notes, 'Saved note')

    def test_invalid_storage_and_failed_write_preserve_original(self):
        self.publish(rows()); item = catalogue.catalogue()['items'][0]
        self.save(item, notes='Original')
        path = self.root / 'config' / 'sod-catalogue.json'; original = path.read_bytes()
        with patch('sod_catalogue.atomic_write', side_effect=PermissionError('Synthetic failure')):
            with self.assertRaises(HTTPException):
                self.save(item, notes='Uncommitted')
        self.assertEqual(path.read_bytes(), original)
        path.write_text('{invalid')
        with self.assertRaises(HTTPException): catalogue.read()
        self.assertEqual(path.read_text(), '{invalid')

    def test_corrupt_historical_snapshot_fails_without_discarding_current_source(self):
        self.publish(rows()); snapshot = cache.get_snapshot()
        reference = config.get_settings().data_lifecycle.sod_history[0]
        path = self.root / 'config' / 'csv-data' / 'snapshots' / (reference.snapshot + '.json')
        path.write_text('corrupt')
        with self.assertRaises(HTTPException): catalogue.catalogue()
        self.assertIs(cache.get_snapshot(), snapshot)

    def test_api_filter_sort_pagination_and_strict_edit_contract(self):
        self.publish(rows() + rows('SYN02'))
        result = self.client.get('/api/sod/catalogue?search=SYN*&limit=1&descending=true')
        self.assertEqual(result.status_code, 200)
        data = result.json(); self.assertEqual(data['total'], 2)
        self.assertEqual(data['items'][0]['risk_id'], 'SYN02')
        item = data['items'][0]
        response = self.client.post('/api/sod/catalogue/SYN02', json=dict(expected_revision=0, definition_version=item['definition_version'], metadata={**item['local'], 'business_category':'Synthetic finance','enabled':False}))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get('/api/sod/catalogue?enabled=disabled&category=Synthetic%20finance').json()['total'], 1)
        self.assertEqual(self.client.get('/api/sod/catalogue?status=unsupported').json()['total'], 0)
        self.assertEqual(self.client.get('/api/sod/catalogue?current=all').status_code, 422)
        self.assertEqual(self.client.post('/api/sod/catalogue/bulk', json=dict(expected_revision=1, enabled=False)).status_code, 422)
        self.assertEqual(self.client.post('/api/sod/catalogue/SYN02', json=dict(expected_revision=1, definition_version=item['definition_version'], metadata={'invented':'value'})).status_code, 422)

    def test_catalogue_read_captures_settings_and_source_under_publication_lock(self):
        original = catalogue.catalogue
        def inspect_lock(*args, **kwargs):
            self.assertTrue(cache._load_lock.locked())
            return original(*args, **kwargs)
        with patch('routers.sod.store.catalogue', side_effect=inspect_lock):
            response = self.client.get('/api/sod/catalogue')
        self.assertEqual(response.status_code, 200)

    def test_application_boundary_and_api_stale_revision(self):
        from main import create_app
        self.publish(rows())
        client = TestClient(create_app(session_token='synthetic-catalogue-session'), base_url='http://127.0.0.1:18743')
        self.assertEqual(client.get('/api/sod/catalogue').status_code, 403)
        headers = {'X-SAP-Lens': 'synthetic-catalogue-session'}
        response = client.get('/api/sod/catalogue', headers=headers)
        self.assertEqual(response.status_code, 200)
        item = response.json()['items'][0]
        body = dict(expected_revision=10, definition_version=item['definition_version'], metadata=item['local'])
        self.assertEqual(client.post('/api/sod/catalogue/SYN01', json=body, headers=headers).status_code, 409)
        self.assertEqual(catalogue.read().revision, 0)

    def test_capacity_limit_fails_safely_without_partial_bulk_or_save(self):
        self.publish(rows() + rows('SYN02'))
        items = catalogue.catalogue()['items']
        with patch('sod_catalogue.MAX_RISKS', 1):
            with self.assertRaises(HTTPException): catalogue.bulk(False, 0, True)
            self.assertEqual(catalogue.read().revision, 0)
            self.save(items[0], notes='Preserve first annotation')
            with self.assertRaises(HTTPException): self.save(items[1])
        self.assertEqual(set(catalogue.read().entries), {'SYN01'})

    def test_unconfigured_catalogue_is_a_non_error_empty_state(self):
        result = self.client.get('/api/sod/catalogue')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['total'], 0)
        self.assertFalse(result.json()['source']['loaded'])


if __name__ == '__main__':
    unittest.main()
