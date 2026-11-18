"""Reproducible data-path benchmark on synthetic data (nothing is written to the repository).

    python scripts/benchmarks/data_benchmark.py --roles 400 --users 4000 --assignments 12 [--json out.json]

Every scenario runs in a fresh child process against a disposable application-data directory so peak memory (ru_maxrss), cold and warm
timings are comparable between phases. Scenarios follow the real production path (csv_lifecycle.load): `import` stages and activates the
CSVs (writes snapshots), `startup` restores and re-reads the CSVs (dynamic sources, the default), `startup-warm` repeats it, and the `startup-static*` pair restores from stored data only.
Datasets are generated deterministically (seed 1) into the temporary directory and deleted afterwards."""
import argparse
import csv
import json
import os
import random
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = Path(os.environ.get('SAP_LENS_BENCH_BACKEND') or ROOT / 'backend')  # point at another checkout's backend/ to compare revisions


DIRECTORY_HEADERS = 'Site;Name;SamAccountName;UserPrincipalName;Mail;Department;Title;Enabled;DistinguishedName;ManagerDN;ManagerName;ManagerSamAccountName;ManagerMail;ManagerDepartment;ManagerTitle;ManagerLookupStatus'.split(';')


def generate_directory(directory, employees):
    """One employee per SAP user (matching e-mail u<n>@example.test) with a manager chain: every tenth employee manages the next nine."""
    path = directory / 'directory.csv'
    with path.open('w', newline='') as stream:
        writer = csv.writer(stream, delimiter=';')
        writer.writerow(DIRECTORY_HEADERS)
        for number in range(employees):
            boss = number - number % 10
            managed = number != boss
            writer.writerow(['HQ', f'Employee {number}', f'emp{number}', f'emp{number}@example.test', f'u{number}@example.test', f'D{number % 20}', f'Title {number % 7}', 'True',
                             f'CN=emp{number},OU=Staff,DC=example,DC=test', f'CN=emp{boss},OU=Staff,DC=example,DC=test' if managed else '', f'Employee {boss}' if managed else '',
                             f'emp{boss}' if managed else '', f'u{boss}@example.test' if managed else '', f'D{boss % 20}' if managed else '', f'Title {boss % 7}' if managed else '', ''])
    return path


def generate(directory, roles, users, assignments):
    random.seed(1)
    catalogue = directory / 'roles.csv'
    with catalogue.open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow('FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT'.split(','))
        for role in range(roles):
            for child in range(5):
                for code in range(6):
                    writer.writerow(['FI' if role % 2 else 'MM', f'Z:COMP:{role:04d}', f'Composite {role}', f'Z:SINGLE:{role:04d}:{child}', f'Single {role} {child}', f'ZT{role:04d}{child}{code}', 'Tx'])
    people = directory / 'users.csv'
    rows = 0
    with people.open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow('USERNAME,ROLE_NAME,EMAIL,USER_GROUP,USER_VALID_FROM,USER_VALID_TO,ROLE_VALID_FROM,ROLE_VALID_TO'.split(','))
        for user in range(users):
            for role in random.sample(range(roles), min(assignments, roles)):
                writer.writerow([f'USER{user:05d}', f'Z:COMP:{role:04d}', f'u{user}@example.test', f'G{user % 12}', '20200101', '99991231', '20200101', '99991231'])
                rows += 1
    return catalogue, people, rows


