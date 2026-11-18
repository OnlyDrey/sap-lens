"""Active repository paths and version mirrors. SAP Lens 1 is archived outside the repository; nothing active may depend on it."""
from pathlib import Path
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def check(root=ROOT):
    for path in ('backend/SapLens.slnx', 'backend/product-version.json', 'backend/scripts/build-release.ps1',
                 'backend/scripts/build-release.sh', 'frontend/playwright.config.ts', 'scripts/browser-server.mjs',
                 'Dockerfile', 'compose.yml'):
        assert (root / path).is_file(), f'Missing canonical path: {path}'
    tracked = subprocess.run(['git', '-C', str(root), 'ls-files', '--', 'legacy'], capture_output=True, text=True, check=False).stdout.split()
    assert not tracked, f'SAP Lens 1 is archived outside the repository; tracked files under legacy/: {tracked[:3]}'
    version = json.loads((root / 'backend/product-version.json').read_text())['version']
    for name in ('package.json', 'package-lock.json'):
        package = json.loads((root / 'frontend' / name).read_text())
        assert package['version'] == version
        if 'packages' in package:
            assert package['packages']['']['version'] == version
    for path in ('frontend/vite.config.ts', 'scripts/product-version.mjs', 'frontend/playwright.config.ts', 'frontend/package.json',
                 'backend/scripts/build-release.ps1', 'backend/scripts/build-release.sh', 'Dockerfile', 'compose.yml', '.github/workflows/validate.yml'):
        assert 'legacy/v1' not in (root / path).read_text(), f'Active tooling depends on the archived SAP Lens 1: {path}'
    for path in sorted((root / 'frontend/tests').glob('*.ts')):
        text = path.read_text()
        assert 'legacy/v1' not in text and 'execFileSync(PYTHON' not in text, f'Browser tests depend on SAP Lens 1 or Python: {path.name}'
    print('Primary .NET layout, no SAP Lens 1 dependency and version mirrors passed.')


if __name__ == '__main__':
    check()
