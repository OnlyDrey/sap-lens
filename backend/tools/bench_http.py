"""Service-level benchmark: Python v1 (production backend, unchanged, via run_python_v1.py) versus the .NET prototype server (self-contained publish),
same machine, same synthetic files, loopback HTTP. Measures startup, readiness, data-ready time, memory, CPU, latency under concurrency with and
without a concurrent large import, and shutdown time. Writes JSON for the documentation; prints a summary.

  python -I bench_http.py --data DATASETS_DIR --dotnet PUBLISHED_SERVER_DIR --out http-bench.json [--clients 15] [--seconds 15]"""
import argparse
import http.client
import json
import os
import random
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
PYTHON = sys.executable
TOKEN = 'bench-' + 'x' * 40


def proc_stats(pid):
    stats = {}
    for line in Path(f'/proc/{pid}/status').read_text().splitlines():
        key, _, value = line.partition(':')
        if key in ('VmRSS', 'VmHWM'):
            stats[key] = round(int(value.split()[0]) / 1024, 1)
    fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    stats['cpu_s'] = round((int(fields[11]) + int(fields[12])) / os.sysconf('SC_CLK_TCK'), 2)
    return stats


class Server:
    def __init__(self, kind, port, workdir, dotnet_dir, roles='', users=''):
        self.kind, self.port = kind, port
        if kind == 'python':
            cmd = [PYTHON, '-I', str(TOOLS / 'run_python_v1.py'), '--port', str(port), '--token', TOKEN, '--config-dir', str(workdir)]
            if roles: cmd += ['--roles', roles, '--users', users]
            env = {**os.environ}
            self.header = 'X-SAP-Lens'
        else:
            cmd = [str(Path(dotnet_dir) / 'AuthLens.Api'), '--data-dir', str(workdir), '--port', str(port)]
            env = {**os.environ, 'AUTHLENS_TOKEN': TOKEN, 'Logging__LogLevel__Default': 'Warning'}
            self.header = 'X-SAP-Lens-Token'
        self.started = time.perf_counter()
        self.process = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def request(self, method, path, body=None, headers=None, timeout=120):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=timeout)
        try:
            connection.request(method, path, body=body, headers={self.header: TOKEN, **(headers or {})})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def wait_ready(self, limit=180):
        while time.perf_counter() - self.started < limit:
            try:
                if self.request('GET', '/health/ready', timeout=2)[0] == 200:
                    return round((time.perf_counter() - self.started) * 1000)
            except OSError:
                pass
            if self.process.poll() is not None:
                raise RuntimeError(f'{self.kind} exited with {self.process.returncode}')
            time.sleep(0.02)
        raise TimeoutError(f'{self.kind} not ready')

    def stats(self):
        return proc_stats(self.process.pid)

    def stop(self):
        started = time.perf_counter()
        self.process.send_signal(signal.SIGTERM)
        try:
            self.process.wait(30)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
            return None
        return round((time.perf_counter() - started) * 1000)


def dotnet_import(server, source, path):
    status, body = server.request('POST', f'/api/v1/imports/{source}', body=Path(path).read_bytes(), headers={'Content-Type': 'text/csv'})
    assert status == 202, body
    job = json.loads(body)['id']
    while True:
        status, body = server.request('GET', f'/api/v1/jobs/{job}')
        state = json.loads(body)
        if state['status'] in ('Completed', 'Failed', 'Cancelled'):
            return state
        time.sleep(0.05)


def assignment_keys(users_csv, count=3000):
    keys = []
    with open(users_csv, encoding='utf-8') as stream:
        next(stream)
        for line in stream:
            user, role = line.split(';')[:2]
            if role.strip():
                keys.append(user.strip().upper() + '\x1f' + ''.join(role.split()).upper())
            if len(keys) >= count:
                break
    return keys


def operations(kind):
    users = [f'USER{n:05d}' for n in range(1, 2000)]
    if kind == 'python':
        return {
            'role_search': lambda r: f'/api/roles?search=ROLE_0{r.randint(10, 99)}',
            'user_page': lambda r: f'/api/access/users?offset={r.randint(0, 19000)}&limit=50',
            'user_tcode': lambda r: f'/api/access/users?tcodes=T{r.randint(0, 2999):04d}&show_expired=true&limit=50',
            'compare': lambda r: f'/api/user-comparison?user_a={r.choice(users)}&user_b={r.choice(users)}&validity=all',
        }
    return {
        'role_search': lambda r: f'/api/v1/roles?search=ROLE_0{r.randint(10, 99)}&limit=50',
        'user_page': lambda r: f'/api/v1/users?offset={r.randint(0, 19000)}&limit=50',
        'user_tcode': lambda r: f'/api/v1/users?tcode=T{r.randint(0, 2999):04d}&show_expired=true&limit=50',
        'compare': lambda r: f'/api/v1/users/compare?left={r.choice(users)}&right={r.choice(users)}&validity=all&limit=50',
    }


