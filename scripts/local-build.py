"""Offline local-build identity, freshness receipt and verified distribution export.

No GitHub API, tags or publication. Receipts guard accidental stale inputs, not
malicious changes by the same OS user. All paths stay in ignored build folders.
"""
import argparse
import hashlib
import importlib.util
import importlib.metadata
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
import version

REQUIRED = ['Frontend', 'Python', 'Audit', 'Backend', 'Browser', 'Repository']
MAX_AGE = 24 * 60 * 60


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError('Build output must not be linked.')
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def git(*args, root=ROOT):
    return subprocess.check_output(['git', *args], cwd=root).decode('utf-8').strip()


def identity(requested, root=ROOT):
    return version.make_local_package_info(requested, git('rev-parse', 'HEAD', root=root))


def clean(root=ROOT):
    if git('status', '--porcelain', '--untracked-files=normal', root=root):
        raise ValueError('Packaging requires a clean checkout. Commit source changes, then Validate again.')


def tree_digest(directory, allow_interpreter_links=False):
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('A required validated input directory is missing or linked.')
    result = hashlib.sha256()
    count = 0
    for path in sorted(directory.rglob('*')):
        relative = path.relative_to(directory)
        if '__pycache__' in relative.parts or path.suffix in {'.pyc', '.pyo'}:
            continue
        if path.is_symlink():
            if allow_interpreter_links and sys.platform == 'linux':
                interpreter = (relative.as_posix() in {'bin/python', 'bin/python3', 'bin/python3.12'}
                               and path.resolve() == Path(sys.executable).resolve() and path.is_file())
                library = relative.as_posix() == 'lib64' and path.resolve() == (directory / 'lib').resolve()
                if interpreter or library:
                    result.update(relative.as_posix().encode('utf-8') + b'\0')
                    result.update(bytes.fromhex(digest(path.resolve())) if interpreter else b'venv-lib-alias')
                    count += 1
                    continue
            raise ValueError('Validated inputs must not contain symbolic links.')
        if path.is_file():
            result.update(relative.as_posix().encode('utf-8') + b'\0')
            result.update(bytes.fromhex(digest(path)))
            count += 1
    if not count:
        raise ValueError('A required validated input directory is empty.')
    return result.hexdigest()


def check_packaging_tools(root=ROOT):
    pins = {}
    for name in ['requirements-build.txt', 'requirements-desktop.txt']:
        for line in (root / 'backend' / name).read_text(encoding='utf-8').splitlines():
            match = re.fullmatch(r'(pyinstaller|pywebview)==([0-9.]+)', line)
            if match:
                pins[match[1]] = match[2]
    if set(pins) != {'pyinstaller', 'pywebview'}:
        raise ValueError('Packaging tools require explicit pins in project requirements.')
    for name, expected in pins.items():
        if importlib.metadata.version(name) != expected:
            raise ValueError('Packaging tools differ from project pins. Run Validate again.')
    print('Packaging tools match project requirements: ' + ', '.join(f'{name} {pin}' for name, pin in pins.items()))


def tool_versions():
    return {'python': sys.version.split()[0],
            'node': subprocess.check_output(['node', '--version']).decode('ascii').strip()}


def inputs(root=ROOT, allow_interpreter_links=False):
    result = hashlib.sha256()
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).split(b'\0')
    for name in sorted(name for name in names if name):
        path = root / os.fsdecode(name)
        if not path.is_file() or path.is_symlink():
            raise ValueError('Tracked build input is missing or linked.')
        result.update(name + b'\0' + bytes.fromhex(digest(path)))
    return {'source': result.hexdigest(),
            'tools': tool_versions(),
            'frontend': tree_digest(root / 'frontend/dist'),
            'python': tree_digest(root / 'backend/build/python-env', allow_interpreter_links)}


def receipt_path(root=ROOT):
    return root / 'backend/build/local-validation.json'


def record(requested, stages, root=ROOT):
    if stages != REQUIRED:
        raise ValueError('Cannot record incomplete validation.')
    value = {'schema': 1, 'identity': identity(requested, root), 'inputs': inputs(root),
             'validated_at': time.time(), 'stages': stages}
    write_json(receipt_path(root), value)
    return value


