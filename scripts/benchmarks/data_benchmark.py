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


def child(scenario, data, catalogue, people):
    os.environ.update(SAP_LENS_CONFIG_DIR=str(data), DATA_CSV_PATH='')
    sys.path.insert(0, str(BACKEND))
    import cache
    import config
    import csv_lifecycle
    settings = config.get_settings().model_copy(deep=True)
    settings.data_csv_path, settings.user_csv_path = catalogue, people
    if scenario.startswith('startup-static'):
        settings.source_modes.roles = settings.source_modes.users = 'static'  # restore from stored data only, no re-read of the CSV files
    if scenario == 'startup-static':  # first static start: switches the modes (not timed), then restores
        config.save_configuration(settings, settings.revision)
    started = time.perf_counter()
    if scenario == 'import':
        config.save_configuration(settings, settings.revision)
        csv_lifecycle.load(config.get_settings(), operation='refresh', strict=True)
    elif os.environ.get('SAP_LENS_BENCH_PROFILE'):
        import cProfile
        import pstats
        profiler = cProfile.Profile()
        profiler.runcall(csv_lifecycle.load, config.get_settings(), operation='startup', strict=True)
        pstats.Stats(profiler, stream=sys.stderr).sort_stats('cumulative').print_stats(14)
    else:
        csv_lifecycle.load(config.get_settings(), operation='startup', strict=True)
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
    print(json.dumps(dict(scenario=scenario, seconds=round(elapsed, 3), peak_mb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024), rss_mb=rss, rss_without_source_records_mb=without_records,
                          roles=len(state.roles), users=len(state.users.users), assignments=len(state.users.assignments))))


def size(path):
    path = Path(path)
    return sum(p.stat().st_size for p in path.rglob('*') if p.is_file()) if path.is_dir() else (path.stat().st_size if path.exists() else 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--roles', type=int, default=400)
    parser.add_argument('--users', type=int, default=4000)
    parser.add_argument('--assignments', type=int, default=12)
    parser.add_argument('--json')
    parser.add_argument('--profile', choices=['startup', 'startup-static', 'startup-static-warm'], help='print the top functions of one scenario')
    parser.add_argument('--child', nargs=4)
    options = parser.parse_args()
    if options.child:
        return child(*options.child)
    with tempfile.TemporaryDirectory(prefix='sap-lens-bench-') as folder:
        folder = Path(folder)
        catalogue, people, rows = generate(folder, options.roles, options.users, options.assignments)
        data = folder / 'data'
        results = []
        for scenario in ('import', 'startup', 'startup-warm', 'startup-static', 'startup-static-warm'):
            environment = dict(os.environ, **({'SAP_LENS_BENCH_PROFILE': '1'} if options.profile == scenario else {}))
            run = subprocess.run([sys.executable, __file__, '--child', scenario, str(data), str(catalogue), str(people)], capture_output=True, text=True, check=False, env=environment)
            if options.profile == scenario:
                print(run.stderr[-3500:], file=sys.stderr)
            if run.returncode:
                sys.exit(run.stderr[-2000:])
            results.append(json.loads(run.stdout.strip().splitlines()[-1]))
        report = dict(assignment_rows=rows, csv_mb=round((catalogue.stat().st_size + people.stat().st_size) / 1e6, 1), data_mb=round(size(data) / 1e6, 1),
                      snapshots_mb=round(size(data / 'csv-data') / 1e6, 1), cache_mb=round(size(data / 'cache') / 1e6, 1), store_mb=round(size(data / 'store') / 1e6, 1), runs=results)
        print(json.dumps(report, indent=1))
        if options.json:
            Path(options.json).write_text(json.dumps(report, indent=1))


if __name__ == '__main__':
    main()
