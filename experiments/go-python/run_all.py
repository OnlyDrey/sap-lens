"""Bounded orchestration of every Phase 0 check. Linux only for the lifecycle tests; Windows execution is reported as NOT EXECUTED, never inferred.

  python run_all.py [--runtime TREE] [--skip-repro]
Exit code 0 only if every executed stage passed. govulncheck is attempted and reported as NOT EXECUTED when its database is unreachable.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOST = ROOT / 'host'


def stage(name, command, cwd, timeout, env=None, allow_unavailable=False):
    started = time.monotonic()
    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout, env={**os.environ, **(env or {})})
        code, tail = completed.returncode, (completed.stdout + completed.stderr)[-400:]
    except subprocess.TimeoutExpired:
        code, tail = -1, f'timeout after {timeout}s'
    except FileNotFoundError as error:
        code, tail = -2, str(error)
    status = 'PASSED' if code == 0 else ('NOT EXECUTED' if allow_unavailable and code != -1 else 'FAILED')
    print(f'{status:13} {name} ({time.monotonic() - started:.1f}s)' + ('' if status == 'PASSED' else f'\n    {tail.strip()[-300:]}'), flush=True)
    return status != 'FAILED'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', default=os.environ.get('POC_RUNTIME', '/tmp/poc-linux'))
    parser.add_argument('--skip-repro', action='store_true')
    args = parser.parse_args()
    go = shutil.which('go') or 'go'
    host_binary = HOST / 'bin' / 'saplens-host'
    results = [
        stage('gofmt (no unformatted files)', ['sh', '-c', 'test -z "$(gofmt -l .)"'], HOST, 60),
        stage('go vet (linux)', [go, 'vet', './...'], HOST, 180),
        stage('go vet (windows/amd64 cross)', [go, 'vet', './...'], HOST, 180, {'GOOS': 'windows', 'GOARCH': 'amd64', 'CGO_ENABLED': '0'}),
        stage('go test -race', [go, 'test', '-race', '-count=1', './...'], HOST, 600),
        stage('go build linux', [go, 'build', '-trimpath', '-o', str(host_binary), '.'], HOST, 180, {'CGO_ENABLED': '0'}),
        stage('go build windows (cross, never executed here)', [go, 'build', '-trimpath', '-o', os.devnull, '.'], HOST, 180, {'GOOS': 'windows', 'GOARCH': 'amd64', 'CGO_ENABLED': '0'}),
        stage('govulncheck', [shutil.which('govulncheck') or str(Path.home() / 'go/bin/govulncheck'), './...'], HOST, 120, allow_unavailable=True),
    ]
    env = {'PYTHONPATH': str(ROOT / 'tests'), 'POC_RUNTIME': args.runtime}
    static = 'test_runtime_static' + ('' if not args.skip_repro else '.LockClosure')
    results.append(stage('python static: lock closure, integrity, reproducibility', [sys.executable, '-m', 'unittest', static], ROOT / 'tests', 900, env))
    results.append(stage('python e2e: lifecycle, health, security boundary, capability bootstrap', [sys.executable, '-m', 'unittest', 'test_lifecycle_security', 'test_capability_bootstrap'], ROOT / 'tests', 600, env))
    results.append(stage('windows harness: parse, logic self-test, non-Windows path, forbidden-operation scan (Linux only)', [sys.executable, '-m', 'unittest', 'test_windows_harness'], ROOT / 'tests', 300, env))
    print('NOT EXECUTED  native Windows smoke, installer acceptance, App Control verification (no Windows host in this environment)')
    return 0 if all(results) else 1


if __name__ == '__main__':
    sys.exit(main())
