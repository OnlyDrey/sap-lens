"""Bounded, logged subprocess execution and shared failures."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]

class BuildError(Exception):
    def __init__(self,message,code=2):
        super().__init__(message)
        self.code=code

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
            with output.open('w',encoding='utf-8') as log:
                result=subprocess.run([str(item) for item in command],cwd=self.root,stdin=subprocess.DEVNULL if self.machine_readable else None,stdout=(sys.stderr if self.machine_readable else None) if ci else log,stderr=None if ci else subprocess.STDOUT,timeout=timeout,env={**os.environ,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8'})
            code=result.returncode
        except (OSError,subprocess.TimeoutExpired) as error:
            code=3 if isinstance(error,OSError) else 124
        with (self.directory/'events.jsonl').open('a',encoding='utf-8') as log:
            log.write(json.dumps(dict(timestamp=datetime.now(timezone.utc).isoformat(),operation=name,exit_code=code,seconds=round(time.monotonic()-started,3),output=output.name))+'\n')
        if (self.verbose or code) and not ci:
            print('\n'.join(output.read_text(encoding='utf-8',errors='replace').splitlines()[-20:]),file=sys.stderr if self.machine_readable else sys.stdout)
        if code:
            raise BuildError(f'{name} failed (exit {code}). Logs: {self.directory}',code)
        return code
