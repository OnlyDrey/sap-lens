"""Active repository paths and version mirrors; legacy runtime stays archived."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def check(root=ROOT):
    for path in ('backend/SapLens.slnx', 'backend/product-version.json', 'backend/scripts/build-release.ps1',
                 'backend/scripts/build-release.sh', 'frontend/playwright.config.ts', 'scripts/browser-server.mjs',
                 'legacy/v1/backend/main.py', 'legacy/v1/Dockerfile', 'Dockerfile', 'compose.yml'):
        assert (root / path).is_file(), f'Missing canonical path: {path}'
    version = json.loads((root / 'backend/product-version.json').read_text())['version']
    for name in ('package.json', 'package-lock.json'):
        package = json.loads((root / 'frontend' / name).read_text())
        assert package['version'] == version
        if 'packages' in package:
            assert package['packages']['']['version'] == version
    for path in ('frontend/vite.config.ts', 'scripts/product-version.mjs', 'frontend/playwright.config.ts'):
        assert 'legacy/v1' not in (root / path).read_text(), f'Active runtime depends on v1: {path}'
    print('Primary .NET layout, archived v1 runtime and version mirrors passed.')


if __name__ == '__main__':
    check()
