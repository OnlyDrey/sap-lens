"""Language-level benchmark: the PRODUCTION Python v1 functions on the large synthetic dataset, in one process, no HTTP and no storage.
The .NET counterpart is `AuthLens.Cli bench --data DIR --out FILE`; both write the same JSON shape for tools/bench_report.py.

  python -I bench_algorithms.py --data DATASETS_DIR --out python-bench.json"""
import argparse
import json
import resource
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import python_reference as ref  # noqa: E402  (sets an isolated SAP_LENS_CONFIG_DIR before importing backend modules)
from config_models import UserImportProfile  # noqa: E402

QUERIES = {
    'role_lookup_text': {'search': 'ROLE_01*'},
    'role_lookup_tcodes_or': {'tcodes': ['T0010', 'T0020', 'T0030'], 'transaction_mode': 'or'},
    'role_lookup_area': {'function_keys': ['FI', 'MM']},
}
USER_QUERIES = {
    'user_lookup_all': {},
    'user_lookup_tcode': {'tcodes': ['T0010'], 'show_expired': True},
    'user_lookup_search': {'search': 'user0001*'},
}


def timed(runs, action):
    samples, result = [], None
    for _ in range(runs):
        started = time.perf_counter()
        result = action()
        samples.append(round((time.perf_counter() - started) * 1000, 2))
    return samples, result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--dataset', default='large')
    args = parser.parse_args()
    base = Path(args.data) / args.dataset
    out = {}
    out['catalogue_build'], state = timed(3, lambda: ref.cache._build_catalog(path=str(base / 'roles.csv')))
    out['users_build'], users = timed(3, lambda: ref.build_users(str(base / 'users.csv'), UserImportProfile(id='default', name='x'), state.roles))
    out['sod_parse'], sod = timed(3, lambda: ref.parse_sod(str(base / 'sod.csv')))
    state.users, state.sod, state.directory = users, sod, None
    ref.cache._cache = state
    for name, query in QUERIES.items():
        out[name], _ = timed(7, lambda q=query: ref.role_lookup(q))
    for name, query in USER_QUERIES.items():
        out[name], _ = timed(7, lambda q=query: ref.user_lookup(state, q))
    out['compare'], _ = timed(7, lambda: ref.user_comparison._compare(state, 'USER00001', 'USER00008', 'all'))
    out['sod_analyze'], result = timed(3, lambda: ref.sod_analysis.analyze(state, {}, ref.TODAY, 'active', None))
    summary = {'implementation': 'python-v1', 'python': sys.version.split()[0], 'operations': out,
               'sod_user_findings': len(result['users']), 'peak_rss_mb': round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)}
    Path(args.out).write_text(json.dumps(summary, indent=1))
    for name, samples in out.items():
        print(f'{name:24} first {samples[0]:>9.1f} ms   median(rest) {statistics.median(samples[1:]):>9.1f} ms')
    print(f"peak RSS {summary['peak_rss_mb']} MB")


if __name__ == '__main__':
    main()
