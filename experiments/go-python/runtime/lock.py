"""Create runtime/lock.json: pinned interpreter archives and per-platform hashed wheel closures for backend/requirements.txt.

Needs network access and pip. Run once per dependency change; assemble.py then works only from the lock (hash-verified).
  python experiments/go-python/runtime/lock.py
"""
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from common import CACHE, LOCK, REPOSITORY, sha256_file

PBS_TAG = '20250902'
PBS_PYTHON = '3.12.11'
ARCHIVES = {
    'linux': f'cpython-{PBS_PYTHON}+{PBS_TAG}-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz',
    'windows': f'cpython-{PBS_PYTHON}+{PBS_TAG}-x86_64-pc-windows-msvc-install_only_stripped.tar.gz',
}
PLATFORM_FLAGS = {
    'linux': ['--platform', 'manylinux_2_28_x86_64', '--platform', 'manylinux_2_17_x86_64', '--platform', 'manylinux2014_x86_64'],
    'windows': ['--platform', 'win_amd64'],
}


def pinned_requirements():
    lines = []
    for line in (REPOSITORY / 'backend/requirements.txt').read_text(encoding='utf-8').splitlines():
        line = line.split('#', 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def interpreter_entries():
    base = f'https://github.com/astral-sh/python-build-standalone/releases/download/{PBS_TAG}/'
    sums = urllib.request.urlopen(base + 'SHA256SUMS', timeout=60).read().decode()
    entries = {}
    for platform, name in ARCHIVES.items():
        match = next((m for m in re.finditer(r'([0-9a-f]{64})\s+(\S+)', sums) if m.group(2) == name), None)
        if not match:
            raise SystemExit(f'{name} is not listed in SHA256SUMS of {PBS_TAG}')
        target = CACHE / name
        from common import download
        download(base + name.replace('+', '%2B'), target, match.group(1))
        entries[platform] = {'file': name, 'url': base + name.replace('+', '%2B'), 'sha256': match.group(1), 'size': target.stat().st_size,
                             'source_of_hash': f'release {PBS_TAG} SHA256SUMS over TLS (not an independent signature)'}
    return entries


def wheel_entries(platform, requirements):
    with tempfile.TemporaryDirectory() as directory:
        required = Path(directory) / 'requirements.txt'
        required.write_text('\n'.join(requirements) + '\n', encoding='utf-8')
        command = [sys.executable, '-m', 'pip', 'download', '--quiet', '--only-binary=:all:', '--python-version', '3.12', '--implementation', 'cp', '--abi', 'cp312',
                   *PLATFORM_FLAGS[platform], '--dest', directory, '-r', str(required)]
        subprocess.run(command, check=True)
        wheels = []
        for wheel in sorted(Path(directory).glob('*.whl')):
            name, version = wheel.name.split('-')[:2]
            wheels.append({'name': re.sub(r'[-_.]+', '-', name).lower(), 'version': version, 'file': wheel.name, 'sha256': sha256_file(wheel), 'size': wheel.stat().st_size})
    return wheels


def main():
    requirements = pinned_requirements()
    lock = {'schema': 1, 'python': {'version': PBS_PYTHON, 'archives': interpreter_entries()}, 'requirements': requirements, 'wheels': {}}
    for platform in ('linux', 'windows'):
        lock['wheels'][platform] = wheel_entries(platform, requirements)
        print(platform, len(lock['wheels'][platform]), 'wheels')
    LOCK.write_text(json.dumps(lock, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print('wrote', LOCK)


if __name__ == '__main__':
    main()
