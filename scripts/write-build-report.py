"""One best-effort Actions report; verification failures remain blocking elsewhere."""
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import math
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]
STAGES = {
    'Environment': ['Python environment creation'],
    'Frontend': ['npm installation', 'Frontend compilation'],
    'Python dependencies': ['Python dependency installation'],
    'Security audit': ['Audit tool provisioning', 'Python vulnerability audit', 'Production JavaScript audit'],
    'Backend tests': ['Backend tests'],
    'Browser tests': ['Playwright installation', 'Playwright tests'],
    'Packaging': ['PyInstaller packaging (clean)', 'PyInstaller packaging (same-job incremental)'],
    'Verification': ['Package verification and checksum'],
    'Smoke tests': ['EXE smoke testing'],
    'Artifact upload': [],
    'Artifact round-trip verification': ['Downloaded artifact verification'],
}


def safe(value):
    return str(value).replace('|', '\\|').replace('\r', ' ').replace('\n', ' ').replace('<', '&lt;').replace('>', '&gt;')


def seconds(value):
    return f'{value:.2f} s' if isinstance(value, (int, float)) else 'Unavailable'


def read_timings(path):
    records = []
    if path.is_file():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            try:
                record = json.loads(line)
                if record['status'] not in {'passed', 'failed'} or not math.isfinite(float(record['seconds'])) or float(record['seconds']) < 0:
                    raise ValueError()
                records.append(record)
            except (KeyError, TypeError, ValueError):
                # Retain completed records if a process was interrupted while appending.
                continue
    return records


def duration(step):
    try:
        return max(0, (datetime.fromisoformat(step['completed_at'].replace('Z', '+00:00')) -
                       datetime.fromisoformat(step['started_at'].replace('Z', '+00:00'))).total_seconds())
    except (KeyError, AttributeError, TypeError, ValueError):
        return None


def render(records, package, jobs, env, now=None):
    now = now or datetime.now(timezone.utc)
    candidates = [job for job in jobs if job.get('name') == env.get('BUILD_JOB_NAME', env.get('GITHUB_JOB', 'windows-exe'))]
    job = max(candidates, key=lambda j: j.get('run_attempt', 0), default={})
    steps = job.get('steps', [])
    rows = []
    for stage, tasks in STAGES.items():
        matches = [r for r in records if r['stage'] in tasks]
        elapsed = sum(float(r['seconds']) for r in matches) if matches else None
        mandatory = tasks[:1] if stage == 'Packaging' else tasks
        complete = all(any(r['stage'] == task for r in matches) for task in mandatory)
        status = 'Failed' if any(r['status'] == 'failed' for r in matches) else 'Passed' if matches and complete else 'Incomplete' if matches else 'Not run'
        if stage == 'Environment':
            setup = steps[:next((i + 1 for i, s in enumerate(steps) if s['name'] in {'Environment', 'Create isolated Python build environment'}), 0)]
            if any(s.get('conclusion') in {'failure', 'cancelled'} for s in setup):
                status = 'Failed'
            values = [duration(s) for s in setup]
            if values and all(v is not None for v in values):
                elapsed = sum(values)
        if stage == 'Artifact upload':
            upload = next((s for s in steps if s['name'] == 'Upload verified executable'), {})
            elapsed = duration(upload)
            status = {'success': 'Passed', 'failure': 'Failed', 'skipped': 'Not run', 'cancelled': 'Cancelled'}.get(upload.get('conclusion'), 'Unavailable')
        rows.append((stage, elapsed, status))
    states = dict((name, status) for name, _, status in rows)
    overall = env.get('BUILD_STATUS', 'unknown')
    if any(status == 'Failed' for _, _, status in rows):
        overall = 'failure'
    elif overall == 'success' and any(status != 'Passed' for _, _, status in rows):
        overall = 'incomplete'
    elapsed = None
    try:
        start = datetime.fromisoformat((env.get('WORKFLOW_STARTED_AT') or job.get('started_at') or '').replace('Z', '+00:00'))
        elapsed = (now - start).total_seconds()
    except (KeyError, TypeError, ValueError):
        pass
    checks = '; '.join(f'{name}: {states[name]}' for name in ['Backend tests', 'Browser tests', 'Security audit'])
    fields = [
        ('Application version', package.get('version', env.get('APP_VERSION', 'Unavailable'))),
        ('Source', f"{env.get('GITHUB_REF_NAME', 'local')} @ {env.get('GITHUB_SHA', 'Unavailable')}"),
        ('Build status', overall),
        ('Windows runner', f"{env.get('RUNNER_OS', 'Unavailable')} {env.get('RUNNER_ARCH', '')}; {env.get('ImageOS', '')} {env.get('ImageVersion', '')}; {env.get('RUNNER_NAME', '')}"),
        ('Python / Node', f"{env.get('BUILD_PYTHON_VERSION', 'Unavailable')} / {env.get('BUILD_NODE_VERSION', 'Unavailable')}"),
        ('Validation', checks),
        ('Packaging format', package.get('format', 'one-file (default)')),
        ('Executable size', f"{package['size_bytes']:,} bytes" if 'size_bytes' in package else 'Unavailable'),
        ('Artifact size', env.get('ARTIFACT_SIZE', 'Unavailable; upload result does not supply size')),
        ('Executable SHA-256', package.get('exe_sha256', 'Unavailable; package not verified')),
        ('Artifact name', env.get('ARTIFACT_NAME', 'SAP-Lens-Windows-x64')),
        ('GitHub artifact ZIP SHA-256', env.get('ARTIFACT_DIGEST') or 'Unavailable'),
        ('Signing status', 'Unsigned; signing deferred (not configured)'),
        ('Workflow elapsed at report', seconds(elapsed) + (' (from run start; post-job cleanup pending)' if env.get('WORKFLOW_STARTED_AT') else ' (from job start; excludes queue and pending post-job cleanup)')),
        ('Packaging duration', seconds(next(value for name, value, _ in rows if name == 'Packaging'))),
        ('Smoke-test duration', seconds(next(value for name, value, _ in rows if name == 'Smoke tests'))),
        ('Warnings', 'See stage logs; known upstream/development caveats are tracked in docs/DEPRECATIONS.md'),
    ]
    output = ['# SAP Lens — Windows Build Report', '', '| Item | Value |', '|---|---|']
    output += [f'| {name} | {safe(value)} |' for name, value in fields]
    output += ['', '| Stage | Duration | Status |', '|---|---:|---|']
    output += [f'| {name} | {seconds(value)} | {status} |' for name, value, status in rows]
    output += ['', 'Task timings use stopwatches; Environment also includes setup/cache steps when available.',
               'Missing/interrupted tasks are not reported as passed. ZIP digest and executable checksum cover different bytes.',
               'Runner cleanup/cache saves finish after this report; the completed Actions run is authoritative for total duration.']
    return '\n'.join(output) + '\n'


