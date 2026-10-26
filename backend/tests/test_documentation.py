"""Offline documentation integrity; no external URL fetching or file changes."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('documentation_rules',ROOT/'scripts/check-docs.py')
rules=importlib.util.module_from_spec(spec);spec.loader.exec_module(rules)


class DocumentationTests(unittest.TestCase):
    def test_repository_documentation_links_and_assets_exist(self):
        paths=[ROOT/'README.md',ROOT/'AGENTS.md',ROOT/'LICENSE.md',*sorted((ROOT/'docs').rglob('*.md')),*sorted((ROOT/'examples').rglob('*.md'))]
        self.assertEqual(rules.check(paths),[])

    def test_missing_files_anchors_images_and_escape_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);doc=root/'README.md'
            doc.write_text('# Example\n[missing](missing.md)\n[anchor](#absent)\n![image](missing.png)\n[escape](../outside.md)\n')
            self.assertEqual(len(rules.check([doc],root)),4)

    def test_headings_explicit_ids_duplicate_anchors_and_code_examples(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);doc=root/'README.md';image=root/'image.png';image.write_bytes(b'synthetic')
            doc.write_text('# Example\n# Example\n<a id="custom"></a>\n[one](#example) [two](#example-1) [id](#custom)\n![image](image.png)\n[external](https://example.invalid/not-fetched)\n```md\n[example only](absent.md)\n```\n')
            self.assertEqual(rules.check([doc],root),[])

    def test_packaged_operating_guides_do_not_require_a_source_checkout(self):
        package_spec=importlib.util.spec_from_file_location('documentation_packaging',ROOT/'scripts/deployment-package.py')
        packages=importlib.util.module_from_spec(package_spec);package_spec.loader.exec_module(packages)
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'docs';source.mkdir();target=root/'package';target.mkdir()
            document=source/'GUIDE.md';document.write_text('# Guide\n[security](DEPLOYMENT_SECURITY.md) [developer reference](OTHER.md) [section](#guide)\n')
            (target/'SECURITY.md').write_text('# Security\n')
            with patch.object(packages,'ROOT',root):packages.package_document(document,target/'README.md')
            self.assertEqual(rules.check(list(target.glob('*.md')),target),[])
            self.assertIn('(SECURITY.md)',(target/'README.md').read_text())
            self.assertIn('developer reference (repository documentation)',(target/'README.md').read_text())

    def test_current_operating_guides_are_self_contained_when_packaged(self):
        package_spec=importlib.util.spec_from_file_location('operating_documentation_packaging',ROOT/'scripts/deployment-package.py')
        packages=importlib.util.module_from_spec(package_spec);package_spec.loader.exec_module(packages)
        for guide in ('WINDOWS_DESKTOP','WINDOWS_SERVICE','LINUX_DOCKER','LINUX_NATIVE'):
            with self.subTest(guide=guide), tempfile.TemporaryDirectory() as temporary:
                target=Path(temporary)
                packages.package_document(ROOT/'docs/deployment/SECURITY.md',target/'SECURITY.md')
                packages.package_document(ROOT/f'docs/deployment/{guide}.md',target/'README.md')
                self.assertEqual(rules.check(list(target.glob('*.md')),target),[])
                if guide!='WINDOWS_DESKTOP':
                    self.assertIn('(SECURITY.md)',(target/'README.md').read_text())

    def test_native_bundle_documentation_members_survive_source_migration(self):
        from unittest.mock import patch
        package_spec=importlib.util.spec_from_file_location('native_documentation_packaging',ROOT/'scripts/deployment-package.py')
        packages=importlib.util.module_from_spec(package_spec);package_spec.loader.exec_module(packages)
        with tempfile.TemporaryDirectory() as temporary:
            target=Path(temporary)
            # Backend CI runs before the frontend build: only documentation is under test.
            with patch.object(packages,'identity',return_value={'version':'0.1.0','source_commit':'synthetic'}), patch.object(packages.shutil,'copytree'):
                packages.copy_source(target)
            self.assertEqual({p.name for p in target.glob('*.md')},{
                'LICENSE.md','README.md','SECURITY.md','DEPLOYMENT_LINUX_NATIVE.md',
                'DEPLOYMENT_SECURITY.md','DEPLOYMENT_PACKAGES.md','PACKAGING_VALIDATION.md',
                'LOCAL_BUILD_VALIDATION.md','INSTALLATION_LIFECYCLE_VALIDATION.md'})
            self.assertEqual(rules.check(list(target.glob('*.md')),target),[])
            self.assertIn('# Linux native/systemd',(target/'README.md').read_text())
