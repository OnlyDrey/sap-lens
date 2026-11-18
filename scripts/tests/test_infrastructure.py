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

    def test_archived_workflows_cannot_run(self):
        self.assertEqual(['validate.yml'], [p.name for p in (ROOT / '.github/workflows').glob('*.yml')])
        self.assertEqual(4, len(list((ROOT / 'legacy/v1/.github/workflows').glob('*.yml'))))


class DeploymentContracts(unittest.TestCase):
    def test_canonical_structure_and_versions(self):
        module('check-structure').check()

    def test_image_preserves_tls_nonroot_and_data_boundaries(self):
        dockerfile = (ROOT / 'Dockerfile').read_text()
        for expected in ('node:24', 'dotnet/sdk:10.0', 'dotnet/aspnet:10.0', 'USER app', 'VOLUME /data', 'HEALTHCHECK'):
            self.assertIn(expected, dockerfile)
        self.assertNotIn('COPY legacy', dockerfile)
        probe = (ROOT / 'backend/scripts/docker/healthcheck.sh').read_text()
        self.assertIn('--cacert', probe)
        self.assertIn('/health/ready', probe)
        self.assertNotIn('--insecure', probe)
        self.assertIn('--max-time 3', probe)

    def test_context_excludes_legacy_and_private_data(self):
        ignore = (ROOT / '.dockerignore').read_text()
        self.assertTrue(ignore.startswith('**\n'))
        for pattern in ('**/*.key', '**/*.sqlite3', '**/bin/', '**/obj/'):
            self.assertIn(pattern, ignore)
        self.assertNotIn('!legacy', ignore)


if __name__ == '__main__':
    unittest.main()
