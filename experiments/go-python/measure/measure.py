"""Linux-only measurement harness for the Phase 0 experiment. Synthetic data, isolated temp dirs, bounded waits.

  python measure.py --runtime TREE [--pruned TREE] [--pyinstaller DIR] [--venv PYTHON] [--runs 5] [--json OUT]

Variants (all start the same SAP Lens backend through the same poc_backend entry, same handoff, same health check):
  venv-direct        repository virtualenv interpreter, no host
  bundled-direct     bundled CPython tree, no host
  bundled-host       bundled CPython tree supervised by the Go host
  bundled-host-pruned  pruned tree supervised by the Go host
  pyinstaller-direct PyInstaller onedir build of the same entry, no host (stand-in for the existing packaging approach)
'cold' is the FIRST run of a variant in this process (page cache is not dropped: no privilege to do so reliably); 'warm' is the median of the remaining runs.
Memory is the sum over the process tree read from /proc/<pid>/status (VmRSS sampled, VmHWM peak); shared pages are counted once per process, so totals overstate.
"""
import argparse
import json
import os
import re
import secrets
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT.parents[1]
HOST = ROOT / 'host' / 'bin' / 'saplens-host'


def tree_pids(root):
    found, queue = [root], [root]
    while queue:
        pid = queue.pop()
        for children in Path(f'/proc/{pid}/task').glob('*/children'):
            try:
                kids = [int(c) for c in children.read_text().split()]
            except OSError:
                continue
            found += kids
            queue += kids
    return found


def memory_kib(pids):
    rss = hwm = 0
    for pid in pids:
        try:
            status = dict(line.split(':', 1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
            rss += int(status.get('VmRSS', '0 kB').split()[0])
            hwm += int(status.get('VmHWM', '0 kB').split()[0])
        except (OSError, ValueError):
            pass
    return rss, hwm


def health(port, instance):
    request = urllib.request.Request(f'http://127.0.0.1:{port}/health')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=2) as response:
            return json.loads(response.read(8192)).get('instance_id') == instance
    except Exception:
        return False


def data_dir():
    directory = Path(tempfile.mkdtemp(prefix='poc-measure-'))
    (directory / '.sap-lens-poc').write_text('sap-lens-poc-v1\n')
    return directory


def run_direct(command, env_extra, cwd=None, idle=2.0):
    data = data_dir()
    capability, instance = secrets.token_urlsafe(32), secrets.token_hex(16)
    env = {'PATH': '/usr/bin:/bin', 'SAP_LENS_POC_DATA': str(data), **env_extra}
    started = time.perf_counter()
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env, cwd=cwd)
    process.stdin.write(json.dumps({'capability': capability, 'instance_id': instance}) + '\n')
    process.stdin.flush()
    port = json.loads(process.stdout.readline())['port']
    while not health(port, instance):
        if time.perf_counter() - started > 60:
            process.kill()
            raise SystemExit('not ready in 60 s')
        time.sleep(0.01)
    ready = time.perf_counter() - started
    return process, ready, process.pid, None


def run_host(runtime, idle=2.0):
    data = Path(tempfile.mkdtemp(prefix='poc-measure-')) / 'data'
    started = time.perf_counter()
    process = subprocess.Popen([str(HOST), '--runtime', str(runtime), '--data', str(data)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    line = process.stdout.readline()
    ready = time.perf_counter() - started
    if not line.startswith('READY'):
        process.kill()
        raise SystemExit(f'host not ready: {line!r}')
    return process, ready, process.pid, int(re.search(r'ms=(\d+)', line).group(1)) / 1000


def measure_once(launch, stop_mode, idle=2.0):
    process, ready, root, internal = launch()
    time.sleep(0.3)
    samples = []
    end = time.monotonic() + idle
    while time.monotonic() < end:
        samples.append(memory_kib(tree_pids(root)))
        time.sleep(0.1)
    pids = tree_pids(root)
    steady = samples[-1][0]
    peak = max(max(s[1] for s in samples), memory_kib(pids)[1])
    started = time.perf_counter()
    if stop_mode == 'signal':
        process.terminate()
    else:
        process.stdin.write('stop\n')
        process.stdin.flush()
        process.stdin.close()
    code = process.wait(timeout=30)
    shutdown = time.perf_counter() - started
    for stream in (process.stdout,):
        stream.close()
    return {'ready_s': round(ready, 3), 'host_internal_ready_s': internal, 'steady_rss_mib': round(steady / 1024, 1), 'peak_hwm_mib': round(peak / 1024, 1),
            'processes': len(pids), 'shutdown_s': round(shutdown, 3), 'exit_code': code}


def tree_size(path):
    total = files = 0
    for item in Path(path).rglob('*'):
        if item.is_file() and not item.is_symlink():
            total += item.stat().st_size
            files += 1
    return total, files


def summarise(rows):
    def med(key):
        values = [r[key] for r in rows if r[key] is not None]
        return round(statistics.median(values), 3) if values else None
    return {'cold': rows[0], 'warm_median': {k: med(k) for k in ('ready_s', 'steady_rss_mib', 'peak_hwm_mib', 'shutdown_s')},
            'warm_min_max_ready_s': [min(r['ready_s'] for r in rows[1:]), max(r['ready_s'] for r in rows[1:])] if len(rows) > 1 else None, 'exit_codes': sorted({r['exit_code'] for r in rows})}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--pruned')
    parser.add_argument('--pyinstaller')
    parser.add_argument('--venv')
    parser.add_argument('--runs', type=int, default=6)
    parser.add_argument('--json')
    args = parser.parse_args()
    variants = {}
    if args.venv:
        env = {'PYTHONPATH': f'{ROOT / "backend"}:{REPOSITORY / "backend"}'}
        variants['venv-direct'] = (lambda: run_direct([args.venv, '-m', 'poc_backend'], env, cwd=str(REPOSITORY / 'backend')), 'stdin', None)
    runtime = Path(args.runtime)
    python = runtime / 'python' / 'bin' / 'python3'
    variants['bundled-direct'] = (lambda: run_direct([str(python), '-I', '-m', 'poc_backend'], {}), 'stdin', runtime)
    variants['bundled-host'] = (lambda: run_host(runtime), 'signal', runtime)
    if args.pruned:
        variants['bundled-host-pruned'] = (lambda: run_host(args.pruned), 'signal', Path(args.pruned))
    if args.pyinstaller:
        exe = Path(args.pyinstaller) / 'poc_pyi'
        variants['pyinstaller-direct'] = (lambda: run_direct([str(exe)], {}), 'stdin', Path(args.pyinstaller))
    result = {'machine': {'cpus': os.cpu_count(), 'kernel': os.uname().release, 'python_harness': sys.version.split()[0]}, 'runs_per_variant': args.runs, 'variants': {}}
    for name, (launch, stop_mode, tree) in variants.items():
        rows = [measure_once(launch, stop_mode) for _ in range(args.runs)]
        entry = summarise(rows)
        if tree:
            size, files = tree_size(tree)
            entry['tree_bytes'], entry['tree_files'] = size, files
        result['variants'][name] = entry
        print(name, json.dumps(entry['warm_median']), 'cold ready', entry['cold']['ready_s'], flush=True)
    result['host_binary_bytes'] = HOST.stat().st_size
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
