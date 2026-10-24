"""Public-tree invariants, without embedding any real organization identifiers."""
import csv
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
from config_models import AppConfig


class RepositoryPrivacyTests(unittest.TestCase):
    def test_only_product_assets_are_public(self):
        allowed={'favicon.png','sap-lens.png','theme.js'}
        self.assertEqual({p.name for p in (ROOT/'frontend/public').iterdir() if p.is_file()},allowed)
        self.assertTrue((ROOT/'assets/sap-lens.ico').is_file())
        self.assertEqual(AppConfig().organization.name,'Example Inc.')
        self.assertIsNone(AppConfig().logo_id)

    def test_synthetic_examples_and_no_configuration_paths(self):
        with (ROOT/'examples/synthetic.csv').open() as stream:
            rows=list(csv.DictReader(stream))
        self.assertTrue(rows)
        self.assertTrue(all(r['AGR_NAME'].startswith('DEMO_') and 'Synthetic' in r['TEXT'] for r in rows))
        example=json.loads((ROOT/'examples/synthetic-profile.sap-lens.json').read_text())
        self.assertEqual(example['settings']['data_csv_path'],'')
        self.assertEqual(example['settings']['organization']['name'],'Example Inc.')
        self.assertIsNone(example['logo_base64'])

    def test_local_data_exclusions_and_explicit_distribution_inputs(self):
        for file in ['saved-filters.json','nested/saved-filters.json','account-review.json','nested/account-review.json','local-config/settings.json','user-branding/private.png','app-data/runtime.json','local.csv','private.sap-lens.json']:
            result=subprocess.run(['git','check-ignore','-q',file],cwd=ROOT)
            self.assertEqual(result.returncode,0,file)
        for file in ['examples/synthetic.csv','frontend/tests/fixtures/synthetic.csv','examples/synthetic-profile.sap-lens.json']:
            result=subprocess.run(['git','check-ignore','-q',file],cwd=ROOT)
            self.assertEqual(result.returncode,1,file)
        build=(ROOT/'scripts/build-windows.ps1').read_text()
        self.assertNotIn('--add-data "backend',build)
        self.assertNotIn('settings.json',build)
        self.assertNotIn('*.csv',build)


if __name__=='__main__':unittest.main()
