"""The generated-output layout: one root, ignored by Git and Docker, honored by the producers, and safe to clean."""
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))

from build_system import artifacts, layout, targets  # noqa: E402
from build_system.runner import BuildError  # noqa: E402


def read(relative):
    return (ROOT / relative).read_text(encoding='utf-8')


class LayoutContractTests(unittest.TestCase):
    def test_every_output_lives_under_the_single_root_and_is_not_tracked(self):
        for name, (relative, description) in layout.OUTPUTS.items():
            self.assertTrue(relative.startswith('dist/'), name); self.assertTrue(description)
            self.assertTrue(layout.is_inside_artifact_root(ROOT / relative))
        tracked = subprocess.check_output(['git', 'ls-files', 'dist'], cwd=ROOT, text=True).split()
        self.assertEqual(tracked, [])                                                 # no artifact is committed

    def test_git_ignores_the_whole_root_for_every_layout_and_future_subfolder(self):
        self.assertIn('/dist/', read('.gitignore').splitlines())
        samples = [f'{path}/artifact.zip' for path, _ in layout.OUTPUTS.values()] + ['dist/1.0.0-beta.2/x.tar.gz', 'dist/windows/desktop/SAP-Lens.exe', 'dist/linux/native/x', 'dist/manifests/build-manifest.json', 'dist/.sap-lens-clean.lock']
        for sample in samples:
            self.assertEqual(subprocess.run(['git', 'check-ignore', '-q', sample], cwd=ROOT).returncode, 0, sample)
        for source in ('frontend/src/main.tsx', 'backend/main.py', 'scripts/build.py', 'docs/BUILD.md'):
            self.assertEqual(subprocess.run(['git', 'check-ignore', '-q', source], cwd=ROOT).returncode, 1, source)  # sources stay trackable

    def test_docker_context_never_contains_the_artifact_root_but_keeps_the_frontend_build(self):
        lines = [line.strip() for line in read('.dockerignore').splitlines() if line.strip() and not line.startswith('#')]
        self.assertEqual(lines[0], '**')                                              # allowlist: everything else is excluded
        allowed = [line[1:] for line in lines if line.startswith('!')]
        self.assertNotIn('dist', allowed); self.assertFalse([item for item in allowed if item.startswith('dist/')])
        self.assertIn('frontend/dist/', allowed)                                      # the compiled frontend is a required build input
        dockerfile = read('Dockerfile')
        self.assertIn('COPY frontend/dist/', dockerfile)
        for line in dockerfile.splitlines():
            if line.startswith('COPY') and '--from' not in line:
                self.assertNotRegex(line, r'(^|\s)dist/', line)                      # nothing copies from the repository-root dist

    def test_producers_and_workflows_use_the_documented_locations(self):
        expected = {
            'scripts/build-local.ps1': ('dist/local',), 'scripts/build-server-windows.ps1': ('dist/server',),
            'scripts/package-windows-deployment.ps1': ('dist/deployment',), 'scripts/deployment/package-docker.py': ('dist/deployment',),
            '.github/workflows/build-deployments.yml': ('dist/deployment/*', 'dist/publication'),
        }
        for relative, needles in expected.items():
            for needle in needles:
                self.assertIn(needle, read(relative), f'{relative} should reference {needle}')

    def test_deployment_layout_is_shared_by_all_targets_and_remote_retrieval(self):
        # The real constructor and remote retriever both use this exact shared function;
        # constructor/override/manifest behavior is exercised in SourceOutputIsolation.
        import importlib.util
        spec = importlib.util.spec_from_file_location('layout_builder', ROOT / 'scripts/deployment/build-deployments.py')
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        self.assertIs(builder.output_name, layout.deployment_output_name)
        for target in builder.TARGETS:
            with self.subTest(target=target):
                self.assertEqual(builder.output_name('1.0.0-beta.2', 'a'*40), '1.0.0-beta.2-' + 'a'*12)
        self.assertNotEqual(builder.output_name('1.0.0-beta.2', 'a'*40), builder.output_name('1.0.0-beta.2', 'b'*40))

    def test_reparse_outputs_are_rejected_without_rejecting_ordinary_aliases(self):
        path = Mock()
        path.lstat.return_value = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        self.assertTrue(layout.is_linked_output(path))
        path.lstat.return_value = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0)
        self.assertFalse(layout.is_linked_output(path))
        path.lstat.return_value = SimpleNamespace(st_mode=stat.S_IFLNK)
        self.assertTrue(layout.is_linked_output(path))
        path.lstat.side_effect = FileNotFoundError
        self.assertFalse(layout.is_linked_output(path))
        path.lstat.side_effect = PermissionError
        with self.assertRaises(PermissionError):
            layout.is_linked_output(path)

    def test_clean_only_targets_generated_locations(self):
        for relative in layout.GENERATED:
            self.assertFalse(Path(relative).is_absolute()); self.assertNotIn('..', Path(relative).parts)
            self.assertTrue(relative.startswith(('dist/', 'backend/build', 'backend/dist', 'frontend/dist')), relative)
        self.assertNotIn('dist/publication', layout.GENERATED)                      # staging for the release job is never wiped locally
        for protected in ('backend', 'frontend', 'frontend/src', 'scripts', 'docs', 'dist', ''):
            self.assertNotIn(protected, layout.GENERATED)
        self.assertIs(targets.CLEAN_PATHS, layout.GENERATED)


