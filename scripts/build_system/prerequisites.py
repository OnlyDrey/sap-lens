"""Standard-library detection and consented setup; never installs system tools implicitly."""
import json
import os
import re
import shutil
import subprocess
import sys
from .runner import ROOT, BuildError

def locate(name):
    return shutil.which(name)

def inspect_tool(name):
    path=locate(name)
    if not path:return None
    arguments={'node':['-p','process.versions.node'],'npm':['--version'],'git':['--version'],'docker':['--version']}
    try:
        value=subprocess.check_output([path,*arguments[name]],text=True,stderr=subprocess.DEVNULL,timeout=15).strip()
    except (OSError,subprocess.SubprocessError):return None
    if name in ('node','npm'):
        match=re.match(r'^(\d+)\.',value)
        node_range=re.fullmatch(r'>=(\d+) <(\d+)',json.loads((ROOT/'frontend/package.json').read_text())['engines']['node'])
        if not node_range:raise BuildError('Unsupported Node engine declaration; update the build detector with the project configuration.')
        supported=range(int(node_range[1]),int(node_range[2])) if name=='node' else (10,11)
        if not match or int(match[1]) not in supported:
            raise BuildError(f'Incompatible {name}: use Node 24/25 and npm 10/11 from project configuration.',3)
    return path

def install_system(name,runner,consent=False,interactive=False,prompt=input):
    if os.name!='nt' or name not in ('git','node') or not locate('winget'):
        raise BuildError(f'Install {name} through your approved platform tools, then reopen the terminal. Automatic setup requires Windows winget; Docker setup is manual.',3)
    if not consent and (not interactive or prompt(f'Install {name} for this user using winget? [y/N] ').strip().lower() not in ('y','yes')):
        raise BuildError(f'{name} is missing; installation declined or not authorized. Install it manually or explicitly opt in with --install-system.',3)
    package={'git':'Git.Git','node':'OpenJS.NodeJS.LTS'}[name]
    command=[locate('winget'),'install','--id',package,'--exact','--source','winget','--scope','user','--accept-source-agreements','--accept-package-agreements','--disable-interactivity']
    if name=='node':
        try:
            versions=subprocess.check_output([locate('winget'),'show','--id',package,'--exact','--source','winget','--versions','--accept-source-agreements'],text=True,timeout=60)
        except (OSError,subprocess.SubprocessError) as error:
            raise BuildError('Cannot resolve a supported Node 24 version from winget. Use the approved Node 24 installer.',3) from error
        available=re.findall(r'^\s*(24\.\d+\.\d+)\s*$',versions,re.M)
        if not available:raise BuildError('winget has no supported Node 24 version; do not install an unrelated latest major. Use approved manual setup.',3)
        command+=['--version',max(available,key=lambda value:tuple(map(int,value.split('.'))))]
    runner.run('Install approved per-user '+name,command,timeout=600)
    # PATH can remain stale after a system installer. Never claim success based only on its exit code.
    if not inspect_tool(name):raise BuildError(f'{name} installed but is not available in this process. Reopen the terminal and retry.',3)

def check_tools(args,runner,interactive):
    if sys.version_info<(3,12):raise BuildError('Use Python 3.12 or newer for this CLI; package builds require Python 3.12.',3)
    if args.mode in ('build','package') and sys.version_info[:2]!=(3,12):raise BuildError('The existing packaging toolchain requires Python 3.12 x64.',3)
    names=[] if args.mode=='clean' else ['git'] if args.mode=='release' else ['git','node','npm']
    if args.platform in ('docker','all') and args.mode in ('build','package'):names+=['docker']
    if args.mode in ('build','package') and not (locate('pwsh') or os.name=='nt' and locate('powershell')):
        raise BuildError('Packaging validation requires PowerShell 7 on Linux or PowerShell 5.1/7 on Windows. Install it through approved tools.',3)
    for name in names:
        if inspect_tool(name):continue
        if name=='npm' and inspect_tool('node'):
            raise BuildError('npm is missing. Repair the supported Node installation and reopen the terminal.',3)
        if args.skip_setup:raise BuildError(f'Missing {name}; --skip-setup forbids setup. Install the documented prerequisite.',3)
        install_system(name,runner,args.install_system,interactive)
    if args.platform in ('docker','all') and args.mode in ('build','package'):
        runner.run('Check Docker Compose',[locate('docker'),'compose','version'],timeout=30)

def prepare_environment(root,runner,*,packaging=False,frontend=True):
    if sys.version_info[:2]!=(3,12):raise BuildError('Project setup requires Python 3.12 to match the locked toolchain.',3)
    directory=root/('backend/build/python-env' if packaging else '.venv')
    if directory.is_symlink():raise BuildError('The project Python environment must not be a link.',3)
    python=directory/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if directory.exists() and not python.is_file():raise BuildError('Project environment is incomplete. Review/remove only that generated environment, then retry setup.',3)
    if not python.exists():runner.run('Create project-local Python environment',[sys.executable,'-m','venv',directory])
    try:
        info=json.loads(subprocess.check_output([str(python),'-c','import sys,json; print(json.dumps(list(sys.version_info[:2])))'],text=True,timeout=15))
    except (OSError,ValueError,subprocess.SubprocessError) as error:raise BuildError('Cannot inspect the project Python environment. Repair it using Python 3.12.',3) from error
    if info!=[3,12]:raise BuildError('Project environment uses another Python version; preserve/recreate it using Python 3.12.',3)
    runner.run('Repair/ensure local pip',[python,'-m','ensurepip'])
    requirements=['-r','backend/requirements-dev.txt']
    if packaging:requirements+=['-r','backend/requirements-build.txt']
    runner.run('Install locked project Python dependencies',[python,'-m','pip','install',*requirements])
    runner.run('Check local Python dependencies',[python,'-m','pip','check'])
    if frontend:runner.run('Install locked frontend dependencies',[locate('npm'),'--prefix','frontend','ci','--no-audit','--no-fund'])
    return python
