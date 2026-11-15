"""Build the Windows validation bundle on Linux (EXPERIMENTAL; nothing is executed). Output: DIR/{saplens-host.exe, runtime.tar.gz, scripts/, SHA256SUMS.txt}. The printed sums_sha256 is the trusted checksum Run-Phase1.ps1 requires; it must reach the
Windows machine through a channel other than the bundle itself.

  python make_bundle.py --out DIR
The Windows tree is assembled from hash-locked inputs by runtime/assemble.py; the host is cross-compiled with CGO_ENABLED=0. Copy DIR to the Windows test machine,
verify SHA256SUMS.txt there, extract runtime.tar.gz with the built-in tar.exe, then follow docs/experiments/go-python/WINDOWS_VALIDATION.md.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
from common import sha256_file  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--prune', action='store_true')
    args = parser.parse_args()
    out = Path(args.out).resolve()
    if out.exists():
        raise SystemExit(f'{out} exists; refusing to overwrite')
    out.mkdir(parents=True)
    env = {**os.environ, 'GOOS': 'windows', 'GOARCH': 'amd64', 'CGO_ENABLED': '0'}
    subprocess.run(['go', 'build', '-trimpath', '-buildvcs=false', '-ldflags=-s -w -buildid=', '-o', str(out / 'saplens-host.exe'), '.'], cwd=ROOT / 'host', env=env, check=True)
    tree = out.parent / (out.name + '-tree')
    command = [sys.executable, str(ROOT / 'runtime' / 'assemble.py'), '--platform', 'windows', '--out', str(tree), '--archive', str(out / 'runtime.tar.gz')] + (['--prune'] if args.prune else [])
    summary = json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip().splitlines()[-1])
    shutil.rmtree(tree)
    shutil.copytree(ROOT / 'windows', out / 'scripts', ignore=shutil.ignore_patterns('make_bundle.py', 'pe_inventory.py', '__pycache__'))
    lines = [f'{sha256_file(path)}  {path.relative_to(out).as_posix()}' for path in sorted(out.rglob('*')) if path.is_file()]
    (out / 'SHA256SUMS.txt').write_text('\n'.join(lines) + '\n', encoding='ascii')
    print(json.dumps({'bundle': str(out), 'sums_sha256': sha256_file(out / 'SHA256SUMS.txt'), 'runtime_root_sha256': summary['root_sha256'], 'files': len(lines),
                      'host_sha256': sha256_file(out / 'saplens-host.exe'), 'archive_sha256': summary['archive_sha256']}))
    print('\nTrusted checksum for the Windows run (transfer it SEPARATELY from the bundle, for example read it out or send it by another channel):', file=sys.stderr)
    print('  ' + sha256_file(out / 'SHA256SUMS.txt'), file=sys.stderr)


if __name__ == '__main__':
    main()
