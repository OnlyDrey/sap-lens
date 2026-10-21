"""Saved colors remain portable and cannot defeat readable primary controls."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from pydantic import ValidationError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import config
import cache
from config_models import AppConfig, ThemePalette, ThemePreset
from portable_config import export_configuration, read_portable, PortableConfig
from theme_colors import contrast
from diagnostics import diagnostics_snapshot
from fastapi.testclient import TestClient
from main import create_app


class ThemeAndDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.environment=patch.dict(os.environ,{'SAP_LENS_CONFIG_DIR':self.temp.name,'DATA_CSV_PATH':''})
        self.environment.start();config.get_settings.cache_clear();cache.clear_cache()
    def tearDown(self):
        config.get_settings.cache_clear();self.environment.stop();self.temp.cleanup()

    def test_older_schema_two_adds_safe_default_palettes_without_losing_preferences(self):
        old=AppConfig(theme='system').model_dump();old.pop('theme_colors')
        old['organization']['name']=''
        Path(self.temp.name,'settings.json').write_text(json.dumps(old))
        loaded=config.get_settings()
        self.assertEqual(loaded.theme,'system')
        self.assertEqual(loaded.organization.name,'')
        self.assertEqual(loaded.theme_colors.dark.primary,'#1a003b')
        self.assertFalse(config.configuration_notice())
        self.assertEqual(AppConfig().theme,'dark')

    def test_colors_named_presets_persist_and_export_in_both_modes(self):
        settings=AppConfig();settings.theme_colors.dark.primary='#123456'
        settings.theme_colors.custom_presets=[ThemePreset(name='Synthetic theme',mode='dark',colors=settings.theme_colors.dark.model_copy())]
        config.save_configuration(settings,0);config.get_settings.cache_clear()
        saved=config.get_settings()
        self.assertEqual(saved.theme_colors.dark.primary,'#123456')
        for private in [False,True]:
            package=export_configuration(saved,private)
            restored=read_portable(PortableConfig.model_validate(package),'')
            self.assertEqual(restored.theme_colors,saved.theme_colors)
            self.assertEqual(restored.theme_colors.custom_presets[0].name,'Synthetic theme')

    def test_invalid_hex_low_contrast_and_duplicate_presets_are_rejected(self):
        self.assertEqual(contrast('#000000','#ffffff'),21)
        for values in [{'primary':'red'},{'accent':'#fff'},{'text':'#111827'},{'background':'#f1f5f9'}]:
            with self.assertRaises(ValidationError):ThemePalette(**values)
        settings=AppConfig().model_dump()
        preset={'name':'Synthetic','mode':'dark','colors':settings['theme_colors']['dark']}
        settings['theme_colors']['custom_presets']=[preset,{**preset,'name':'synthetic'}]
        with self.assertRaises(ValidationError):AppConfig.model_validate(settings)

    def test_invalid_palette_api_keeps_saved_configuration(self):
        with TestClient(create_app(),base_url='http://127.0.0.1:18743') as client:
            settings=client.get('/api/configuration').json()['settings']
            settings['theme_colors']['dark']['text']='#111827'
            response=client.post('/api/configuration',json=settings,headers={'X-SAP-Lens':'1'})
            self.assertEqual(response.status_code,422)
            self.assertEqual(client.get('/api/configuration').json()['settings']['revision'],0)
            self.assertFalse(Path(self.temp.name,'settings.json').exists())

    def test_diagnostic_export_is_allowlisted_and_api_is_guarded(self):
        settings=AppConfig();settings.data_csv_path=str(Path(self.temp.name,'synthetic-private.csv'))
        settings.organization.name='Synthetic private identity';config.save_configuration(settings,0)
        report=diagnostics_snapshot()
        raw=json.dumps(report)
        for forbidden in [self.temp.name,'Synthetic private identity','synthetic-private.csv','session','rules']:
            self.assertNotIn(forbidden,raw)
        self.assertIn('application_directory',diagnostics_snapshot(private=True))
        with TestClient(create_app(origin='http://127.0.0.1:18743',session_token='synthetic-capability'),base_url='http://127.0.0.1:18743') as client:
            self.assertEqual(client.get('/api/diagnostics').status_code,403)
            result=client.get('/api/diagnostics/export',headers={'X-SAP-Lens':'synthetic-capability'})
            self.assertEqual(result.status_code,200)
            self.assertNotIn('data_source',result.json())
            self.assertEqual(result.headers['cache-control'],'no-store')
