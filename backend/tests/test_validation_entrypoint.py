"""Lean policy, source ownership and production-storage isolation; no full suites."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('lean_validation',ROOT/'scripts/validate.py')
validation=importlib.util.module_from_spec(spec);spec.loader.exec_module(validation)


class LeanValidationTests(unittest.TestCase):
    def setUp(self):self.mapping=json.loads((ROOT/'scripts/test-map.json').read_text())
    def test_levels_delegate_selection_to_the_run_tests_profiles(self):
        self.assertEqual(validation.plan('fast',[],'HEAD',self.mapping),['quick','--base','HEAD'])
        self.assertEqual(validation.plan('feature',[],'origin/work',self.mapping),['targeted','--base','origin/work'])
        self.assertEqual(validation.plan('fast',['sod'],'HEAD',self.mapping),['quick','sod'])
        self.assertEqual(validation.plan('regression',[],'HEAD',self.mapping),['regression'])
    def test_feature_includes_declared_shared_dependents(self):
        selected=validation.plan('feature',['shared-ui'],'HEAD',self.mapping)
        for name in ('sod','settings','user-access','role-lookup'):self.assertIn(name,selected)
    def test_explicit_full_is_the_complete_collection(self):
        self.assertEqual(validation.plan('full',[],'HEAD',self.mapping),['full'])
    def test_all_declared_source_owners_and_dependencies_exist(self):
        known=set(self.mapping['features'])
        for rule in self.mapping['validation_sources']:self.assertLessEqual(set(rule['areas']),known)
        for owner,dependencies in self.mapping['validation_dependencies'].items():
            self.assertIn(owner,known);self.assertLessEqual(set(dependencies),known)
    def test_environment_excludes_production_credentials_and_paths(self):
        with tempfile.TemporaryDirectory() as temporary,patch.dict(os.environ,{'SAP_LENS_AUTH_SECRET_FILE':'synthetic-private-location','SAP_LENS_DATA_DIR':'synthetic-production','DATA_CSV_PATH':'synthetic-private.csv'}):
            env=validation.isolated_environment(Path(temporary))
            self.assertNotIn('SAP_LENS_AUTH_SECRET_FILE',env)
            self.assertTrue(Path(env['SAP_LENS_DATA_DIR']).is_relative_to(temporary))
            self.assertEqual(env['DATA_CSV_PATH'],'')
    def test_area_aliases_and_unknown_area(self):
        self.assertIn('deployment',validation.plan('fast',['packaging'],'HEAD',self.mapping))
        with self.assertRaisesRegex(ValueError,'Unknown area'):validation.plan('feature',['missing'],'HEAD',self.mapping)
    def test_driver_delegates_and_propagates_failure_in_isolated_storage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'scripts').mkdir();(root/'scripts/test-map.json').write_text(json.dumps(self.mapping))
            with patch.object(validation,'ROOT',root),patch.object(validation,'execute',return_value=7) as execute:
                self.assertEqual(validation.main(['--level','fast','--area','sod']),7)
            command,log,env,timeout=execute.call_args.args
            self.assertIn('run-tests.py',command[1]);self.assertEqual(command[2:4],['quick','sod'])
            self.assertNotIn('regression',command);self.assertNotIn('full',command)
            self.assertFalse(Path(env['SAP_LENS_DATA_DIR']).parent.exists())
            self.assertTrue(log.is_relative_to(root/'build'))
            self.assertGreater(timeout,0)

    def test_full_cannot_be_silently_narrowed_or_skip_its_build(self):
        for level in ('full','regression'):
            for option in [['--grep','one'],['--area','sod'],['--no-build']]:
                with patch('sys.stderr'),self.assertRaises(SystemExit) as error:validation.main(['--level',level,*option])
                self.assertEqual(error.exception.code,2)