def load(server, clients, seconds, writers=0, keys=(), during=None):
    """`clients` threads for `seconds`; the first `writers` threads post review decisions (.NET only). `during` runs in its own thread at t=2 s."""
    ops = operations(server.kind)
    samples = {name: [] for name in [*ops, 'review_write']}
    outcomes = {'ok': 0, 'client_error': 0, 'server_error': 0, 'failed': 0}
    lock = threading.Lock()
    stop = time.perf_counter() + seconds
    extra = {}

    def client(index):
        rng = random.Random(index)
        while time.perf_counter() < stop:
            if index < writers:
                name, method, path = 'review_write', 'POST', '/api/v1/reviews'
                body = json.dumps({'subject_type': 'assignment', 'subject_key': rng.choice(keys), 'decision': 'approved', 'comment': 'bench'}).encode()
                headers = {'Content-Type': 'application/json'}
            else:
                name = rng.choice(list(ops))
                method, path, body, headers = 'GET', ops[name](rng), None, None
            started = time.perf_counter()
            try:
                status, _ = server.request(method, path, body=body, headers=headers, timeout=60)
                kind = 'ok' if status < 400 else 'client_error' if status < 500 else 'server_error'
            except OSError:
                kind = 'failed'
            elapsed = (time.perf_counter() - started) * 1000
            with lock:
                outcomes[kind] += 1
                if kind in ('ok', 'client_error'):
                    samples[name].append(elapsed)

    def background():
        time.sleep(2)
        started = time.perf_counter()
        extra['result'] = during()
        extra['import_ms'] = round((time.perf_counter() - started) * 1000)

    threads = [threading.Thread(target=client, args=(i,)) for i in range(clients)]
    if during:
        threads.append(threading.Thread(target=background))
    started = time.perf_counter()
    for t in threads: t.start()
    for t in threads: t.join()
    duration = time.perf_counter() - started

    def pct(values, p):
        if not values: return None
        values = sorted(values)
        return round(values[min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))], 1)
    everything = [v for name, values in samples.items() for v in values]
    report = {name: dict(n=len(v), p50=pct(v, 50), p95=pct(v, 95), p99=pct(v, 99)) for name, v in samples.items() if v}
    report['all'] = dict(n=len(everything), p50=pct(everything, 50), p95=pct(everything, 95), p99=pct(everything, 99), throughput_rps=round(len(everything) / duration, 1))
    return dict(latency_ms=report, outcomes=outcomes, **extra)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True)
    parser.add_argument('--dotnet', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--clients', type=int, default=15)
    parser.add_argument('--seconds', type=int, default=15)
    args = parser.parse_args()
    data = Path(args.data)
    work = Path(tempfile.mkdtemp(prefix='saplens-bench-'))
    results = {'clients': args.clients, 'seconds': args.seconds, 'cpus': os.cpu_count()}
    port = 18820
    for kind in ('python', 'dotnet'):
        port += 1
        result = results[kind] = {}
        # 1. Empty startup: run 1 on a fresh directory (cold), runs 2-5 on the same directory (warm).
        empty = work / f'{kind}-empty'
        empty.mkdir()
        runs = []
        for _ in range(5):
            server = Server(kind, port, empty, args.dotnet)
            ready = server.wait_ready()
            stats = server.stats()
            runs.append(dict(ready_ms=ready, rss_mb=stats['VmRSS'], shutdown_ms=server.stop()))
        result['empty_startup'] = runs
        # 2. Data ready from CSVs (first start) and after a restart with existing data.
        loaded = work / f'{kind}-loaded'
        loaded.mkdir()
        csv_dir = work / f'{kind}-csv'
        csv_dir.mkdir()
        for name in ('roles.csv', 'users.csv', 'sod.csv'):
            shutil.copy(data / 'large' / name, csv_dir / name)
        roles, users = str(csv_dir / 'roles.csv'), str(csv_dir / 'users.csv')
        server = Server(kind, port, loaded, args.dotnet, roles, users)
        ready = server.wait_ready()
        if kind == 'dotnet':
            imports = {source: dotnet_import(server, source, csv_dir / f'{source}.csv')['status'] for source in ('roles', 'users', 'sod')}
        else:
            imports = {}
        status, _ = server.request('GET', '/api/v1/roles?limit=1' if kind == 'dotnet' else '/api/roles?search=ROLE_00001')
        result['first_load'] = dict(ready_ms=ready, data_ready_ms=round((time.perf_counter() - server.started) * 1000), first_query_status=status, imports=imports, **server.stats())
        result['first_load']['shutdown_ms'] = server.stop()
        server = Server(kind, port, loaded, args.dotnet, roles, users)
        ready = server.wait_ready()
        status, _ = server.request('GET', '/api/v1/roles?limit=1' if kind == 'dotnet' else '/api/roles?search=ROLE_00001')
        result['restart'] = dict(ready_ms=ready, data_ready_ms=round((time.perf_counter() - server.started) * 1000), first_query_status=status, **server.stats())
        # 3. Concurrency on the loaded server: steady state, then with a large users import running at the same time.
        for op in operations(kind).values():  # warm every endpoint once
            server.request('GET', op(random.Random(0)))
        keys = assignment_keys(data / 'large' / 'users.csv') if kind == 'dotnet' else ()
        writers = 3 if kind == 'dotnet' else 0
        result['steady'] = load(server, args.clients, args.seconds, writers, keys)
        changed = data / 'large-changed' / 'users.csv'
        if kind == 'dotnet':
            during = lambda server=server, changed=changed: dotnet_import(server, 'users', changed)['status']  # noqa: E731
        else:
            def during(server=server, changed=changed, users=users):
                shutil.copy(changed, users)
                status, body = server.request('POST', '/api/refresh', timeout=600)
                return status
        result['during_import'] = load(server, args.clients, args.seconds + 10, writers, keys, during)
        result['after'] = server.stats()
        result['shutdown_loaded_ms'] = server.stop()
        print(json.dumps({kind: {k: v for k, v in result.items() if k in ('first_load', 'restart', 'after', 'shutdown_loaded_ms')}}, indent=1))
        print(kind, 'steady', json.dumps(result['steady']['latency_ms']['all']), 'during import', json.dumps(result['during_import']['latency_ms']['all']),
              result['during_import'].get('import_ms'), result['during_import']['outcomes'])
    Path(args.out).write_text(json.dumps(results, indent=1))
    shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
