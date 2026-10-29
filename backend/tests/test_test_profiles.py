"""Integrity of the test profiles: no test file may be silently left out of regression."""
import importlib.util
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('run_tests_script', ROOT / 'scripts' / 'run-tests.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class TestProfileTests(unittest.TestCase):
    def test_every_backend_module_and_browser_spec_belongs_to_exactly_one_feature(self):
        self.assertEqual(runner.coverage_problems(), [])

    def test_smoke_backend_selection_resolves_to_real_tests(self):
        loader = unittest.TestLoader()
        for name in runner.load_map()['smoke']['backend']:
            try:
                suite = loader.loadTestsFromName(name)
            except (ImportError, AttributeError) as error:
                self.fail(f'{name} does not resolve: {error}')
            self.assertGreater(suite.countTestCases(), 0, name)
            self.assertNotIn('_FailedTest', repr(suite), name)

    def test_smoke_browser_tests_exist_and_cover_the_critical_features(self):
        tag = runner.load_map()['smoke']['browser_tag']
        owners = {}
        for feature, entry in runner.load_map()['features'].items():
            for spec_name in entry['browser']:
                text = (ROOT / 'frontend' / 'tests' / f'{spec_name}.spec.ts').read_text(encoding='utf-8')
                if re.search(rf"tag:\s*'{re.escape(tag)}'", text):
                    owners.setdefault(feature, []).append(spec_name)
        for feature in ('dashboard', 'role-lookup', 'user-access', 'access-package', 'account-review', 'data-sources', 'sod', 'shared-ui', 'platform', 'role-comparison'):
            self.assertIn(feature, owners, f'no {tag} browser test for {feature}')

    def test_map_has_known_feature_descriptions_and_no_empty_features(self):
        for name, feature in runner.load_map()['features'].items():
            self.assertTrue(feature['description'], name)
            self.assertTrue(feature['backend'] or feature['browser'], name)


if __name__ == '__main__':
    unittest.main()
