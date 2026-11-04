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
        with (ROOT/'examples/role-catalogue.example.csv').open(encoding='utf-8-sig') as stream:
            rows=list(csv.DictReader(stream))
        self.assertTrue(rows)
        self.assertTrue(all('SYN' in r['AGR_NAME'].upper() for r in rows))
        self.assertFalse((ROOT/'examples/synthetic.csv').exists(), 'the obsolete example was superseded by the linked example datasets')
        example=json.loads((ROOT/'examples/synthetic-profile.sap-lens.json').read_text())
        self.assertEqual(example['settings']['data_csv_path'],'')
        self.assertEqual(example['settings']['organization']['name'],'Example Inc.')
        self.assertIsNone(example['logo_base64'])

    def test_local_data_exclusions_and_explicit_distribution_inputs(self):
        for file in ['csv-data/snapshots/private.json','nested/csv-data/reports/private.json','saved-filters.json','nested/saved-filters.json','account-review.json','nested/account-review.json','local-config/settings.json','user-branding/private.png','app-data/runtime.json','local.csv','private.sap-lens.json']:
            result=subprocess.run(['git','check-ignore','-q',file],cwd=ROOT)
            self.assertEqual(result.returncode,0,file)
        for file in ['examples/role-catalogue.example.csv','frontend/tests/fixtures/role-catalogue-minimal.csv','examples/synthetic-profile.sap-lens.json']:
            result=subprocess.run(['git','check-ignore','-q',file],cwd=ROOT)
            self.assertEqual(result.returncode,1,file)
        build=(ROOT/'scripts/build-windows.ps1').read_text()
        self.assertNotIn('--add-data "backend',build)
        self.assertNotIn('settings.json',build)
        self.assertNotIn('*.csv',build)


    def test_docker_build_context_is_an_allowlist_that_excludes_private_and_test_content(self):
        lines=[line.strip() for line in (ROOT/'.dockerignore').read_text().splitlines() if line.strip() and not line.startswith('#')]
        self.assertEqual(lines[0],'**')  # everything is excluded unless explicitly allowed
        for denied in ('**/*.csv','**/*.secret','**/.env*','**/settings.json','**/snapshots/**','**/employee-directory/**','frontend/test-results/'):
            self.assertIn(denied,lines)
        allowed=[line[1:] for line in lines if line.startswith('!')]
        for forbidden in ('frontend/tests','backend/tests','examples','docs','.github','deploy'):
            self.assertFalse(any(item==forbidden or item.startswith(forbidden+'/') for item in allowed),forbidden)
        for required in ('Dockerfile','backend/requirements.txt','backend/resources/*.json','frontend/src/**','assets/sap-lens.png'):
            self.assertIn(required,allowed)


if __name__=='__main__':unittest.main()