class CleanSafetyTests(unittest.TestCase):
    def args(self, **extra):
        return SimpleNamespace(output=None, confirm_clean=True, dry_run=False, **extra)

    def run_clean(self, root):
        with patch.object(targets, 'ROOT', root):
            return targets.clean(self.args(), Mock())

    def test_a_linked_output_directory_is_refused_and_its_target_is_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary); root = base / 'repo'; outside = base / 'user-data'
            (root / 'dist').mkdir(parents=True); outside.mkdir(); (outside / 'precious.db').write_text('keep')
            try:
                (root / 'dist/local').symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest('symbolic links are not permitted here')
            with self.assertRaises(BuildError):
                self.run_clean(root)
            self.assertEqual((outside / 'precious.db').read_text(), 'keep')

    def test_clean_removes_generated_output_and_nothing_else(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative, keep in (('dist/deployment/a.zip', False), ('dist/local/run/x', False), ('frontend/dist/index.html', False), ('backend/build/log', False),
                                   ('frontend/src/main.tsx', True), ('backend/main.py', True), ('docs/BUILD.md', True), ('examples/role-catalogue.example.csv', True)):
                path = root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('x')
            self.run_clean(root)
            for relative in ('dist/deployment/a.zip', 'dist/local/run/x', 'frontend/dist/index.html', 'backend/build/log'):
                self.assertFalse((root / relative).exists(), relative)
            for relative in ('frontend/src/main.tsx', 'backend/main.py', 'docs/BUILD.md', 'examples/role-catalogue.example.csv'):
                self.assertTrue((root / relative).exists(), relative)

    def test_clean_requires_explicit_confirmation_and_rejects_other_output_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(targets, 'ROOT', root), self.assertRaises(BuildError):
                targets.clean(SimpleNamespace(output=None, confirm_clean=False, dry_run=False), Mock())
            with patch.object(targets, 'ROOT', root), self.assertRaises(BuildError):
                targets.clean(SimpleNamespace(output=root / 'src', confirm_clean=True, dry_run=False), Mock())


if __name__ == '__main__':
    unittest.main()


class FinalReleaseArtifacts(unittest.TestCase):
    def test_platform_outputs_share_verified_release_inventory_and_preserve_identity(self):
        import json
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / 'dist' / layout.deployment_output_name('1.0.0-beta.2', 'a'*40)
            for platform, name in (('desktop','desktop.zip'),('service','service.zip'),('linux-native','native.tar.gz'),('docker','docker.tar.gz')):
                source = root / name
                source.write_bytes(('synthetic '+platform).encode())
                expected = artifacts.digest(source)
                target = artifacts.collect(source, output, '1.0.0-beta.2', 'a'*40, platform, expected)
                self.assertEqual(target.parent, output)
                self.assertEqual(artifacts.digest(target), expected)
                self.assertEqual(target.with_name(name+'.sha256').read_text().strip(), expected+'  '+name)
            manifest = json.loads((output/'release-manifest.json').read_text())
            self.assertEqual(len(manifest['artifacts']), 4)
            self.assertEqual(manifest['source_commit'], 'a'*40)
            with self.assertRaisesRegex(ValueError, 'already exists'):
                artifacts.collect(source, output, '1.0.0-beta.2', 'a'*40, platform, expected)
            new = root/'another.zip'; new.write_bytes(b'synthetic')
            with self.assertRaisesRegex(ValueError, 'another version/source'):
                artifacts.collect(new, output, '1.0.0-beta.2', 'b'*40, platform, artifacts.digest(new))
            self.assertFalse((output/new.name).exists())
            with self.assertRaisesRegex(ValueError, 'verified checksum'):
                artifacts.collect(new, output, '1.0.0-beta.2', 'a'*40, platform, '0'*64)
            self.assertFalse((output/new.name).exists())

    def test_reparse_paths_are_rejected_before_collection(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)/'artifact.zip'; source.write_bytes(b'synthetic')
            with patch.object(artifacts, 'is_linked_output', return_value=True):
                with self.assertRaisesRegex(ValueError, 'linked'):
                    artifacts.collect(source, Path(temporary)/'out', '1.0.0', 'a'*40, 'desktop', artifacts.digest(source))


    def test_failed_copy_preserves_previous_artifacts_and_registration_requires_matching_sidecar(self):
        import json
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); output=root/'dist'/'release'
            first=root/'desktop.zip'; first.write_bytes(b'synthetic desktop')
            artifacts.collect(first,output,'1.0.0','a'*40,'desktop',artifacts.digest(first))
            before=(output/'release-manifest.json').read_bytes()
            second=root/'service.zip'; second.write_bytes(b'synthetic service')
            with patch.object(artifacts.shutil,'copyfileobj',side_effect=OSError('synthetic copy failure')):
                with self.assertRaises(OSError):
                    artifacts.collect(second,output,'1.0.0','a'*40,'service',artifacts.digest(second))
            self.assertFalse((output/second.name).exists())
            self.assertEqual((output/'release-manifest.json').read_bytes(),before)
            existing=output/second.name; existing.write_bytes(second.read_bytes())
            sidecar=output/(second.name+'.sha256'); sidecar.write_text('wrong')
            with self.assertRaisesRegex(ValueError,'sidecar'):
                artifacts.register_existing(existing,'1.0.0','a'*40,'service',artifacts.digest(second))
            self.assertEqual((output/'release-manifest.json').read_bytes(),before)
            sidecar.write_text(artifacts.digest(second)+'  '+second.name+'\n')
            artifacts.register_existing(existing,'1.0.0','a'*40,'service',artifacts.digest(second))
            self.assertEqual(len(json.loads((output/'release-manifest.json').read_text())['artifacts']),2)
