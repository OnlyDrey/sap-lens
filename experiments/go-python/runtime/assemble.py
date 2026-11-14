"""Assemble an isolated runtime tree: bundled CPython + hash-verified wheels + SAP Lens backend + production frontend build + PoC entry.

  python assemble.py --platform linux   --out /tmp/poc-linux   [--archive /tmp/poc-linux.tar.gz]
  python assemble.py --platform windows --out /tmp/poc-windows            (assembled on Linux; EXPERIMENTAL, never executed here)

Nothing is installed or executed from the downloaded wheels: they are unpacked. The tree contains manifest.json with a hash of every file.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from common import (CACHE, LOCK, REPOSITORY, ROOT, download, extract_tar_gz, extract_wheel, normalise_modes, sha256_file, tree_manifest,
                    write_deterministic_archive)

PLATFORM_TAGS = {'linux': ['manylinux_2_28_x86_64', 'manylinux_2_17_x86_64', 'manylinux2014_x86_64'], 'windows': ['win_amd64']}
SKIP_DIRECTORIES = {'__pycache__', 'tests', 'build'}
# Stdlib parts the headless backend never imports (GUI toolkit, test suites, packaging tools). Optional (--prune); the result is checked by the e2e test.
PRUNE = {
    'linux': ['lib/python3.12/test', 'lib/python3.12/idlelib', 'lib/python3.12/tkinter', 'lib/python3.12/turtledemo', 'lib/python3.12/turtle.py', 'lib/python3.12/lib2to3',
              'lib/python3.12/ensurepip', 'lib/python3.12/pydoc_data', 'lib/python3.12/site-packages/pip', 'lib/python3.12/site-packages/setuptools',
              'lib/python3.12/site-packages/pkg_resources', 'lib/python3.12/lib-dynload/_tkinter.cpython-312-x86_64-linux-gnu.so', 'lib/tcl8.6', 'lib/tk8.6', 'lib/tcl8',
              'lib/itcl4.2.4', 'lib/thread2.8.9', 'lib/libtcl8.6.so', 'lib/libtk8.6.so', 'bin/idle3', 'bin/idle3.12', 'bin/2to3', 'bin/2to3-3.12', 'bin/pydoc3', 'bin/pydoc3.12',
              'bin/pip', 'bin/pip3', 'bin/pip3.12'],
    'windows': ['Lib/test', 'Lib/idlelib', 'Lib/tkinter', 'Lib/turtledemo', 'Lib/turtle.py', 'Lib/lib2to3', 'Lib/ensurepip', 'Lib/pydoc_data', 'Lib/site-packages/pip',
                'Lib/site-packages/setuptools', 'Lib/site-packages/pkg_resources', 'DLLs/_tkinter.pyd', 'DLLs/tcl86t.dll', 'DLLs/tk86t.dll', 'tcl', 'Scripts'],
}


def prune(tree, platform):
    removed = 0
    for relative in PRUNE[platform]:
        target = tree / 'python' / relative
        if target.is_dir() and not target.is_symlink():
            removed += sum(f.stat().st_size for f in target.rglob('*') if f.is_file())
            shutil.rmtree(target)
        elif target.exists() or target.is_symlink():
            removed += target.stat().st_size if target.is_file() else 0
            target.unlink()
    return removed


def load_lock():
    lock = json.loads(LOCK.read_text(encoding='utf-8'))
    if lock.get('schema') != 1:
        raise SystemExit('Unsupported lock schema')
    return lock


def interpreter(lock, platform):
    entry = lock['python']['archives'][platform]
    return download(entry['url'], CACHE / entry['file'], entry['sha256'], entry['size'])


def fetch_wheels(lock, platform):
    """pip only downloads, with --require-hashes and --no-deps: a hash that differs from the lock fails the assembly."""
    directory = CACHE / f'wheels-{platform}'
    directory.mkdir(parents=True, exist_ok=True)
    wanted = lock['wheels'][platform]
    with tempfile.TemporaryDirectory() as temporary:
        required = Path(temporary) / 'requirements.txt'
        required.write_text(''.join(f"{w['name']}=={w['version']} --hash=sha256:{w['sha256']}\n" for w in wanted), encoding='utf-8')
        platforms = [flag for tag in PLATFORM_TAGS[platform] for flag in ('--platform', tag)]
        subprocess.run([sys.executable, '-m', 'pip', 'download', '--quiet', '--no-deps', '--require-hashes', '--only-binary=:all:', '--python-version', '3.12',
                        '--implementation', 'cp', '--abi', 'cp312', *platforms, '--dest', str(directory), '-r', str(required)], check=True)
    result = []
    for wheel in wanted:
        path = directory / wheel['file']
        if not path.is_file() or sha256_file(path) != wheel['sha256']:
            raise SystemExit(f"Wheel {wheel['file']} is missing or does not match the lock")
        result.append(path)
    return result


def copy_application(destination):
    backend = REPOSITORY / 'backend'
    target = destination / 'backend'
    for source in sorted(backend.rglob('*')):
        relative = source.relative_to(backend)
        if any(part in SKIP_DIRECTORIES for part in relative.parts) or not source.is_file():
            continue
        if relative.parts[0] not in ('routers', 'resources') and len(relative.parts) > 1:
            continue
        if relative.suffix not in ('.py', '.json', '.xlsx', '.csv', '.txt', '.md', '.png', '.ico') and relative.parts[0] != 'resources':
            continue
        (target / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target / relative)
    shutil.copyfile(ROOT / 'backend' / 'poc_backend.py', target / 'poc_backend.py')
    dist = REPOSITORY / 'frontend' / 'dist'
    if not (dist / 'index.html').is_file():
        raise SystemExit('Build the production frontend first (frontend/dist is missing).')
    shutil.copytree(dist, destination / 'frontend' / 'dist')


def compile_bytecode(python, tree, scope):
    """Deterministic bytecode: hash-based pyc files with a fixed, prefix-independent source path. Integrity is the manifest's job."""
    for path in scope:
        subprocess.run([str(python), '-I', '-m', 'compileall', '-q', '-f', '--invalidation-mode', 'unchecked-hash', '-s', str(tree), '-p', '/runtime', str(path)], check=True,
                       env={**os.environ, 'PYTHONHASHSEED': '0', 'PYTHONDONTWRITEBYTECODE': '1'})
    # hash seed: set/frozenset constants; -f and no implicit pyc: modules compileall itself imports must not keep timestamp-based pyc files