def github_json(endpoint):
    try:
        result = subprocess.run(['gh', 'api', endpoint], capture_output=True, text=True, timeout=20)
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return {}


def main():
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if not summary:
        return
    try:
        env = dict(os.environ)
        try:
            import sys
            sys.path.insert(0, str(ROOT / 'backend'))
            from version import VERSION
            env['APP_VERSION'] = VERSION
        except (OSError, ValueError, ImportError):
            env['APP_VERSION'] = 'Unavailable'
        endpoint = f"repos/{env['GITHUB_REPOSITORY']}/actions/runs/{env['GITHUB_RUN_ID']}"
        artifact_id = env.get('ARTIFACT_ID')
        # These read-only metadata requests are independent; avoid serial API latency.
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs_request = pool.submit(github_json, endpoint + '/jobs?filter=latest')
            run_request = pool.submit(github_json, endpoint)
            artifact_request = pool.submit(github_json, f"repos/{env['GITHUB_REPOSITORY']}/actions/artifacts/{artifact_id}") if artifact_id and artifact_id.isdigit() else None
            jobs = jobs_request.result().get('jobs', [])
            env['WORKFLOW_STARTED_AT'] = run_request.result().get('run_started_at') or ''
            artifact = artifact_request.result() if artifact_request else {}
        if isinstance(artifact.get('size_in_bytes'), int):
            env['ARTIFACT_SIZE'] = f"{artifact['size_in_bytes']:,} bytes"
        if not jobs:
            print('::warning::Workflow timing metadata unavailable; local stage timings are retained.')
        package_path = ROOT / 'backend/build/package-verification.json'
        try:
            package = json.loads(package_path.read_text()) if package_path.is_file() else {}
        except (OSError, ValueError):
            package = {}
        for key, command in [('BUILD_PYTHON_VERSION', ['python', '--version']), ('BUILD_NODE_VERSION', ['node', '--version'])]:
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=5)
                env[key] = result.stdout.strip() if result.returncode == 0 else 'Unavailable'
            except (OSError, subprocess.TimeoutExpired):
                env[key] = 'Unavailable'
        Path(summary).write_text(render(read_timings(ROOT / 'backend/build/timings.jsonl'), package, jobs, env), encoding='utf-8')
    except Exception:
        # Report formatting/API errors cannot waive verification or fail a sound package.
        print('::warning::Build summary is incomplete; inspect stage logs and verification results.')


if __name__ == '__main__':
    main()
