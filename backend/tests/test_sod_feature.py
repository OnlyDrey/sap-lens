"""SoD is a manual feature: never enabled by a source, data preserved while disabled, existing installs migrate as enabled."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI
from fastapi.testclient import TestClient
import cache
import config
from config_models import AppConfig, FeatureSettings, SourceSnapshot
from routers.sod_analysis import router
from test_sod_analysis_api import synthetic_snapshot


class SodFeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(self.root), 'DATA_CSV_PATH': ''})
        self.env.start(); config.get_settings.cache_clear(); cache.clear_cache()
        cache._cache = synthetic_snapshot()
        app = FastAPI(); app.include_router(router)
        self.client = TestClient(app)

    def tearDown(self):
        cache.clear_cache(); config.get_settings.cache_clear(); self.env.stop(); self.temp.cleanup()

    def configure(self, **features):
        settings = config.get_settings().model_copy(deep=True)
        settings.sod_csv_path = str(self.root / 'matrix.csv')
        settings.data_lifecycle.sources['sod'] = SourceSnapshot(snapshot='a' * 64, path=settings.sod_csv_path, imported_at='2026-10-27T00:00:00+00:00', checked_at='2026-10-27T00:00:00+00:00')
        for key, value in features.items(): setattr(settings.features, key, value)
        config.save_configuration(settings, settings.revision)

    def analysis(self):
        response = self.client.get('/api/sod/analysis', params={'as_of': '2026-10-27'})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_fresh_configuration_is_disabled_and_a_source_never_enables_it(self):
        self.assertFalse(AppConfig().features.sod)
        self.assertFalse(FeatureSettings().sod)
        self.configure()
        self.assertFalse(config.get_settings().features.sod)
        result = self.analysis()
        self.assertEqual(result['total'], 0)
        self.assertEqual(result['coverage']['reason'], 'sod_disabled')

    def test_legacy_settings_with_a_sod_source_stay_enabled_but_without_a_source_stay_off(self):
        legacy = json.loads(AppConfig(sod_csv_path=str(self.root / 'm.csv')).model_dump_json())
        legacy['features'].pop('sod')
        self.assertTrue(AppConfig.model_validate(legacy).features.sod)
        legacy['sod_csv_path'] = ''
        self.assertFalse(AppConfig.model_validate(legacy).features.sod)
        explicit = json.loads(AppConfig(sod_csv_path=str(self.root / 'm.csv')).model_dump_json())
        explicit['features']['sod'] = False
        self.assertFalse(AppConfig.model_validate(explicit).features.sod)

    def test_disabling_preserves_source_and_reenabling_restores_analysis_without_reimport(self):
        self.configure(sod=True)
        enabled = self.analysis()
        self.assertEqual(enabled['total'], 2)
        self.configure(sod=False)
        self.assertEqual(self.analysis()['coverage']['reason'], 'sod_disabled')
        self.assertTrue(cache.get_snapshot().sod)
        self.assertIn('sod', config.get_settings().data_lifecycle.sources)
        self.configure(sod=True)
        self.assertEqual(self.analysis()['total'], 2)


if __name__ == '__main__':
    unittest.main()