def assemble(platform, out, source_commit, archive=None, prune_stdlib=False):
    started = time.monotonic()
    out = Path(out).resolve()
    if out.exists():
        raise SystemExit(f'{out} exists; refusing to overwrite')
    lock = load_lock()
    python_archive = interpreter(lock, platform)
    wheels = fetch_wheels(lock, platform)
    out.mkdir(parents=True)
    extract_tar_gz(python_archive, out)
    site = out / 'python' / ('lib/python3.12/site-packages' if platform == 'linux' else 'Lib/site-packages')
    site.mkdir(parents=True, exist_ok=True)
    for wheel in wheels:
        extract_wheel(wheel, site)
    if prune_stdlib:
        prune(out, platform)
    app = out / 'app'
    copy_application(app)
    relative = '../../../../app/backend' if platform == 'linux' else '../../../app/backend'
    (site / 'sap_lens_poc.pth').write_text(relative + '\n', encoding='utf-8')
    if platform == 'linux':
        compiler = out / 'python' / 'bin' / 'python3'
    else:  # same 3.12 bytecode format: compile with the Linux interpreter of the same release
        helper = Path(tempfile.mkdtemp(prefix='poc-compile-'))
        extract_tar_gz(interpreter(lock, 'linux'), helper)
        compiler = helper / 'python' / 'bin' / 'python3'
    compile_bytecode(compiler, out, [app / 'backend', site, out / 'python' / ('lib' if platform == 'linux' else 'Lib')])
    if platform == 'windows':
        shutil.rmtree(helper, ignore_errors=True)
    normalise_modes(out)
    inputs = {'platform': platform, 'python': lock['python']['version'], 'python_archive_sha256': lock['python']['archives'][platform]['sha256'],
              'wheels': [{'file': w['file'], 'sha256': w['sha256']} for w in lock['wheels'][platform]], 'lock_sha256': sha256_file(LOCK),
              'source_commit': source_commit, 'pruned': bool(prune_stdlib), 'builder_sha256': sha256_file(Path(__file__))}
    manifest = tree_manifest(out, inputs)
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n', encoding='utf-8')
    archive_sha = write_deterministic_archive(out, archive) if archive else None
    seconds = round(time.monotonic() - started, 2)
    summary = {'platform': platform, 'root_sha256': manifest['root_sha256'], 'files': manifest['file_count'], 'bytes': manifest['bytes'],
               'wheels': len(wheels), 'seconds': seconds, 'archive_sha256': archive_sha, 'archive_bytes': Path(archive).stat().st_size if archive else None}
    print(json.dumps(summary))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--platform', choices=['linux', 'windows'], required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--archive')
    parser.add_argument('--prune', action='store_true', help='remove stdlib parts a headless backend does not need (GUI toolkit, test suites, pip)')
    parser.add_argument('--source-commit', default=subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPOSITORY, capture_output=True, text=True).stdout.strip())
    arguments = parser.parse_args()
    assemble(arguments.platform, arguments.out, arguments.source_commit, arguments.archive, arguments.prune)


if __name__ == '__main__':
    main()
