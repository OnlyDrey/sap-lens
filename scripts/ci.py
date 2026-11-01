"""Small CI command/timing adapter; never treats a missing check as a pass."""
import argparse
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ACTIONLINT_VERSION = '1.7.12'
ACTIONLINT_SHA256 = '8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8'
ACTIONLINT_WINDOWS_SHA256 = '6e7241b51e6817ea6a047693d8e6fed13b31819c9a0dd6c5a726e1592d22f6e9'


def timing_path():
    # Runner temp is per job; local reports stay in the ignored build directory.
    return Path(os.environ.get('RUNNER_TEMP', ROOT / 'backend/build')) / 'sap-lens-ci-timings.jsonl'


def run(stage, command):
    started = time.monotonic()
    wall_start = time.time()
    status, count, skipped = 1, None, None
    try:
        with subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding='utf-8', errors='replace') as process:
            for line in process.stdout:
                print(line, end='', flush=True)
                clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', line)
                match = re.search(r'Ran (\d+) tests? in', clean) or re.search(r'(\d+) passed \(', clean)
                if match:
                    count = int(match[1])
                match = re.search(r'skipped=(\d+)', clean)
                if match:
                    skipped = int(match[1])
            status = process.wait()
        return status
    finally:
        record = {'stage': stage, 'started_at': wall_start, 'seconds': round(time.monotonic() - started, 2),
                  'status': 'passed' if status == 0 else 'failed', 'tests': count, 'skipped': skipped}
        try:
            path = timing_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('a', encoding='utf-8') as output:
                output.write(json.dumps(record) + '\n')
        except OSError:
            print('::warning::CI timing unavailable; command result is unchanged.')


def safe(value):
    return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')


def render(steps, records, env):
    mandatory = env.get('CI_REQUIRED', '').split()
    # Optional steps run only when the change needs them (see scripts/run-tests.py changed). A skipped optional step is "not needed", never a pass or a gap;
    # one that ran must have succeeded.
    optional = [key for key in env.get('CI_OPTIONAL', '').split() if steps.get(key, {}).get('outcome') not in {None, 'skipped'}]
    checked = mandatory + optional
    result = 'Passed' if mandatory and all(steps.get(key, {}).get('outcome') == 'success' for key in checked) else 'Incomplete'
    if any(steps.get(key, {}).get('outcome') in {'failure', 'cancelled'} for key in checked):
        result = 'Failed'
    rows = [f"# SAP Lens — {safe(env.get('GITHUB_WORKFLOW', 'Local validation'))}", '',
            f"{safe(env.get('CI_JOB_NAME', env.get('GITHUB_JOB', 'local')))}: **{result}**  ",
            f"Source: {safe(env.get('GITHUB_REF_NAME', 'local'))} @ {safe(env.get('GITHUB_SHA', 'Unavailable'))}", '',
            '| Check | Result | Duration | Tests |', '|---|---|---:|---|']
    timings = {record['stage']: record for record in records}
    for stage in checked + [key for key in env.get('CI_OPTIONAL', '').split() if key not in optional]:
        record = timings.get(stage, {})
        state = steps.get(stage, {}).get('outcome', 'not run')
        if stage not in checked:
            state = 'not needed for this change'
        elapsed = f"{record['seconds']:.2f} s" if 'seconds' in record else 'Not timed (action/setup)'
        tests = str(record['tests']) if record.get('tests') is not None else '—'
        if record.get('skipped'):
            tests += f"; {record['skipped']} skipped"
        rows.append(f'| {safe(stage)} | {safe(state)} | {elapsed} | {tests} |')
    rows += ['', 'Durations measure commands; checkout, setup, cache actions and runner cleanup are additional.',
             'Skipped/missing mandatory checks are never counted as passed. See job logs for warnings.',
             'Known upstream artifact DEP0005 and existing development advisories: docs/development/DEPENDENCY_MAINTENANCE.md.']
    starts = [record['started_at'] for record in records if isinstance(record.get('started_at'), (int, float))]
    if starts:
        rows += [f'Elapsed since first measured command: {max(0, time.time() - min(starts)):.2f} s (initial setup excluded).']
    cache_states = []
    for key in ('setup_node', 'setup_python', 'browser_cache'):
        if key in steps:
            hit = steps[key].get('outputs', {}).get('cache-hit')
            state = 'hit' if hit in ('true', True) else 'miss' if hit in ('false', False) else 'not reported; see action log'
            cache_states.append(f'{key}: {state}')
    if cache_states:
        rows += ['Download caches — ' + '; '.join(cache_states) + '.']
    return '\n'.join(rows) + '\n'


def summary():
    path = timing_path()
    records = []
    if path.is_file():
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                record = json.loads(line)
                if (isinstance(record.get('seconds'), (int, float)) and math.isfinite(record['seconds']) and
                        record['seconds'] >= 0 and isinstance(record.get('stage'), str)):
                    records.append(record)
            except (ValueError, AttributeError):
                continue
    text = render(json.loads(os.environ.get('CI_STEPS', '{}')), records, os.environ)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        Path(os.environ['GITHUB_STEP_SUMMARY']).write_text(text, encoding='utf-8')
    else:
        print(text)


def lint():
    documentation = subprocess.call([sys.executable, str(ROOT / 'scripts/check-docs.py')], cwd=ROOT)
    if documentation:
        return documentation
    system = platform.system()
    if system not in {'Linux', 'Windows'} or platform.machine() not in {'x86_64', 'AMD64'}:
        raise RuntimeError('Pinned actionlint installer requires Windows or Linux x64.')
    windows = system == 'Windows'
    package = 'windows_amd64.zip' if windows else 'linux_amd64.tar.gz'
    expected = ACTIONLINT_WINDOWS_SHA256 if windows else ACTIONLINT_SHA256
    url = f'https://github.com/rhysd/actionlint/releases/download/v{ACTIONLINT_VERSION}/actionlint_{ACTIONLINT_VERSION}_{package}'
    # Cache only the checksum-verified download, never trust a mutable executable.
    directory = Path(os.environ.get('RUNNER_TEMP', ROOT / 'backend/build'))
    directory.mkdir(parents=True, exist_ok=True)
    cached = directory / f'actionlint-{ACTIONLINT_VERSION}-{package}'
    if cached.is_symlink():
        raise RuntimeError('actionlint cache must not be linked')
    data = cached.read_bytes() if cached.is_file() else b''
    if hashlib.sha256(data).hexdigest() != expected:
        data = urllib.request.urlopen(url, timeout=60).read()
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError('actionlint checksum mismatch')
        cached.write_bytes(data)
    tool = directory / (f'actionlint-{ACTIONLINT_VERSION}' + ('.exe' if windows else ''))
    if tool.is_symlink():
        raise RuntimeError('actionlint destination must not be linked')
    if windows:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            executable = archive.read('actionlint.exe')
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
            executable = archive.extractfile('actionlint').read()
    tool.write_bytes(executable)
    tool.chmod(0o700)
    return subprocess.call([str(tool)], cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['run', 'summary', 'lint'])
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.operation == 'run':
        stage, *command = args.arguments
        if command[:1] == ['--']:
            command = command[1:]
        return run(stage, command)
    if args.operation == 'lint':
        return lint()
    summary()
    return 0


if __name__ == '__main__':
    sys.exit(main())
