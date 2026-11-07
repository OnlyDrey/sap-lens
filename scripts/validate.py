#!/usr/bin/env python3
"""Isolated local validation over run-tests.py: QUICK (fast), TARGETED (feature), REGRESSION and FULL with private storage, a log directory and a timeout."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]

def python_exe():
    """Python 3.12 x64 for every child command: this interpreter when it is 3.12, else the ready project .venv, never a silent fallback."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from build_system import python_env
    return python_env.test_interpreter(ROOT)

ALIASES={'reviews':['sod','account-review'],'imports':['data-sources'],'users':['user-access'],'shared-frontend':['shared-ui'], 'storage':['platform','sod','account-review'],'packaging':['deployment'],'SoD':['sod']}


LEVELS={'fast':'quick','quick':'quick','feature':'targeted','targeted':'targeted','regression':'regression','full':'full'}


def plan(level,areas,base,mapping):
    """run-tests.py arguments for a level. Selection itself lives in run-tests.py (import graphs and test-map.json); this wrapper adds
    isolated storage, a log directory and a timeout. Unmapped changes broaden the run there; they never skip tests."""
    profile=LEVELS[level]
    if profile in ('regression','full'):return [profile]
    if not areas:return [profile,'--base',base]
    selected=[]
    for area in areas:
        names=ALIASES.get(area,[area.lower()])
        if any(name not in mapping['features'] for name in names):raise ValueError('Unknown area: '+area)
        selected.extend(names)
    selected=sorted(set(selected))
    if profile=='targeted':
        pending=list(selected)
        while pending:
            for dependency in mapping.get('validation_dependencies',{}).get(pending.pop(),[]):
                if dependency not in selected:selected.append(dependency);pending.append(dependency)
        selected.sort()
    return [profile,*selected]


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
    parser.add_argument('--level',choices=sorted(LEVELS),default='quick',type=str.lower,help='quick (fast), targeted (feature), regression or full; see docs/development/TESTING.md#profiles')
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
    if LEVELS[args.level] in ('regression','full') and (args.area or args.grep or args.no_build):parser.error('REGRESSION and FULL cannot filter areas/tests or skip the build; use TARGETED for partial validation')
    if args.timeout is not None and args.timeout<1:parser.error('--timeout must be positive')
    args.timeout=args.timeout or {'quick':600,'targeted':1800,'regression':3600,'full':7200}[LEVELS[args.level]]
    mapping=json.loads((ROOT/'scripts/test-map.json').read_text())
    try:
        selection=plan(args.level,args.area,args.base,mapping)
    except ValueError as error:print(error,file=sys.stderr);return 2
    if args.plan:
        print(json.dumps(dict(level=args.level,profile=selection),indent=2));return 0
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output=ROOT/'build'/'validation'/stamp;output.mkdir(parents=True)
    log=output/'validation.log'
    with tempfile.TemporaryDirectory(prefix='sap-lens-validation-') as temporary:
        env=isolated_environment(Path(temporary))
        env['SAP_LENS_TEST_ARTIFACTS']=str(output/'browser')
        if args.reports:env['SAP_LENS_TEST_REPORTERS']='html,junit'
        command=[python_exe(),str(ROOT/'scripts/run-tests.py'),*selection,'--jobs',str(args.jobs),'--browser-jobs',str(args.browser_jobs),'--report',str(output/'summary.json'),'--log',str(output/'run-tests.log')]
        if args.grep:command+=['--grep',args.grep]
        if args.no_build:command+=['--no-build']
        commands=[command]
        for command in commands:
            code=execute(command,log,env,args.timeout)
            if code:print(f'{LEVELS[args.level].upper()}: FAILED ({code}); details: {log}');return code
    print(f'{LEVELS[args.level].upper()}: PASSED; summary/logs: {output}')
    return 0


if __name__=='__main__':sys.exit(main())
