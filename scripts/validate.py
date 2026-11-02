#!/usr/bin/env python3
"""FAST/FEATURE/FULL local policy over the existing run-tests.py engine."""
import argparse
from datetime import datetime, timezone
import fnmatch
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
ALIASES={'reviews':['sod','account-review'],'imports':['data-sources'],'users':['user-access'],'shared-frontend':['shared-ui'], 'storage':['platform','sod','account-review'],'packaging':['deployment'],'SoD':['sod']}


def changed(base):
    result=subprocess.run(['git','diff','--name-only',base],cwd=ROOT,capture_output=True,text=True)
    if result.returncode: raise ValueError('Unusable base commit. Choose --base or an explicit --area; FULL is never selected automatically.')
    extra=subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=ROOT,text=True)
    return sorted(set(result.stdout.splitlines()+extra.splitlines()))


def areas_for(paths,mapping):
    areas=set();unknown=[]
    for path in paths:
        if path.startswith('docs/') or path.endswith('.md'): continue
        owners=[name for name,feature in mapping['features'].items() if path in [f'backend/tests/{m}.py' for m in feature['backend']]+[f'frontend/tests/{s}.spec.ts' for s in feature['browser']]]
        if owners: areas.update(owners);continue
        match=next((rule for rule in mapping['validation_sources'] if any(fnmatch.fnmatchcase(path,pattern) for pattern in rule['patterns'])),None)
        if match:areas.update(match['areas'])
        else:unknown.append(path)
    if unknown:raise ValueError('Unmapped changes: '+', '.join(unknown)+'. Select --area explicitly, extend test-map.json, or request --level full. No tests silently omitted.')
    return sorted(areas)


def plan(level,areas,paths,mapping):
    selected=[]
    for area in areas:
        names=ALIASES.get(area,[area.lower()])
        if any(name not in mapping['features'] for name in names):raise ValueError('Unknown area: '+area)
        selected.extend(names)
    selected=sorted(set(selected)) or areas_for(paths,mapping)
    if level=='feature':
        pending=list(selected)
        while pending:
            for dependency in mapping.get('validation_dependencies',{}).get(pending.pop(),[]):
                if dependency not in selected:selected.append(dependency);pending.append(dependency)
        selected.sort()
    if level=='full':return ['regression']
    if not selected:return []
    return ['targeted',*selected,*(['--backend'] if level=='fast' else [])]


def isolated_environment(folder):
    # Never inherit production/server paths or authentication into local tests.
    env={key:value for key,value in os.environ.items() if not key.startswith('SAP_LENS_') and key!='DATA_CSV_PATH'}
    env.update(SAP_LENS_DEPLOYMENT_MODE='desktop',SAP_LENS_CONFIG_DIR=str(folder/'config'),SAP_LENS_DATA_DIR=str(folder/'data'),SAP_LENS_SOURCE_DIR=str(folder/'sources'),DATA_CSV_PATH='',TMPDIR=str(folder),TEMP=str(folder),TMP=str(folder))
    return env


def execute(command,log,env,timeout):
    with log.open('a',encoding='utf-8') as stream:
        process=subprocess.Popen(command,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
        try:return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # run-tests owns its children and handles termination. Escalate only
            # our process tree if graceful cleanup cannot finish.
            process.terminate()
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=stream,stderr=stream)
                process.kill();process.wait()
            stream.write('\nValidation timed out.\n');return 124


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--level',choices=['fast','feature','full'],default='fast',type=str.lower)
    parser.add_argument('--area',action='append',default=[])
    parser.add_argument('--base',default='HEAD')
    parser.add_argument('--jobs',type=int,choices=[1,2,3],default=1)
    parser.add_argument('--browser-jobs',type=int,choices=[1,2,3],default=1)
    parser.add_argument('--grep')
    parser.add_argument('--no-build',action='store_true')
    parser.add_argument('--plan',action='store_true')
    parser.add_argument('--reports',action='store_true',help='Preserve browser HTML and JUnit alongside JSON/traces')
    parser.add_argument('--timeout',type=int,help='Per-stage limit; defaults FAST 600, FEATURE 1800, FULL 7200 seconds')
    args=parser.parse_args(argv)
    if args.timeout is not None and args.timeout<1:parser.error('--timeout must be positive')
    args.timeout=args.timeout or {'fast':600,'feature':1800,'full':7200}[args.level]
    mapping=json.loads((ROOT/'scripts/test-map.json').read_text())
    try:
        paths=changed(args.base) if not args.area and args.level!='full' else []
        selection=plan(args.level,args.area,paths,mapping)
    except ValueError as error:print(error,file=sys.stderr);return 2
    if args.plan:
        print(json.dumps(dict(level=args.level,paths=paths,profile=selection),indent=2));return 0
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output=ROOT/'build'/'validation'/stamp;output.mkdir(parents=True)
    log=output/'validation.log'
    with tempfile.TemporaryDirectory(prefix='sap-lens-validation-') as temporary:
        env=isolated_environment(Path(temporary))
        env['SAP_LENS_TEST_ARTIFACTS']=str(output/'browser')
        if args.reports:env['SAP_LENS_TEST_REPORTERS']='html,junit'
        commands=[]
        if selection:
            command=[sys.executable,str(ROOT/'scripts/run-tests.py'),*selection,'--jobs',str(args.jobs),'--browser-jobs',str(args.browser_jobs),'--report',str(output/'summary.json')]
            if args.grep:command+=['--grep',args.grep]
            if args.no_build:command+=['--no-build']
            commands.append(command)
        else:commands.append([sys.executable,'scripts/check-docs.py'])
        if args.level=='fast':
            commands.append([sys.executable,'-m','ruff','check','backend','scripts'])
            if any(path.startswith('frontend/src/') for path in paths) or args.area:
                import shutil
                commands.append([shutil.which('npm') or 'npm','--prefix','frontend','run','check:types'])
        for command in commands:
            code=execute(command,log,env,args.timeout)
            if code:print(f'{args.level.upper()}: FAILED ({code}); details: {log}');return code
    print(f'{args.level.upper()}: PASSED; summary/logs: {output}')
    return 0


if __name__=='__main__':sys.exit(main())
