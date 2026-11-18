"""Bounded, logged subprocess execution and shared failures."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]

class BuildError(Exception):
    def __init__(self,message,code=2):
        super().__init__(message)
        self.code=code


class StageProgress:
    """Named start/end events and bounded heartbeats, without streaming private child output."""
    def __init__(self, name, log, stream=None, follow=False, interval=15):
        self.name, self.log = name, Path(log)
        self.stream = stream if stream is not None else sys.stdout
        self.follow, self.interval = follow, interval
        self.exit_code = 0
        self.stop = threading.Event()
        self.offset = 0
        self.pending = ''

    def emit(self, state):
        print(f'[build-stage] {state} | {self.name} | elapsed {time.monotonic()-self.started:.1f}s | Log: {self.log}', file=self.stream, flush=True)

    def relay(self):
        if not self.follow:
            return
        try:
            with self.log.open(encoding='utf-8', errors='replace') as source:
                source.seek(self.offset)
                content = source.read()
                self.offset = source.tell()
        except OSError:
            return
        lines = (self.pending + content).split('\n')
        self.pending = lines.pop()[-4096:]
        for line in lines:
            # Only authored progress markers; detailed subprocess output stays in logs.
            if line.startswith('[build-stage] '):
                print(line, file=self.stream, flush=True)

    def watch(self):
        next_heartbeat = self.started + self.interval
        while not self.stop.wait(.25):
            self.relay()
            if time.monotonic() >= next_heartbeat:
                self.emit('RUNNING')
                next_heartbeat = time.monotonic() + self.interval

    def __enter__(self):
        self.started = time.monotonic()
        self.emit('START')
        self.thread = threading.Thread(target=self.watch, name='build-progress', daemon=True)
        self.thread.start()
        return self

    def __exit__(self, kind, error, traceback):
        self.stop.set()
        self.thread.join()
        self.relay()
        self.seconds = round(time.monotonic()-self.started, 3)
        self.emit('FAILED' if kind or self.exit_code else 'PASS')


class Runner:
    def __init__(self,root=ROOT,verbose=False):
        self.root=root
        self.verbose=verbose
        self.machine_readable=False
        self.directory=None
        self.last_output=None

    def run(self,name,command,timeout=1800):
        if self.directory is None:
            self.directory=self.root/'backend/build/unified'/uuid.uuid4().hex
            self.directory.mkdir(parents=True)
        started=time.monotonic()
        output=self.directory/(str(time.time_ns())+'.log')
        self.last_output=output
        print(name,file=sys.stderr if self.machine_readable else sys.stdout,flush=True)
        ci=os.environ.get('GITHUB_ACTIONS')=='true'
        try:
            with StageProgress(name, output, stream=sys.stderr if self.machine_readable else sys.stdout, follow=not ci) as progress:
                with output.open('w',encoding='utf-8') as log:
                    result=subprocess.run([str(item) for item in command],cwd=self.root,stdin=subprocess.DEVNULL if self.machine_readable else None,stdout=(sys.stderr if self.machine_readable else None) if ci else log,stderr=None if ci else subprocess.STDOUT,timeout=timeout,env={**os.environ,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'})
                code=result.returncode
                progress.exit_code=code
        except (OSError,subprocess.TimeoutExpired) as error:
            code=3 if isinstance(error,OSError) else 124
        with (self.directory/'events.jsonl').open('a',encoding='utf-8') as log:
            log.write(json.dumps(dict(timestamp=datetime.now(timezone.utc).isoformat(),operation=name,exit_code=code,seconds=round(time.monotonic()-started,3),output=output.name))+'\n')
        if (self.verbose or code) and not ci:
            print('\n'.join(output.read_text(encoding='utf-8',errors='replace').splitlines()[-20:]),file=sys.stderr if self.machine_readable else sys.stdout)
        if code:
            raise BuildError(f'{name} failed (exit {code}). Logs: {self.directory}',code)
        return code
