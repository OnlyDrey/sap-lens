"""Local contract tests; fixtures never run workflows or contact services."""
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]

def module(name):
    spec = spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    result = module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class WorkflowContracts(unittest.TestCase):
    def test_workflow_loader_refuses_python_object_tags(self):
        import yaml
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / '.github/workflows'
            target.mkdir(parents=True)
            (target / 'validate.yml').write_text('!!python/object:builtins.object {}')
            with self.assertRaises(yaml.constructor.ConstructorError):
                module('check-workflows').check(Path(directory))

    def test_actual_main_only_workflow(self):
        module('check-workflows').check()

    def test_forbidden_triggers_and_permissions_fail_closed(self):
        original = (ROOT / '.github/workflows/validate.yml').read_text()
        for before, after in [('branches: [main]', 'branches: [work]'), ('push:', 'pull_request:'),
                              ('push:\n    branches: [main]', 'workflow_dispatch: {}'), ('contents: read', 'contents: write')]:
            with self.subTest(after=after), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / '.github/workflows'
                target.mkdir(parents=True)
                (target / 'validate.yml').write_text(original.replace(before, after))
                with self.assertRaises(AssertionError):
                    module('check-workflows').check(Path(directory))

    def test_only_the_main_push_workflow_exists(self):
        # SAP Lens 1's workflows were archived with it outside the repository; only the .NET validation workflow remains.
        self.assertEqual(['validate.yml'], [p.name for p in (ROOT / '.github/workflows').glob('*.yml')])


class DeploymentContracts(unittest.TestCase):
    def test_canonical_structure_and_versions(self):
        module('check-structure').check()


class DependencyAuditContracts(unittest.TestCase):
    def test_complete_reports_preserve_vulnerability_findings(self):
        audit = module('check-dependencies')
        self.assertEqual([], audit.findings({'version': 1, 'projects': [{'path': 'app.csproj'}]}))
        report = {'version': 1, 'projects': [{'path': 'app.csproj', 'frameworks': [{'transitivePackages': [
            {'id': 'Synthetic.Package', 'resolvedVersion': '1.0.0', 'vulnerabilities': [{'severity': 'High'}]}
        ]}]}]}
        self.assertEqual([('app.csproj', 'Synthetic.Package', '1.0.0')], audit.findings(report))

    def test_incomplete_or_failed_advisory_queries_never_pass(self):
        for report in ({}, {'version': 1, 'projects': []}, {'version': 2, 'projects': [{}]},
                       {'version': 1, 'projects': [{}], 'logs': [{'level': 'Warning', 'code': 'NU1900'}]}):
            with self.subTest(report=report), self.assertRaises(ValueError):
                module('check-dependencies').findings(report)


if __name__ == '__main__':
    unittest.main()
