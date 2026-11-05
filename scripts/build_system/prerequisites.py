"""Standard-library detection and consented setup; never installs system tools implicitly."""
import json
import os
import re
import shutil
import subprocess
import sys
from . import python_env
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
            raise BuildError(f'Incompatible {name} {value}: this project needs Node {node_range[1]} or {int(node_range[2])-1} and npm 10 or 11 (frontend/package.json engines). SAP Lens does not replace your global Node.js: install a supported version with your approved tools (or a per-user version manager) and reopen the terminal.',3)
    if name=='node' and int(match[1])%2==1 and not NOTED:
        NOTED.append(value)
        print(f'Note: Node.js {value} is a Current (non-LTS) release. It satisfies the project engines, but Node.js 24 LTS is the CI baseline and the recommended version for reproducible builds.')
    return path

NOTED=[]  # the non-LTS note is shown once per run

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
    # PowerShell is a Windows-target prerequisite (Windows PowerShell 5.1 or 7). Linux and Docker packaging on Linux is Python-only;
    # the optional script parse check runs there only when pwsh happens to be installed.
    if args.mode in ('build','package') and os.name=='nt' and not (locate('powershell') or locate('pwsh')):
        raise BuildError('Windows packaging requires Windows PowerShell 5.1 (included with Windows) or PowerShell 7. Install it through approved tools.',3)
    for name in names:
        if inspect_tool(name):continue
        if name=='npm' and inspect_tool('node'):
            raise BuildError('npm is missing. Repair the supported Node installation and reopen the terminal.',3)
        if args.skip_setup:raise BuildError(f'Missing {name}; --skip-setup forbids setup. Install the documented prerequisite.',3)
        install_system(name,runner,args.install_system,interactive)
    if args.platform in ('docker','all') and args.mode in ('build','package'):
        runner.run('Check Docker Compose',[locate('docker'),'compose','version'],timeout=30)

def frontend_current(root):
    """npm's own freshness rule: the hidden lockfile it writes into node_modules is newer than package.json and package-lock.json.
    Anything missing or older means `npm ci` (which is deterministic and rebuilds node_modules from the lockfile)."""
    base=root/'frontend'
    hidden=base/'node_modules/.package-lock.json'
    try:
        return hidden.is_file() and all(hidden.stat().st_mtime>=(base/name).stat().st_mtime for name in ('package.json','package-lock.json'))
    except OSError:return False

def prepare_environment(root,runner,*,packaging=False,frontend=True):
    if sys.version_info[:2]!=(3,12):raise BuildError('Project setup requires Python 3.12 to match the locked toolchain.',3)
    directory=root/('backend/build/python-env' if packaging else '.venv')
    if directory.is_symlink():raise BuildError('The project Python environment must not be a link.',3)
    python=directory/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if directory.exists() and not python.is_file():raise BuildError('Project environment is incomplete. Review/remove only that generated environment, then retry setup.',3)
    if not python.exists():runner.run('Create project-local Python environment',[sys.executable,'-m','venv',directory])
    try:
        info=json.loads(subprocess.check_output([str(python),'-c','import sys,json; print(json.dumps(list(sys.version_info[:2])+[64 if sys.maxsize>2**32 else 32]))'],text=True,timeout=15))
    except (OSError,ValueError,subprocess.SubprocessError) as error:raise BuildError(f'Cannot inspect the project Python environment {directory}: it is broken or incomplete. It was left untouched; remove or repair only that environment yourself, then retry.',3) from error
    if info[:2]!=[3,12]:raise BuildError(f'Project environment {directory} uses Python {info[0]}.{info[1]}, not 3.12. It was left untouched; preserve or remove it yourself, then retry so a 3.12 x64 environment is created.',3)
    if info[2:]!=[64]:raise BuildError(f'Project environment {directory} uses 32-bit Python; 64-bit Python 3.12 is required. It was left untouched; preserve or remove it yourself, then retry.',3)
    def run(label,command):
        try:runner.run(label,command);return 0,''
        except BuildError as error:
            log=getattr(runner,'last_output',None)
            return error.code,(log.read_text(encoding='utf-8',errors='replace') if log and log.is_file() else '')
    try:python_env.ensure_pip(python,root,run,print)
    except RuntimeError as error:raise BuildError(str(error),3) from None
    files=['backend/requirements-dev.txt']+(['backend/requirements-build.txt'] if packaging else [])
    if python_env.dependencies_satisfied(python,root,files):print('Locked Python dependencies are already installed; nothing to change.')
    else:
        code,output=run('Install locked project Python dependencies',[python,'-m','pip','install',*sum((['-r',name] for name in files),[])])
        if code:
            hint=' The package index certificate could not be verified: trust the corporate CA in the operating system store and retry (certificate checks are never disabled).' if python_env.TLS_FAILURE.search(output) else ''
            raise BuildError(f'Installing the locked Python dependencies failed (exit {code}). The environment may be partly installed; rerunning is safe.{hint} Logs: {getattr(runner,"directory",None)}',code)
    runner.run('Check local Python dependencies',[python,'-m','pip','check'])
    if frontend:
        if frontend_current(root):print('Locked frontend dependencies are already installed; nothing to change.')
        else:runner.run('Install locked frontend dependencies',[locate('npm'),'--prefix','frontend','ci','--no-audit','--no-fund'])
    return python
