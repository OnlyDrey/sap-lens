#!/usr/bin/env python3
"""One entry point for the SAP Lens test profiles (changed, fast, smoke, targeted, regression, release).

Standard library only; works on Windows and Linux. Feature ownership comes from
scripts/test-map.json. See docs/development/TESTING.md.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / 'frontend'
BACKEND_TESTS = ROOT / 'backend' / 'tests'
BROWSER_TESTS = FRONTEND / 'tests'
MAP = ROOT / 'scripts' / 'test-map.json'
BASE_PORT = 18745


def load_map() -> dict:
    return json.loads(MAP.read_text(encoding='utf-8'))


def backend_modules() -> list[str]:
    return sorted(path.stem for path in BACKEND_TESTS.glob('test_*.py'))


def browser_specs() -> list[str]:
    return sorted(path.name[:-len('.spec.ts')] for path in BROWSER_TESTS.glob('*.spec.ts'))


def selection(features: list[str] | None) -> tuple[list[str], list[str]]:
    """Backend modules and browser spec names for the named features (all when None)."""
    mapping = load_map()['features']
    names = list(mapping) if not features else features
    unknown = [name for name in names if name not in mapping]
    if unknown:
        raise SystemExit(f'Unknown feature(s): {", ".join(unknown)}. Known: {", ".join(mapping)}')
    return ([m for n in names for m in mapping[n]['backend']], [s for n in names for s in mapping[n]['browser']])


def coverage_problems() -> list[str]:
    """Every test file must belong to exactly one feature, so no profile can silently drop tests."""
    mapping = load_map()['features']
    problems = []
    for kind, actual in (('backend', backend_modules()), ('browser', browser_specs())):
        listed = [name for feature in mapping.values() for name in feature[kind]]
        problems += [f'{kind} test not mapped to a feature: {name}' for name in sorted(set(actual) - set(listed))]
        problems += [f'{kind} mapping names a missing test file: {name}' for name in sorted(set(listed) - set(actual))]
        problems += [f'{kind} test mapped more than once: {name}' for name in sorted({n for n in listed if listed.count(n) > 1})]
    hints = load_map().get('browser_seconds_hint', {})
    problems += [f'browser_seconds_hint names a missing spec: {name}' for name in sorted(set(hints) - set(browser_specs()))]
    return problems


# ---------------------------------------------------------------------------- change selection (Fast Validation)

def _pattern(glob: str) -> re.Pattern:
    out, i = '', 0
    while i < len(glob):
        if glob.startswith('**/', i):
            out += '(?:.*/)?'; i += 3
        elif glob.startswith('**', i):
            out += '.*'; i += 2
        elif glob[i] == '*':
            out += '[^/]*'; i += 1
        else:
            out += re.escape(glob[i]); i += 1
    return re.compile(out + r'\Z')


def classify(path: str, rules: dict | None = None) -> str:
    """docs, backend_tests, frontend_tests, frontend or core. Core is the default, so an unmapped path runs the whole backend suite."""
    rules = rules or load_map()['change_rules']
    for category in ('docs', 'backend_tests', 'frontend_tests', 'frontend'):
        if any(_pattern(glob).match(path) for glob in rules[category]):
            return category
    return 'core'


def changed_files(base: str | None) -> list[str] | None:
    """Paths that differ from `base` (working tree included); None when the base is unusable, which selects the safe baseline."""
    if not base or set(base) == {'0'}:
        return None
    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True)
    present = lambda: git('cat-file', '-e', base + '^{commit}').returncode == 0
    if not present():
        git('fetch', '--no-tags', '--depth=1', 'origin', base)  # a shallow CI checkout may lack the previous commit
    if not present():
        return None
    done = git('diff', '--name-only', base)
    return sorted(set(done.stdout.split())) if done.returncode == 0 else None


def plan_changes(files: list[str] | None) -> dict:
    """What Fast Validation runs for a change. Never less than: the repository integrity tests; the whole backend for any backend source,
    script, workflow, dependency or unmapped change; build, lint and the @smoke browser tests for any frontend change."""
    mapping = load_map()
    rules = mapping['change_rules']
    always = [m for feature in rules['always'] for m in mapping['features'][feature]['backend']]
    if files is None:
        return dict(backend='full', modules=[], frontend=True, browser=True, specs=[], reasons=['no usable base commit: safe baseline (whole backend, frontend checks, browser smoke)'], files=None)
    modules, specs, reasons = set(always), set(), []
    backend_full = frontend = False
    for path in files:
        category = classify(path, rules)
        if category == 'docs':
            continue
        if category == 'backend_tests':
            name = Path(path).stem
            if name.startswith('test_'):
                if (BACKEND_TESTS / f'{name}.py').exists():  # a deleted test module has nothing left to run
                    modules.add(name)
            else:
                backend_full = True  # a shared helper or fixture: its users are unknown
                reasons.append(f'{path}: shared test helper')
        elif category == 'frontend_tests':
            frontend = True
            name = Path(path).name[:-len('.spec.ts')] if path.endswith('.spec.ts') else None
            if name and (BROWSER_TESTS / f'{name}.spec.ts').exists():
                specs.add(name)
        elif category == 'frontend':
            frontend = True
        else:
            backend_full = True
            reasons.append(f'{path}: core (backend source, script, workflow, dependency or unmapped path)')
    return dict(backend='full' if backend_full else 'modules' if len(modules) > len(always) else 'repository',
                modules=sorted(modules), frontend=frontend, browser=frontend, specs=sorted(specs), reasons=reasons[:12], files=files)


# ---------------------------------------------------------------------------- backend

def run_backend_worker(names: list[str], output: Path) -> int:
    """Run unittest names in this process and write a JSON result (used as a subprocess)."""
    sys.path.insert(0, str(BACKEND_TESTS))
    suite = unittest.TestLoader().loadTestsFromNames(names)
    started = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=0, stream=sys.stderr).run(suite)
    output.write_text(json.dumps({
        'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
        'skipped': [[str(test), reason] for test, reason in result.skipped], 'seconds': time.perf_counter() - started,
    }), encoding='utf-8')
    return 0 if result.wasSuccessful() else 1


def split_modules(modules: list[str], jobs: int) -> list[list[str]]:
    """Longest-first balancing from measured hints, falling back to the number of test functions."""
    hints = load_map().get('backend_seconds_hint', {})
    weight = lambda m: hints.get(m, 0.08 * len((BACKEND_TESTS / f'{m}.py').read_text(encoding='utf-8').split('    def test_')))
    groups: list[list[str]] = [[] for _ in range(max(1, jobs))]
    loads = [0.0] * len(groups)
    for module in sorted(modules, key=weight, reverse=True):
        index = loads.index(min(loads))
        groups[index].append(module)
        loads[index] += weight(module)
    return [group for group in groups if group]


def run_backend(names: list[str], jobs: int, label: str, split: bool) -> dict:
    started = time.perf_counter()
    groups = split_modules(names, jobs) if split else [names]
    with tempfile.TemporaryDirectory(prefix='sap-lens-backend-') as scratch:
        def launch(index_group: tuple[int, list[str]]) -> tuple[int, Path]:
            index, group = index_group
            out = Path(scratch) / f'{index}.json'
            command = [sys.executable, '-W', 'error::DeprecationWarning', str(Path(__file__).resolve()), '_backend', str(out), *group]
            code = subprocess.run(command, cwd=ROOT).returncode
            return code, out
        with ThreadPoolExecutor(len(groups)) as pool:
            outcomes = list(pool.map(launch, enumerate(groups)))
        merged = {'tests': 0, 'failures': 0, 'errors': 0, 'skipped': [], 'shards': []}
        for code, out in outcomes:
            data = json.loads(out.read_text(encoding='utf-8')) if out.exists() else {'tests': 0, 'failures': 0, 'errors': 1, 'skipped': [], 'seconds': 0.0}
            merged['shards'].append(round(data.get('seconds', 0.0), 1))
            for key in ('tests', 'failures', 'errors'):
                merged[key] += data[key]
            merged['skipped'] += data['skipped']
    merged.update(name=label, seconds=time.perf_counter() - started, ok=not merged['failures'] and not merged['errors'] and all(c == 0 for c, _ in outcomes))
    # Aggregate lines in unittest's own format keep scripts/ci.py counts correct after parallel workers.
    print(f"\nRan {merged['tests']} tests in {merged['seconds']:.3f}s")
    print(('OK' if merged['ok'] else 'FAILED') + (f" (skipped={len(merged['skipped'])})" if merged['skipped'] else ''), flush=True)
    return merged


# ---------------------------------------------------------------------------- browser

def npm() -> str:
    return shutil.which('npm') or shutil.which('npm.cmd') or 'npm'


def dist_is_stale() -> bool:
    built = FRONTEND / 'dist' / 'index.html'
    if not built.exists():
        return True
    inputs = ['index.html', 'package.json', 'vite.config.ts', 'tailwind.config.ts', 'tsconfig.json']
    files = [FRONTEND / name for name in inputs] + list((FRONTEND / 'src').rglob('*'))
    return max((p.stat().st_mtime for p in files if p.is_file()), default=0) > built.stat().st_mtime


def step(name: str, command: list[str], cwd: Path = ROOT, env: dict | None = None, quiet: bool = True) -> dict:
    started = time.perf_counter()
    done = subprocess.run(command, cwd=cwd, env={**os.environ, **(env or {})}, capture_output=quiet, text=True)
    if quiet and done.returncode:
        sys.stderr.write((done.stdout or '')[-4000:] + (done.stderr or '')[-2000:])
    return {'name': name, 'seconds': time.perf_counter() - started, 'ok': done.returncode == 0, 'tests': None}


def build_frontend(force: bool = False) -> dict | None:
    if not (FRONTEND / 'node_modules').exists():
        raise SystemExit('Frontend dependencies are missing: run `npm --prefix frontend ci` first.')
    if not force and not dist_is_stale():
        return None
    return step('build (includes TypeScript check)', [npm(), '--prefix', str(FRONTEND), 'run', 'build'])


def busy_ports(jobs: int) -> list[int]:
    """Ports of this run that another process already listens on. The runner reports them; it never stops a process."""
    busy = []
    for port in range(BASE_PORT, BASE_PORT + jobs):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                busy.append(port)
    return busy


BROWSER_JOBS_MAX = 3  # measured on 4 vCPUs: 3 processes were the fastest, 4 were slower (Chromium saturates the host)
DEFAULT_SPEC_SECONDS = 35.0
OWNED: list[subprocess.Popen] = []  # only processes this runner started; they are the only ones it ever signals


def split_specs(files: list[str], jobs: int) -> list[list[str]]:
    """Deterministic longest-first assignment of spec files to `jobs` independent processes, from measured per-spec seconds."""
    hints = load_map().get('browser_seconds_hint', {})
    weight = lambda f: hints.get(Path(f).name[:-len('.spec.ts')], DEFAULT_SPEC_SECONDS)
    groups: list[list[str]] = [[] for _ in range(max(1, jobs))]
    loads = [0.0] * len(groups)
    for file in sorted(files, key=lambda f: (-weight(f), f)):
        index = loads.index(min(loads))
        groups[index].append(file)
        loads[index] += weight(file)
    return [sorted(group) for group in groups if group]


def stop_owned(grace: float = 20.0) -> None:
    """Terminate the process groups this runner started (SIGTERM first so servers clean up, then SIGKILL); nothing else is touched."""
    for process in OWNED:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM) if hasattr(os, 'killpg') else process.terminate()
            except (ProcessLookupError, PermissionError):
                pass
    deadline = time.monotonic() + grace
    for process in OWNED:
        try:
            process.wait(max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL) if hasattr(os, 'killpg') else process.kill()
            except (ProcessLookupError, PermissionError):
                pass
    OWNED.clear()


def playwright_tests(report: dict) -> list[tuple[float, str, str, str]]:
    """(seconds, spec file, title, status) for every test of a Playwright JSON report."""
    found: list[tuple[float, str, str, str]] = []
    def walk(suite: dict) -> None:
        for spec in suite.get('specs', []):
            for test in spec.get('tests', []):
                found.append((sum(r.get('duration', 0) for r in test.get('results', [])) / 1000, spec.get('file', suite.get('file', '')), spec.get('title', ''), test.get('status', '')))
        for child in suite.get('suites', []):
            walk(child)
    for suite in report.get('suites', []):
        walk(suite)
    return found


def run_browser(specs: list[str] | None, grep: str | None, jobs: int, label: str, extra: list[str]) -> dict:
    """Run the browser tests in `jobs` independent Playwright processes, each with its own server, port and storage."""
    started = time.perf_counter()
    names = specs if specs is not None else browser_specs()
    files = [f'tests/{name}.spec.ts' for name in names]
    if specs is not None and not files:
        return {'name': label, 'tests': 0, 'failures': 0, 'errors': 0, 'skipped': [], 'seconds': 0.0, 'ok': True}
    jobs = max(1, min(jobs, len(files) or 1, BROWSER_JOBS_MAX))
    if (busy := busy_ports(jobs)):
        sys.stderr.write(f"Browser test port(s) {', '.join(map(str, busy))} already in use by another process (a stale test server?). "
                         "Stop that process yourself (find it with `ss -ltnp`); the runner never signals processes it did not start.\n")
        return {'name': label, 'tests': 0, 'failures': 0, 'errors': 1, 'skipped': [], 'seconds': 0.0, 'ok': False}
    groups = split_specs(files, jobs) if jobs > 1 else [files if specs is not None else []]
    with tempfile.TemporaryDirectory(prefix='sap-lens-browser-') as scratch:
        launched: list[tuple[int, int, subprocess.Popen, Path, Path, list[str]]] = []
        try:
            for index, group in enumerate(groups):
                report, log = Path(scratch) / f'report-{index}.json', Path(scratch) / f'log-{index}.txt'
                command = [npm(), '--prefix', str(FRONTEND), 'run', 'test:browser', '--', *group, '--reporter=line,json', f'--output={Path(scratch) / f"results-{index}"}']
                if grep:
                    command += ['--grep', grep]
                env = {**os.environ, 'SAP_LENS_BROWSER_TEST_PORT': str(BASE_PORT + index), 'PLAYWRIGHT_JSON_OUTPUT_NAME': str(report)}
                handle = None if jobs == 1 else log.open('w', encoding='utf-8')  # a single process streams its progress live (CI logs, local feedback)
                process = subprocess.Popen(command + extra, cwd=FRONTEND, env=env, stdout=handle, stderr=subprocess.STDOUT if handle else None, text=True, start_new_session=True)
                OWNED.append(process)
                launched.append((index, BASE_PORT + index, process, report, log, group))
            codes = [(item, item[2].wait()) for item in launched]
        finally:
            stop_owned()  # an interrupt or an error must not leave our own Chromium or test servers behind
        merged = {'tests': 0, 'failures': 0, 'errors': 0, 'skipped': [], 'shards': [], 'shard_detail': [], 'slowest': [], 'failed': []}
        ok, every = True, []
        for (index, port, _, report, log, group), code in codes:
            where = f'shard {index + 1}/{len(groups)} (port {port}, {len(group) or "all"} spec files)'
            if not report.exists():
                ok = False
                merged['errors'] += 1
                sys.stderr.write(f'{where} produced no report.\n')
                if log.exists():
                    sys.stderr.write(log.read_text(encoding='utf-8', errors='replace')[-3000:])
                continue
            data = json.loads(report.read_text(encoding='utf-8'))
            stats, tests = data['stats'], playwright_tests(data)
            every += tests
            merged['shards'].append(round(stats['duration'] / 1000, 1))
            merged['shard_detail'].append({'shard': index + 1, 'port': port, 'spec_files': len(group), 'seconds': round(stats['duration'] / 1000, 1), 'tests': stats['expected'] + stats['unexpected'] + stats['flaky']})
            merged['tests'] += stats['expected'] + stats['unexpected'] + stats['flaky']
            merged['failures'] += stats['unexpected'] + stats['flaky']
            merged['skipped'] += [['browser test', 'skipped']] * stats['skipped']
            failed = [(file, title) for _, file, title, status in tests if status in {'unexpected', 'flaky'}]
            merged['failed'] += [f'{file} :: {title} [{where}]' for file, title in failed]
            if code:
                ok = False
                sys.stderr.write(f'{where} failed' + (':\n  ' + '\n  '.join(f'{file} :: {title}' for file, title in failed) if failed else '') + '\n')
                if log.exists():  # a single streamed process has already printed its own output
                    sys.stderr.write(log.read_text(encoding='utf-8', errors='replace')[-6000:])
        merged['slowest'] = [[round(seconds, 1), file, title] for seconds, file, title, _ in sorted(every, reverse=True)[:10]]
    merged.update(name=label, seconds=time.perf_counter() - started, ok=ok and not merged['failures'])
    print(f"\n{merged['tests'] - merged['failures']} passed ({merged['seconds']:.0f}s)" + (f", {merged['failures']} failed" if merged['failures'] else ''), flush=True)
    return merged


# ---------------------------------------------------------------------------- static and release

def fast_static_checks() -> list[dict]:
    """The cheap checks of every phase: whitespace, documentation links, workflow contracts, both linters and the TypeScript check."""
    py = sys.executable
    return [step(name, command) for name, command in (
        ('whitespace (git diff --check)', ['git', 'diff', '--check']),
        ('documentation links', [py, 'scripts/check-docs.py']),
        ('workflow contracts', [py, 'scripts/check-workflows.py']),
        ('Python lint (ruff)', [py, '-m', 'ruff', 'check', 'backend', 'scripts']),
        ('frontend lint (ESLint)', [npm(), '--prefix', str(FRONTEND), 'run', 'lint']),
        ('TypeScript check', [npm(), '--prefix', str(FRONTEND), 'run', 'check:types']))]


def static_checks() -> list[dict]:
    py = sys.executable
    checks = [
        ('documentation links', [py, 'scripts/check-docs.py']),
        ('workflow contracts', [py, 'scripts/check-workflows.py']),
        ('Lucide catalog', ['node', 'scripts/sync-lucide-catalog.mjs', '--check']),
        ('Python lint (ruff)', [py, '-m', 'ruff', 'check', 'backend', 'scripts']),
        ('frontend lint (ESLint)', [npm(), '--prefix', str(FRONTEND), 'run', 'lint']),
        ('whitespace (git diff --check)', ['git', 'diff', '--check']),
        ('pip check', [py, '-m', 'pip', 'check']),
    ]
    return [step(name, command) for name, command in checks]


def release_checks() -> tuple[list[dict], list[str]]:
    py = sys.executable
    results, unavailable = [], []
    results.append(step('npm audit (production)', [npm(), '--prefix', str(FRONTEND), 'audit', '--omit=dev']))
    if subprocess.run([py, '-m', 'pip_audit', '--version'], capture_output=True).returncode == 0:
        results.append(step('pip-audit', [py, '-m', 'pip_audit', '--vulnerability-service', 'pypi', '--progress-spinner', 'off']))
    else:
        unavailable.append('pip-audit is not installed (see docs/development/CI.md); Python advisories were NOT checked')
    if shutil.which('pwsh'):
        results.append(step('PowerShell parse and safety guards', ['pwsh', '-NoProfile', '-File', 'scripts/check-powershell.ps1']))
    else:
        unavailable.append('pwsh is not installed; PowerShell script checks were NOT run')
    if shutil.which('actionlint'):
        results.append(step('workflow lint', [py, 'scripts/ci.py', 'lint']))
    else:
        unavailable.append('actionlint is not installed; workflow schema/expression lint was NOT run (contracts ran in regression)')
    unavailable.append('Docker image build/run, Windows installer/service/WebView2, native Linux package and systemd acceptance need their own environments or the manual build workflows; they were NOT run here (see docs/deployment/README.md)')
    return results, unavailable


# ---------------------------------------------------------------------------- reporting

def jobs_value(value: str, kind: str) -> int:
    """`auto` parallelizes the backend only: browser processes compete for CPUs, so they are opt-in (--browser-jobs)."""
    if value == 'auto':
        return 1 if kind == 'browser' else max(1, min(3, os.cpu_count() or 2))
    return max(1, int(value))


def browser_jobs_value(option: str | None, fallback: int) -> int:
    """`--browser-jobs` (or SAP_LENS_BROWSER_JOBS): a number, or `auto` = one process per spare CPU, at least 1 and at most 3. Never more than 3."""
    value = option or os.environ.get('SAP_LENS_BROWSER_JOBS') or ''
    if not value:
        return min(fallback, BROWSER_JOBS_MAX)
    if value == 'auto':
        return max(1, min(BROWSER_JOBS_MAX, (os.cpu_count() or 2) - 1))
    return max(1, min(int(value), BROWSER_JOBS_MAX))


def fmt(seconds: float) -> str:
    return f'{seconds:6.1f}s'


def report(profile: str, scope: str, stages: list[dict], notes: list[str], output: str | None) -> int:
    print(f'\nSAP Lens test profile: {profile.upper()} ({scope})')
    ok = True
    for stage in stages:
        counts = ''
        if stage.get('tests') is not None:
            counts = f"{stage['tests']} tests, {len(stage['skipped'])} skipped, {stage['failures'] + stage['errors']} failed"
            if stage.get('shards') and len(stage['shards']) > 1:
                counts += f"; process seconds {stage['shards']}"
        print(f"  {'PASS' if stage['ok'] else 'FAIL'}  {fmt(stage['seconds'])}  {stage['name']}  {counts}")
        for test, reason in stage.get('skipped', []):
            if reason != 'skipped':
                print(f'          skipped: {test.split(" ")[0]} ({reason})')
        for seconds, file, title in stage.get('slowest', []) if profile in ('regression', 'release') else []:
            print(f'          slowest: {seconds:6.1f}s  {file} :: {title[:80]}')
        ok &= stage['ok']
    for note in notes:
        print(f'  NOTE  {note}')
    if profile in ('smoke', 'targeted', 'fast', 'changed'):
        print(f'  NOTE  {profile} is a partial run and is not a regression result; run `regression` before release.')
    print(f"  total {fmt(sum(s['seconds'] for s in stages))}  ->  {'OK' if ok else 'FAILED'}")
    if output:
        Path(output).write_text(json.dumps({'profile': profile, 'scope': scope, 'ok': ok, 'stages': stages, 'notes': notes}, indent=1, default=str), encoding='utf-8')
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if len(argv) > 2 and argv[0] == '_backend':
        return run_backend_worker(argv[2:], Path(argv[1]))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('profile', choices=['changed', 'fast', 'smoke', 'targeted', 'regression', 'release', 'list', 'check'])
    parser.add_argument('features', nargs='*', help='features for the targeted profile (see `list`)')
    side = parser.add_mutually_exclusive_group()
    side.add_argument('--backend', action='store_true', help='backend tests only')
    side.add_argument('--browser', action='store_true', help='browser tests only')
    parser.add_argument('--jobs', default='auto', help='parallel processes (default auto: backend min(3, CPUs), browser 1; 1 disables)')
    parser.add_argument('--browser-jobs', help='browser processes: a number up to 3 or `auto` (one per spare CPU, 1 to 3); default 1 or SAP_LENS_BROWSER_JOBS')
    parser.add_argument('--grep', help='additional Playwright title filter for browser tests')
    parser.add_argument('--base', default=os.environ.get('BASE_SHA', 'HEAD~1'), help='changed profile: commit to compare with (default BASE_SHA or HEAD~1)')
    parser.add_argument('--plan', action='store_true', help='changed profile: print the selection (and write GitHub outputs) without running tests')
    parser.add_argument('--stage', choices=['backend', 'browser'], help='changed profile: run only this part of the selection')
    parser.add_argument('--no-build', action='store_true', help='skip the frontend build even if sources changed')
    parser.add_argument('--report', help='write a JSON summary to this file')
    parser.add_argument('--list-tests', action='store_true', help='print the selected files and exit')
    args, extra = parser.parse_known_args(argv)
    backend_jobs = jobs_value(args.jobs, 'backend')
    browser_jobs = browser_jobs_value(args.browser_jobs, jobs_value(args.jobs, 'browser'))
    want_backend, want_browser = not args.browser, not args.backend

    if args.profile == 'check':
        problems = coverage_problems()
        print('\n'.join(problems) or 'Every backend module and browser spec is mapped to exactly one feature.')
        return 1 if problems else 0
    if args.profile == 'list':
        for name, feature in load_map()['features'].items():
            print(f"{name:20s} backend {len(feature['backend']):2d} modules, browser {len(feature['browser']):2d} specs  {feature['description']}")
        return 0
    problems = coverage_problems()
    if problems:
        raise SystemExit('Test map is out of date:\n' + '\n'.join(problems))

    stages: list[dict] = []
    notes: list[str] = []

    def smoke_stages() -> None:
        smoke = load_map()['smoke']
        if want_backend:
            stages.append(run_backend(smoke['backend'], 1, 'backend smoke', split=False))
        if want_browser:
            built = None if args.no_build else build_frontend()
            if built:
                stages.append(built)
            stages.append(run_browser(None, smoke['browser_tag'], 1, 'browser smoke', extra))

    def targeted_stages(modules: list[str], specs: list[str]) -> None:
        if want_backend and modules:
            stages.append(run_backend(modules, 1, 'backend targeted', split=False))
        if want_browser and specs:
            built = None if args.no_build else build_frontend()
            if built and not any(stage['name'] == built['name'] for stage in stages):
                stages.append(built)
            stages.append(run_browser(specs, args.grep, min(browser_jobs, len(specs)), 'browser targeted', extra))

    if args.profile == 'changed':
        plan = plan_changes(changed_files(args.base))
        print(json.dumps({key: value for key, value in plan.items() if key != 'files'}, indent=1))
        if args.plan:
            if os.environ.get('GITHUB_OUTPUT'):
                with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
                    stream.write(f"backend={plan['backend']}\nfrontend={'true' if plan['frontend'] else 'false'}\nbrowser={'true' if plan['browser'] else 'false'}\n")
            return 0
        scope = f"changes since {args.base}: backend {plan['backend']}, frontend {'yes' if plan['frontend'] else 'no'}"
        if args.stage in (None, 'backend'):
            everything = plan['backend'] == 'full'
            stages.append(run_backend(backend_modules() if everything else plan['modules'], backend_jobs, f"backend {'regression' if everything else 'selection'}", split=True))
        if args.stage in (None, 'browser') and plan['browser']:
            smoke = load_map()['smoke']
            if not args.no_build and args.stage is None:
                built = build_frontend()
                if built:
                    stages.append(built)
            stages.append(run_browser(None, smoke['browser_tag'], 1, 'browser smoke', extra))
            if plan['specs']:
                stages.append(run_browser(plan['specs'], args.grep, min(browser_jobs, len(plan['specs'])), 'browser changed specs', extra))
    elif args.profile == 'smoke':
        scope = 'critical backend tests + browser tests tagged @smoke'
        smoke = load_map()['smoke']
        if args.list_tests:
            print('\n'.join(smoke['backend']) + f"\nbrowser: --grep {smoke['browser_tag']}")
            return 0
        smoke_stages()
    elif args.profile == 'fast':
        scope = 'static checks + critical smoke tests' + (f" + targeted {', '.join(args.features)}" if args.features else '')
        modules, specs = selection(args.features) if args.features else ([], [])
        if args.list_tests:
            print('static: whitespace, docs, workflows, ruff, eslint, tsc\nsmoke: see `smoke --list-tests`\nbackend: ' + ' '.join(modules) + '\nbrowser: ' + ' '.join(specs))
            return 0
        stages += fast_static_checks()
        smoke_stages()
        targeted_stages(modules, specs)
    elif args.profile == 'targeted':
        if not args.features:
            raise SystemExit('targeted needs at least one feature; run `list` to see them')
        modules, specs = selection(args.features)
        scope = ', '.join(args.features)
        if args.list_tests:
            print('backend: ' + ' '.join(modules) + '\nbrowser: ' + ' '.join(specs))
            return 0
        targeted_stages(modules, specs)
        if not stages:
            notes.append('The selected features have no tests for the chosen side.')
    else:
        scope = 'all backend and browser tests, build, static checks' + (' and release checks' if args.profile == 'release' else '')
        modules, specs = backend_modules(), browser_specs()
        if args.list_tests:
            print(f'backend: {len(modules)} modules\nbrowser: {len(specs)} specs')
            return 0
        if want_backend:
            stages.append(run_backend(modules, backend_jobs, f'backend regression ({backend_jobs} process(es))', split=True))
        if want_browser:
            built = None if args.no_build else build_frontend(force=True)
            if built:
                stages.append(built)
            stages.append(run_browser(None, args.grep, browser_jobs, f'browser regression ({browser_jobs} process(es))', extra))
        if want_backend and want_browser:
            stages += static_checks()
        if args.profile == 'release':
            extra_stages, unavailable = release_checks()
            stages += extra_stages
            notes += unavailable
        if args.backend or args.browser:
            notes.append('Only one side was selected; this is not a complete regression.')
    return report(args.profile, scope, stages, notes, args.report)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