def check(requested, root=ROOT, now=None):
    clean(root)
    path = receipt_path(root)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
        raise ValueError('No safe validation receipt. Run -Mode Validate with the same -Version first.')
    value = json.loads(path.read_text(encoding='utf-8'))
    age = (time.time() if now is None else now) - value.get('validated_at', 0)
    if (value.get('schema') != 1 or value.get('stages') != REQUIRED or
            value.get('identity') != identity(requested, root) or not 0 <= age <= MAX_AGE or
            value.get('inputs') != inputs(root)):
        raise ValueError('Validation is stale or inputs/version changed. Run -Mode Validate again (receipt lasts 24 hours).')
    return value


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f'scripts/{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def export(requested, output, root=ROOT):
    """Create and inspect the exact ZIP, then run the canonical EXE verifier again."""
    info = identity(requested, root)
    timings = [json.loads(line.lstrip('\ufeff')) for line in (root / 'backend/build/timings.jsonl').read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    for stage in ['PyInstaller packaging (clean)', 'Package verification and checksum', 'EXE smoke testing']:
        matches = [row for row in timings if row.get('stage') == stage]
        if not matches or matches[-1].get('status') != 'passed':
            raise ValueError('Canonical package verification and native smoke tests must pass before export.')
    approved = json.loads((root / 'backend/build/package-verification.json').read_text(encoding='utf-8-sig'))
    exe = root / 'backend/dist/SAP-Lens.exe'
    checksum = root / 'backend/dist/SAP-Lens.exe.sha256'
    if digest(exe) != approved['exe_sha256']:
        raise ValueError('Executable changed after package verification.')
    output = output.resolve()
    allowed = (root / 'dist/local').resolve()
    if not output.is_relative_to(allowed) or output == allowed:
        raise ValueError('Local distribution must be below dist/local/.')
    output.mkdir(parents=True, exist_ok=False)
    archive_dir = output / 'archive'
    archive_dir.mkdir()
    archive = archive_dir / f"SAP-Lens-Windows-x64-{info['version']}.zip"
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in (exe, checksum):
            bundle.write(path, path.name)
    zip_sha = digest(archive)
    extracted = output / 'application'
    load_script('verify-artifact-zip').verify(archive_dir, extracted, zip_sha)
    report = output / 'verification-report.json'
    subprocess.run([sys.executable, str(root / 'scripts/verify-windows-package.py'),
                    '--distribution', str(extracted), '--expected-sha256', approved['exe_sha256'],
                    '--report', str(report)], cwd=root, check=True)
    archive.with_suffix('.zip.sha256').write_text(f'{zip_sha}  {archive.name}\n', encoding='ascii')
    manifest = {'schema': 1, 'identity': info, 'official_release': False, 'signing': 'disabled',
                'verification': 'passed', 'native_smoke_tests': 'passed',
                'validation': check(requested, root), 'exe_sha256': approved['exe_sha256'],
                'zip_sha256': zip_sha, 'exe_bytes': exe.stat().st_size,
                'zip_bytes': archive.stat().st_size, 'zip_members': ['SAP-Lens.exe', 'SAP-Lens.exe.sha256']}
    write_json(output / 'build-manifest.json', manifest)
    # Mark completion only after every check succeeds; failed exports retain logs, no manifest.
    print(f"Local application: {extracted / 'SAP-Lens.exe'}")
    print(f"Verified ZIP SHA-256: {zip_sha}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['identity', 'clean', 'invalidate', 'record', 'check', 'export', 'tools'])
    parser.add_argument('--version', default='0.1.0')
    parser.add_argument('--stages', nargs='*', default=[])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        if args.operation == 'identity':
            info = identity(args.version)
            write_json(ROOT / 'backend/build/build-version.json', info)
            print(info['version'])
        elif args.operation == 'tools':
            check_packaging_tools()
        elif args.operation == 'clean':
            clean()
        elif args.operation == 'invalidate':
            receipt_path().unlink(missing_ok=True)
        elif args.operation == 'record':
            record(args.version, args.stages)
        elif args.operation == 'check':
            check(args.version)
            print('Validated inputs match the current clean commit, version and 24-hour receipt.')
        elif args.operation == 'export':
            if not args.output:
                parser.error('export requires --output')
            export(args.version, args.output)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        # Do not dump filesystem exception messages or rejected archive content.
        message = str(error) if isinstance(error, ValueError) else type(error).__name__
        parser.exit(1, f'Local build {args.operation} failed: {message}\n')


if __name__ == '__main__':
    main()