def child(scenario, data, catalogue, people, employees=''):
    os.environ.update(SAP_LENS_CONFIG_DIR=str(data), DATA_CSV_PATH='')
    sys.path.insert(0, str(BACKEND))
    import cache
    import config
    import csv_lifecycle
    settings = config.get_settings().model_copy(deep=True)
    settings.data_csv_path, settings.user_csv_path = catalogue, people
    if employees:
        settings.employee_csv_path = employees
        settings.features.employee_directory = True
        settings.source_modes.employees = 'dynamic'
    if scenario == 'api':
        return api(data, catalogue, people, employees)
    if scenario.startswith('startup-static'):
        settings.source_modes.roles = settings.source_modes.users = 'static'  # restore from stored data only, no re-read of the CSV files
    if scenario == 'startup-static':  # first static start: switches the modes (not timed), then restores
        config.save_configuration(settings, settings.revision)
    started = time.perf_counter()
    result = None
    if scenario == 'import':
        config.save_configuration(settings, settings.revision)
        result = csv_lifecycle.load(config.get_settings(), operation='refresh', strict=True)
    elif scenario == 'refresh-directory-changed':  # one employee changes department and manager: only the directory is parsed, compared and re-matched
        csv_lifecycle.load(config.get_settings(), operation='startup', strict=True)  # the running application (not timed)
        started = time.perf_counter()
        text = Path(employees).read_text()
        Path(employees).write_text(text.replace(';D5;Title 5;', ';D6;Title 5;', 1))
        result = csv_lifecycle.load(config.get_settings(), operation='refresh', strict=True)
    elif scenario == 'refresh-users-changed':  # one user's e-mail changes: only the users source is parsed, compared and rebuilt
        csv_lifecycle.load(config.get_settings(), operation='startup', strict=True)  # the running application (not timed)
        started = time.perf_counter()
        text = Path(people).read_text()
        Path(people).write_text(text.replace('u0@example.test', 'u0-renamed@example.test', 1))
        result = csv_lifecycle.load(config.get_settings(), operation='refresh', strict=True)
    elif os.environ.get('SAP_LENS_BENCH_PROFILE'):
        import cProfile
        import pstats
        profiler = cProfile.Profile()
        profiler.runcall(csv_lifecycle.load, config.get_settings(), operation='startup', strict=True)
        pstats.Stats(profiler, stream=sys.stderr).sort_stats('cumulative').print_stats(14)
    else:
        result = csv_lifecycle.load(config.get_settings(), operation='startup', strict=True)
    elapsed = time.perf_counter() - started
    state = cache.get_snapshot()
    def resident():
        return int(open('/proc/self/statm').read().split()[1]) * os.sysconf('SC_PAGE_SIZE') // 2**20 if os.path.exists('/proc/self/statm') else 0
    rss = resident()
    # What the retained raw source records cost: drop them (state is left unusable for refresh diffs) and measure again.
    import gc
    state.users.source_records, state.source_records = [], []
    gc.collect()
    without_records = resident()
    remap = None
    if employees:  # identity mapping of every SAP user against the directory (the work behind Data Health, Account Review and the SoD analysis)
        from routers import employees as directory_routes
        began = time.perf_counter()
        directory_routes.directory_status(snapshot=state)
        remap = round(time.perf_counter() - began, 3)
    statuses = {row['source']: row['status'] for row in (result or {}).get('sources', [])}
    print(json.dumps(dict(scenario=scenario, sources=statuses, remap_seconds=remap, seconds=round(elapsed, 3), peak_mb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024), rss_mb=rss, rss_without_source_records_mb=without_records,
                          roles=len(state.roles), users=len(state.users.users), assignments=len(state.users.assignments))))


