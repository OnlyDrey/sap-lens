"""SoD Settings health reflects one published generation, without exported paths."""
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
from csv_lifecycle import load
from diagnostics import diagnostics_snapshot
from employee_directory import store
from sod_import import HEADERS


class SodSettingsIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'SAP_LENS_CONFIG_DIR': str(self.root/'private'), 'DATA_CSV_PATH': ''})
        self.env.start()
        config.get_settings.cache_clear(); cache.clear_cache(); store.clear()

    def tearDown(self):
        config.get_settings.cache_clear(); cache.clear_cache(); store.clear(); self.env.stop()

    def activate(self):
        path = self.root/'synthetic-matrix.csv'
        base = dict(RISK='SYN01', CRITICITY='H', TYPE='S', TEXT='Synthetic review', ACTVT1='CREATE', ACTVT2='APPROVE', TTEXT='')
        with path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=HEADERS); writer.writeheader()
            for slot, activity, code in [('ACTVT1','CREATE','X001'), ('ACTVT2','APPROVE','X002')]:
                writer.writerow(dict(base, ACTIVITY_SLOT=slot, ACTIVITY=activity, TCODE=code))
        settings = config.get_settings().model_copy(deep=True); settings.sod_csv_path = str(path)
        load(settings, operation='import', strict=True, force=('sod',))
        return path

    def test_source_health_is_neutral_before_configuration(self):
        source = next(row for row in diagnostics_snapshot()['sources'] if row['id']=='sod')
        self.assertFalse(source['configured']); self.assertFalse(source['loaded'])
        self.assertIsNone(source['error']); self.assertEqual(source['mode'], 'static')

    def test_source_status_and_export_redaction_use_committed_snapshot(self):
        path = self.activate()
        report = diagnostics_snapshot()
        source = next(row for row in report['sources'] if row['id']=='sod')
        self.assertTrue(source['loaded']); self.assertTrue(source['snapshot_available'])
        self.assertEqual(source['records'], 2)
        self.assertEqual(source['last_successful_load'], config.get_settings().data_lifecycle.sources['sod'].imported_at)
        self.assertNotIn(str(path), json.dumps(report))
        self.assertNotIn('Synthetic review', json.dumps(report))
        path.unlink()
        cache.clear_cache(); load(operation='startup')
        self.assertTrue(next(row for row in diagnostics_snapshot()['sources'] if row['id']=='sod')['loaded'])

    def test_data_health_uses_source_timestamp_not_sap_generation(self):
        from routers.data_health import overview
        self.activate()
        report = overview(finding='', offset=0, limit=25)
        source = next(row for row in report['sources'] if row['id']=='sod')
        self.assertTrue(source['available']); self.assertEqual(source['records'], 2)
        self.assertIsNotNone(source['last_successful']); self.assertIsNone(report['data_revision'])
