"""Shared helpers for the experiment tests. Synthetic data only; every run uses its own temporary directory."""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))
HOST = Path(os.environ.get('POC_HOST', ROOT / 'host' / 'bin' / 'saplens-host'))
RUNTIME = Path(os.environ.get('POC_RUNTIME', '/tmp/poc-linux'))
NAVIGATE = {'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'document', 'Sec-Fetch-Site': 'none'}


def need_runtime(case):
    if sys.platform == 'win32' or not HOST.is_file() or not (RUNTIME / 'manifest.json').is_file():
        raise unittest.SkipTest('needs POC_HOST binary and an assembled POC_RUNTIME tree on Linux')


def request(url, headers=None, timeout=5):
    """(status, body); redirects are not followed so they stay visible."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
    try:
        with opener.open(urllib.request.Request(url, headers=headers or {}), timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def children_of(pid):
    """All descendants by walking /proc (Linux)."""
    found, queue = [], [pid]
    while queue:
        current = queue.pop()
        for task in Path(f'/proc/{current}/task').glob('*/children'):
            for child in task.read_text().split():
                found.append(int(child))
                queue.append(int(child))
    return found


def alive(pid):
    try:
        text = Path(f'/proc/{pid}/stat').read_text()
    except OSError:
        return False
    return text.rsplit(')', 1)[1].split()[0] != 'Z'


def wait_gone(pid, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.05)
    return not alive(pid)


class Host:
    """A running host process. Usage: `with Host(...) as h:` then h.url, h.backend_pid."""

    def __init__(self, data=None, extra=(), runtime=None):
        self.temp = tempfile.TemporaryDirectory(prefix='poc-test-')
        self.data = data or str(Path(self.temp.name) / 'data')
        self.args = [str(HOST), '--runtime', str(runtime or RUNTIME), '--data', self.data, *extra]

    def start(self, wait_ready=True):
        self.process = subprocess.Popen(self.args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.url = self.backend_pid = None
        if wait_ready:
            line = self.process.stdout.readline()
            match = re.match(r'READY url=(\S+) pid=(\d+)', line)
            if not match:
                self.process.kill()
                raise AssertionError(f'host not ready: {line!r} {self.process.stderr.read()!r}')
            self.url, self.backend_pid = match.group(1).rstrip('/'), int(match.group(2))
        return self

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()
        for stream in (self.process.stdout, self.process.stderr):
            stream.close()
        self.temp.cleanup()
