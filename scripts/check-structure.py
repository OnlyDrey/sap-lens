"""Active repository paths and version mirrors. SAP Lens 1 is archived outside the repository; nothing active may depend on it."""
from pathlib import Path
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def check(root=ROOT):
    for path in ('backend/AuthLens.slnx', 'backend/product-version.json', 'backend/scripts/build-release.ps1',
                 'backend/scripts/build-release.sh', 'frontend/playwright.config.ts', 'scripts/browser-server.mjs',
                 ):
        assert (root / path).is_file(), f'Missing canonical path: {path}'
    experiments = subprocess.run(['git', '-C', str(root), 'ls-files', '--', 'experiments'], capture_output=True, text=True, check=False).stdout.split()
    assert not experiments, f'Experimental code was consolidated into backend/ and scripts/; tracked files under experiments/: {experiments[:3]}'
    for path in ('Dockerfile', 'compose.yml', '.dockerignore', 'backend/scripts/docker'):
        assert not (root / path).exists(), f'Docker support was removed (no supported use); unexpected {path}'
    # The Server's environment variables are AUTHLENS_*; SAP_LENS_V2_* is named only by the startup warning, its test and the naming
    # register (docs/architecture/VERSIONING.md).
    allowed_v2 = {'backend/src/AuthLens.Api/ServerConfiguration.cs', 'backend/tests/AuthLens.Tests/NetworkTests.cs', 'docs/architecture/VERSIONING.md'}
    v2 = subprocess.run(['git', '-C', str(root), 'grep', '-l', '-i', 'SAP_LENS_V2_', '--', '.', ':!scripts/check-structure.py'],
                        capture_output=True, text=True, check=False).stdout.split()
    assert not set(v2) - allowed_v2, f'The SAP_LENS_V2_ prefix was renamed to AUTHLENS_; found in: {sorted(set(v2) - allowed_v2)}'
    tracked = subprocess.run(['git', '-C', str(root), 'ls-files', '--', 'legacy'], capture_output=True, text=True, check=False).stdout.split()
    assert not tracked, f'SAP Lens 1 is archived outside the repository; tracked files under legacy/: {tracked[:3]}'
    version = json.loads((root / 'backend/product-version.json').read_text(encoding='utf-8'))['version']
    for name in ('package.json', 'package-lock.json'):
        package = json.loads((root / 'frontend' / name).read_text(encoding='utf-8'))
        assert package['version'] == version
        if 'packages' in package:
            assert package['packages']['']['version'] == version
    for path in ('frontend/vite.config.ts', 'scripts/product-version.mjs', 'frontend/playwright.config.ts', 'frontend/package.json',
                 'backend/scripts/build-release.ps1', 'backend/scripts/build-release.sh', '.github/workflows/validate.yml'):
        assert 'legacy/v1' not in (root / path).read_text(encoding='utf-8'), f'Active tooling depends on the archived SAP Lens 1: {path}'
    for path in sorted((root / 'backend/tests').rglob('*.cs')):
        if '/bin/' in path.as_posix() or '/obj/' in path.as_posix():
            continue
        text = path.read_text(encoding='utf-8')
        assert 'legacy/v1' not in text and '"legacy", "v1"' not in text, f'.NET tests read files of the archived SAP Lens 1: {path.name}'
    for path in sorted((root / 'frontend/tests').glob('*.ts')):
        text = path.read_text(encoding='utf-8')
        assert 'legacy/v1' not in text and 'execFileSync(PYTHON' not in text, f'Browser tests depend on SAP Lens 1 or Python: {path.name}'
    print('Primary .NET layout, no SAP Lens 1 dependency and version mirrors passed.')


if __name__ == '__main__':
    check()
