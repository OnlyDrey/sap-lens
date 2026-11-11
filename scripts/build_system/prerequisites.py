"""Standard-library detection and consented setup; never installs system tools implicitly."""
import json
import os
import re
import shutil
import subprocess
import sys
from . import failures, python_env
from .runner import ROOT, BuildError

def locate(name):
    return shutil.which(name)

TOOL_TIMEOUT=15
PROBES={'node':['-p','process.versions.node'],'npm':['--version'],'git':['--version'],'docker':['--version']}

class ToolProbe:
    """What happened when a prerequisite was asked for its version. `status` is one of
    missing, launch_failed, nonzero, timeout, invalid_output, ok; nothing here is guessed from a swallowed exception."""
    def __init__(self,name,status,path=None,value=None,exit_code=None,detail=''):
        self.name,self.status,self.path,self.value,self.exit_code,self.detail=name,status,path,value,exit_code,detail

def probe_tool(name):
    """Resolve the tool through PATH/PATHEXT (so Windows npm.cmd works) and run its version probe without a console, stdin or shell."""
    path=locate(name)
    if not path:return ToolProbe(name,'missing')
    command=[path,*PROBES[name]]
    try:
        # stdin is closed: a version probe never reads input, and an inherited console handle must not matter for a .cmd launched through cmd.exe.
        done=subprocess.run(command,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=TOOL_TIMEOUT)
    except subprocess.TimeoutExpired as error:
        return ToolProbe(name,'timeout',path,detail=f'no answer within {TOOL_TIMEOUT} s'+((' ('+failures.tail(error.stderr,5)+')') if isinstance(error.stderr,str) and error.stderr.strip() else ''))
    except (OSError,subprocess.SubprocessError) as error:
        return ToolProbe(name,'launch_failed',path,detail=f'{type(error).__name__}: {error}')
    detail=failures.tail(done.stderr or '',8)
    if done.returncode:return ToolProbe(name,'nonzero',path,exit_code=done.returncode,detail=detail or failures.tail(done.stdout or '',8))
    value=(done.stdout or '').strip().splitlines()[-1].strip() if (done.stdout or '').strip() else ''
    if not re.search(r'\d+\.\d+',value):return ToolProbe(name,'invalid_output',path,value=value[:80],exit_code=0,detail=detail)
    return ToolProbe(name,'ok',path,value=value,exit_code=0)

ACTIONS={'launch_failed':'The executable was found but could not be started. Run the resolved path in the same terminal; check that it is not blocked, quarantined or corrupted, then repair the installation if it also fails there.',
         'nonzero':'The executable started but reported an error. Run the command shown in the same terminal to see the full output, then repair that installation.',
         'timeout':'The executable did not answer in time (antivirus scanning or a stuck first launch are common). Run the command shown in the same terminal; if it answers, retry the build.',
         'invalid_output':'The executable answered with something that is not a version number. Make sure the first match on PATH is the real tool (check with: where.exe {name}).'}
RESULTS={'launch_failed':'Execution failed (could not start)','nonzero':'Execution failed (exit code: {code})','timeout':'Execution timed out','invalid_output':'Unexpected version output'}

def tool_report(probe):
    """The multi-line prerequisite failure: which Python ran the check, which executable was resolved, the exact command and the real result."""
    command=' '.join(f'"{part}"' if ' ' in part else part for part in [probe.path,*PROBES[probe.name]])
    result=RESULTS[probe.status].format(code=probe.exit_code)+(f' - output: {probe.value!r}' if probe.status=='invalid_output' else '')
    details=(probe.detail or '(no output)').replace('\n','\n  ')
    return '\n'.join(['SAP Lens build prerequisite check failed','',f'Python:\n  {sys.executable}\n  Version: {sys.version.split()[0]}',f'Tool:\n  {probe.name}',
                      f'Resolved executable:\n  {probe.path}',f'Command:\n  {command}',f'Result:\n  {result}',f'Details:\n  {details}',
                      f'Suggested action:\n  {ACTIONS[probe.status].format(name=probe.name)}','','SAP Lens never reinstalls a tool that exists. Set SAP_LENS_BUILD_DIAGNOSTICS=1 to print how each tool was resolved.'])

def diagnostics(name,probe):
    if os.environ.get('SAP_LENS_BUILD_DIAGNOSTICS')=='1':
        print(f'[diagnostics] {name}: status={probe.status} path={probe.path} value={probe.value} exit={probe.exit_code} python={sys.executable} cwd={os.getcwd()} PATHEXT={os.environ.get("PATHEXT")}',file=sys.stderr,flush=True)

def inspect_tool(name):
    """Path of a working, supported tool; None only when it is genuinely absent. A tool that exists but fails is a diagnosed error, never "missing"."""
    probe=probe_tool(name)
    diagnostics(name,probe)
    if probe.status=='missing':return None
    if probe.status!='ok':raise BuildError(tool_report(probe),3)
    value,path=probe.value,probe.path
    if name in ('node','npm'):
        match=re.match(r'^(\d+)\.',value)
        node_range=re.fullmatch(r'>=(\d+) <(\d+)',json.loads((ROOT/'frontend/package.json').read_text())['engines']['node'])
        if not node_range:raise BuildError('Unsupported Node engine declaration; update the build detector with the project configuration.')
        supported=range(int(node_range[1]),int(node_range[2])) if name=='node' else (10,11)
        if not match or int(match[1]) not in supported:
            raise BuildError(f'Incompatible {name} {value} (resolved: {path}): this project needs Node {node_range[1]} or {int(node_range[2])-1} and npm 10 or 11 (frontend/package.json engines). SAP Lens does not replace your global Node.js: install a supported version with your approved tools (Node 24 LTS is recommended) and reopen the terminal.',3)
    if name=='node' and int(match[1])%2==1 and not NOTED:
        NOTED.append(value)
        print(f'Note: Node.js {value} is a Current (non-LTS) release. It satisfies the project engines, but Node.js 24 LTS is the CI baseline and the recommended version for reproducible builds.',file=sys.stderr)
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

def prepare_environment(root,runner,*,packaging=False,frontend=True,creator=None):
    """`creator` is the Python 3.12 x64 used to create a missing environment; the engine itself may run under another version."""
    if creator is None:
        found,_=python_env.find_python()
        if not found:raise BuildError('Python 3.12 x64 was not found (the default python is not used). Install it; other versions may stay installed.',3)
        creator=found['path']
    directory=root/('backend/build/python-env' if packaging else '.venv')
    if directory.is_symlink():raise BuildError('The project Python environment must not be a link.',3)
    python=directory/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if directory.exists() and not python.is_file():raise BuildError('Project environment is incomplete. Review/remove only that generated environment, then retry setup.',3)
    if not python.exists():runner.run('Create project-local Python environment',[creator,'-m','venv',directory])
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


def resolve_managed_tools(root=ROOT, *, installer=False):
    """Pinned project tools only; host runtime installation remains consented and separate."""
    from . import managed_tools
    try:
        result = {'actionlint': managed_tools.resolve_actionlint(managed_tools.cache_directory(root))}
        if installer:
            managed_tools.acquire_inno(managed_tools.cache_directory(root))
            result['Inno Setup'] = 'pinned installer verified'
        return result
    except managed_tools.ToolUnavailable as error:
        raise BuildError(str(error), 3) from None
