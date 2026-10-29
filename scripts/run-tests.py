#!/usr/bin/env python3
"""One entry point for the SAP Lens test profiles (smoke, targeted, regression, release).

Standard library only; works on Windows and Linux. Feature ownership comes from
scripts/test-map.json. See docs/development/TESTING.md.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
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
    return problems


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
        merged = {'tests': 0, 'failures': 0, 'errors': 0, 'skipped': []}
        for code, out in outcomes:
            data = json.loads(out.read_text(encoding='utf-8')) if out.exists() else {'tests': 0, 'failures': 0, 'errors': 1, 'skipped': []}
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


def run_browser(specs: list[str] | None, grep: str | None, jobs: int, label: str, extra: list[str]) -> dict:
    """Shard across `jobs` independent Playwright processes, each with its own server, port and storage."""
    started = time.perf_counter()
    files = [f'tests/{name}.spec.ts' for name in specs] if specs is not None else []
    if specs is not None and not files:
        return {'name': label, 'tests': 0, 'failures': 0, 'errors': 0, 'skipped': [], 'seconds': 0.0, 'ok': True}
    with tempfile.TemporaryDirectory(prefix='sap-lens-browser-') as scratch:
        def launch(index: int) -> tuple[int, Path, Path]:
            report, log = Path(scratch) / f'report-{index}.json', Path(scratch) / f'log-{index}.txt'
            command = [npm(), '--prefix', str(FRONTEND), 'run', 'test:browser', '--', *files, '--reporter=line,json', f'--output={Path(scratch) / f"results-{index}"}']
            if grep:
                command += ['--grep', grep]
            if jobs > 1:
                command.append(f'--shard={index + 1}/{jobs}')
            env = {**os.environ, 'SAP_LENS_BROWSER_TEST_PORT': str(BASE_PORT + index), 'PLAYWRIGHT_JSON_OUTPUT_NAME': str(report)}
            if jobs == 1:  # a single process streams its progress live (CI logs, local feedback)
                return subprocess.run(command + extra, cwd=FRONTEND, env=env).returncode, report, log
            with log.open('w', encoding='utf-8') as handle:
                code = subprocess.run(command + extra, cwd=FRONTEND, env=env, stdout=handle, stderr=subprocess.STDOUT, text=True).returncode
            return code, report, log
        with ThreadPoolExecutor(jobs) as pool:
            outcomes = list(pool.map(launch, range(jobs)))
        merged = {'tests': 0, 'failures': 0, 'errors': 0, 'skipped': [], 'shards': []}
        ok = True
        for code, report, log in outcomes:
            if not report.exists():
                ok = False
                merged['errors'] += 1
                if log.exists():
                    sys.stderr.write(log.read_text(encoding='utf-8', errors='replace')[-3000:])
                continue
            stats = json.loads(report.read_text(encoding='utf-8'))['stats']
            merged['shards'].append(round(stats['duration'] / 1000, 1))
            merged['tests'] += stats['expected'] + stats['unexpected'] + stats['flaky']
            merged['failures'] += stats['unexpected'] + stats['flaky']
            merged['skipped'] += [['browser test', 'skipped']] * stats['skipped']
            if code:
                ok = False
                if log.exists():  # a single streamed process has already printed its own output
                    sys.stderr.write(log.read_text(encoding='utf-8', errors='replace')[-6000:])
    merged.update(name=label, seconds=time.perf_counter() - started, ok=ok and not merged['failures'])
    print(f"\n{merged['tests'] - merged['failures']} passed ({merged['seconds']:.0f}s)" + (f", {merged['failures']} failed" if merged['failures'] else ''), flush=True)
    return merged


# ---------------------------------------------------------------------------- static and release

def static_checks() -> list[dict]:
    py = sys.executable
    checks = [
        ('documentation links', [py, 'scripts/check-docs.py']),
        ('workflow contracts', [py, 'scripts/check-workflows.py']),
        ('Lucide catalog', ['node', 'scripts/sync-lucide-catalog.mjs', '--check']),
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
    """`auto` is conservative: browser tests saturate CPUs (Chromium plus a server per process)."""
    if value == 'auto':
        cpus = os.cpu_count() or 2
        return max(1, min(3, cpus // 2)) if kind == 'browser' else max(1, min(3, cpus))
    return max(1, int(value))


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
                counts += f"; shard seconds {stage['shards']}"
        print(f"  {'PASS' if stage['ok'] else 'FAIL'}  {fmt(stage['seconds'])}  {stage['name']}  {counts}")
        for test, reason in stage.get('skipped', []):
            if reason != 'skipped':
                print(f'          skipped: {test.split(" ")[0]} ({reason})')
        ok &= stage['ok']
    for note in notes:
        print(f'  NOTE  {note}')
    if profile in ('smoke', 'targeted'):
        print(f'  NOTE  {profile} is a partial run and is not a regression result; run `regression` before release.')
    print(f"  total {fmt(sum(s['seconds'] for s in stages))}  ->  {'OK' if ok else 'FAILED'}")
    if output:
        Path(output).write_text(json.dumps({'profile': profile, 'scope': scope, 'ok': ok, 'stages': stages, 'notes': notes}, indent=1, default=str), encoding='utf-8')
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if len(argv) > 2 and argv[0] == '_backend':
        return run_backend_worker(argv[2:], Path(argv[1]))
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('profile', choices=['smoke', 'targeted', 'regression', 'release', 'list', 'check'])
    parser.add_argument('features', nargs='*', help='features for the targeted profile (see `list`)')
    side = parser.add_mutually_exclusive_group()
    side.add_argument('--backend', action='store_true', help='backend tests only')
    side.add_argument('--browser', action='store_true', help='browser tests only')
    parser.add_argument('--jobs', default='auto', help='parallel processes (default auto: backend min(3, CPUs), browser min(3, CPUs/2); 1 disables)')
    parser.add_argument('--grep', help='additional Playwright title filter for browser tests')
    parser.add_argument('--no-build', action='store_true', help='skip the frontend build even if sources changed')
    parser.add_argument('--report', help='write a JSON summary to this file')
    parser.add_argument('--list-tests', action='store_true', help='print the selected files and exit')
    args, extra = parser.parse_known_args(argv)
    backend_jobs, browser_jobs = jobs_value(args.jobs, 'backend'), jobs_value(args.jobs, 'browser')
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
    if args.profile == 'smoke':
        scope = 'critical backend tests + browser tests tagged @smoke'
        smoke = load_map()['smoke']
        if args.list_tests:
            print('\n'.join(smoke['backend']) + f"\nbrowser: --grep {smoke['browser_tag']}")
            return 0
        if want_backend:
            stages.append(run_backend(smoke['backend'], 1, 'backend smoke', split=False))
        if want_browser:
            built = None if args.no_build else build_frontend()
            if built:
                stages.append(built)
            stages.append(run_browser(None, smoke['browser_tag'], 1, 'browser smoke', extra))
    elif args.profile == 'targeted':
        if not args.features:
            raise SystemExit('targeted needs at least one feature; run `list` to see them')
        modules, specs = selection(args.features)
        scope = ', '.join(args.features)
        if args.list_tests:
            print('backend: ' + ' '.join(modules) + '\nbrowser: ' + ' '.join(specs))
            return 0
        if want_backend and modules:
            stages.append(run_backend(modules, 1, 'backend targeted', split=False))
        if want_browser and specs:
            built = None if args.no_build else build_frontend()
            if built:
                stages.append(built)
            stages.append(run_browser(specs, args.grep, min(browser_jobs, len(specs)), 'browser targeted', extra))
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
