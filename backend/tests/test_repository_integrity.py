"""Offline documentation and build-input integrity without network dependencies."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]


class RepositoryIntegrityTests(unittest.TestCase):
    def test_markdown_relative_links_resolve(self):
        documents = [ROOT / 'README.md', ROOT / 'AGENTS.md', *(ROOT / 'docs').rglob('*.md'), *(ROOT / 'examples').glob('*.md')]
        for document in documents:
            for target in re.findall(r'\]\(([^)]+)\)', document.read_text(encoding='utf-8')):
                target = target.strip().strip('<>')
                if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', target) or target.startswith('#'):
                    continue
                relative = target.split('#', 1)[0]
                self.assertTrue((document.parent / relative).exists(), f'{document.relative_to(ROOT)}: {relative}')

    def test_requirement_includes_are_available_and_packaging_is_build_only(self):
        for file in (ROOT / 'backend').glob('requirements*.txt'):
            for line in file.read_text(encoding='utf-8').splitlines():
                if line.startswith('-r '):
                    self.assertTrue((file.parent / line[3:]).is_file(), file.name)
        self.assertNotIn('pyinstaller', (ROOT / 'backend/requirements-desktop.txt').read_text(encoding='utf-8').lower())
        self.assertIn('pyinstaller==', (ROOT / 'backend/requirements-build.txt').read_text(encoding='utf-8').lower())

    def test_documented_product_asset_links_exist(self):
        self.assertTrue((ROOT / 'assets/sap-lens.png').is_file())
        self.assertTrue((ROOT / 'assets/sap-lens.ico').is_file())
        for target in re.findall(r'(?:src|href)="(/[^"#]+)"', (ROOT / 'frontend/index.html').read_text(encoding='utf-8')):
            if target.startswith('/src/'):
                self.assertTrue((ROOT / 'frontend' / target.lstrip('/')).is_file())
            else:
                self.assertTrue((ROOT / 'frontend/public' / target.lstrip('/')).is_file())