def api(data, catalogue, people, employees):
    """Request latency (median of 5, first call excluded) of the heavy read endpoints on a started instance; with SAP_LENS_BENCH_PROFILE=api also the hottest functions of each."""
    import cProfile
    import pstats
    import statistics
    import cache
    import config
    import csv_lifecycle
    from fastapi.testclient import TestClient
    from main import create_app
    settings = config.get_settings().model_copy(deep=True)
    settings.data_csv_path, settings.user_csv_path = catalogue, people
    if employees:
        settings.employee_csv_path = employees
        settings.features.employee_directory = True
    config.save_configuration(settings, settings.revision)
    csv_lifecycle.load(config.get_settings(), operation='refresh', strict=True)
    client = TestClient(create_app(session_token='1'), base_url='http://127.0.0.1:18743')
    headers = {'X-SAP-Lens': '1'}
    calls = {'roles': '/api/roles?limit=50', 'users page': '/api/access/users?limit=50', 'users filtered': '/api/access/users?limit=50&groups=G3&search=USER001',
             'users sorted': '/api/access/users?limit=50&sort=username', 'user detail': '/api/access/users/USER00042', 'dashboard': '/api/dashboard'}
    report = {}
    for label, url in calls.items():
        client.get(url, headers=headers)
        samples = []
        for _ in range(5):
            began = time.perf_counter()
            response = client.get(url, headers=headers)
            samples.append((time.perf_counter() - began) * 1000)
        report[label] = dict(status=response.status_code, ms=round(statistics.median(samples), 1), bytes=len(response.content))
        if os.environ.get('SAP_LENS_BENCH_PROFILE'):
            profiler = cProfile.Profile()
            profiler.runcall(client.get, url, headers=headers)
            print(f'--- {label}', file=sys.stderr)
            pstats.Stats(profiler, stream=sys.stderr).sort_stats('cumulative').print_stats('sap-lens/backend', 14)
    state = cache.get_snapshot()
    print(json.dumps(dict(scenario='api', api=report, peak_mb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024), users=len(state.users.users))))


def size(path):
    path = Path(path)
    return sum(p.stat().st_size for p in path.rglob('*') if p.is_file()) if path.is_dir() else (path.stat().st_size if path.exists() else 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--roles', type=int, default=400)
    parser.add_argument('--users', type=int, default=4000)
    parser.add_argument('--assignments', type=int, default=12)
    parser.add_argument('--json')
    parser.add_argument('--profile', choices=['startup', 'startup-static', 'startup-static-warm', 'api'], help='print the top functions of one scenario')
    parser.add_argument('--employees', type=int, default=0, help='also import an Employee Directory with this many employees (matched to the first SAP users)')
    parser.add_argument('--api', action='store_true', help='also time the heavy read endpoints on a started instance')
    parser.add_argument('--child', nargs='+')
    options = parser.parse_args()
    if options.child:
        return child(*options.child)
    with tempfile.TemporaryDirectory(prefix='sap-lens-bench-') as folder:
        folder = Path(folder)
        catalogue, people, rows = generate(folder, options.roles, options.users, options.assignments)
        directory_csv = str(generate_directory(folder, options.employees)) if options.employees else ''
        data = folder / 'data'
        results = []
        sizes = {}
        for scenario in ('import', 'startup', 'startup-warm', 'refresh-users-changed', *(('api',) if options.api else ()), *(('refresh-directory-changed',) if options.employees else ()), 'startup-static', 'startup-static-warm'):
            environment = dict(os.environ, **({'SAP_LENS_BENCH_PROFILE': '1'} if options.profile == scenario else {}))
            run = subprocess.run([sys.executable, __file__, '--child', scenario, str(data), str(catalogue), str(people), *([directory_csv] if directory_csv else [])], capture_output=True, text=True, check=False, env=environment)
            if options.profile == scenario:
                print(run.stderr[-60000:], file=sys.stderr)
            if run.returncode:
                sys.exit(run.stderr[-2000:])
            results.append(json.loads(run.stdout.strip().splitlines()[-1]))
            if scenario == 'import':
                sizes = dict(data_mb=round(size(data) / 1e6, 1), snapshots_mb=round(size(data / 'csv-data') / 1e6, 1), store_mb=round(size(data / 'store') / 1e6, 1))
        report = dict(assignment_rows=rows, csv_mb=round((catalogue.stat().st_size + people.stat().st_size) / 1e6, 1), sizes_after_import=sizes, sizes_at_end=dict(data_mb=round(size(data) / 1e6, 1), snapshots_mb=round(size(data / 'csv-data') / 1e6, 1), store_mb=round(size(data / 'store') / 1e6, 1)), runs=results)
        print(json.dumps(report, indent=1))
        if options.json:
            Path(options.json).write_text(json.dumps(report, indent=1))


if __name__ == '__main__':
    main()
