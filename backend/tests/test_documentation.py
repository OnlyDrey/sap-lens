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
