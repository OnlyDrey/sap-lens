"""Adapters to canonical packagers; no duplicated compiler, installer or publication logic."""
import importlib.util
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from .runner import ROOT, BuildError

TARGETS={'windows':('desktop','installer','server','service','all'),'linux':('server','service','all'),'docker':('server','all'),'all':('all',)}
CI_TOOLS={'validation':('py','testing/ci.py'),'windows-stage':('ps','build-windows.ps1'),'windows-package':('ps','package-windows-deployment.ps1'),
          'installer-check':('ps','build-desktop-installer.ps1'),'native-package':('py','deployment-package.py'),
          'docker-package':('py','deployment/package-docker.py'),'deployment-release':('py','deployment/deployment-release.py'),
          'legacy-release':('py','packaging/release-windows.py')}

def module(name):
    path=next((ROOT/'scripts').rglob(name+'.py'))
    spec=importlib.util.spec_from_file_location('build_internal_'+name.replace('-','_'),path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value

def product_version():
    sys.path.insert(0,str(ROOT/'backend'))
    import version
    return version.product_version()

def validate_version(value):
    sys.path.insert(0,str(ROOT/'backend'))
    import version
    version.make_local_package_info(value,'0'*40)
    return value

def powershell():
    return shutil.which('pwsh') or shutil.which('powershell') or 'pwsh'

def plan(args,python=None):
    python=python or sys.executable
    commands=[]
    if args.ci_tool:
        if os.environ.get('GITHUB_ACTIONS')!='true':raise BuildError('--ci-tool is reserved for existing GitHub Actions jobs; use ordinary build/package modes locally.')
        expected='test' if args.ci_tool=='validation' else 'release' if args.ci_tool in ('deployment-release','legacy-release') else 'build' if args.ci_tool in ('windows-stage','installer-check') else 'package'
        if args.mode!=expected:raise BuildError(f'{args.ci_tool} requires mode {expected}.')
        kind,script=CI_TOOLS[args.ci_tool]
        extra=['-BenchmarkPackaging'] if args.ci_tool=='windows-stage' and args.benchmark_packaging=='true' else []
        ported={'windows-package':'packaging','installer-check':'installer'}
        if args.ci_tool in ported and os.environ.get('SAP_LENS_WINDOWS_PACKAGING')=='python':
            # Opt-in Python ports of package-windows-deployment.ps1 / build-desktop-installer.ps1; unverified on Windows, PowerShell stays the default.
            return [('CI '+args.ci_tool+' (Python port)',[python,str(ROOT/'scripts/build_system/windows'/(ported[args.ci_tool]+'.py')),*args.tool_args])]
        if args.ci_tool=='windows-stage' and os.environ.get('SAP_LENS_WINDOWS_STAGES')=='python':
            # Opt-in Python port of build-windows.ps1 (same options, stages and commands); unverified on Windows, so PowerShell stays the default.
            return [('CI '+args.ci_tool+' (Python stages)',[python,str(ROOT/'scripts/build_system/windows/stages.py'),*args.tool_args,*extra])]
        return [('CI '+args.ci_tool,([powershell(),'-NoProfile','-File'] if kind=='ps' else [python])+[str(ROOT/'scripts'/script),*args.tool_args,*extra])]
    if args.setup_only:return []
    match args.mode:
        case 'quick':
            commands=[('Build configuration',[python,'scripts/packaging/local-build.py','quick','--version',args.version]),
                      ('Product manifests',['node','scripts/product-version.mjs']),
                      ('Documentation links',[python,'scripts/check-docs.py']),
                      ('Test ownership',[python,'scripts/run-tests.py','check']),('Whitespace',['git','diff','--check'])]
        case 'test':
            command=[python,'scripts/validate.py','--level','full' if args.scope=='full' else 'feature']
            if args.scope!='full':command+=['--area',args.area or 'deployment']
            commands=[('Explicit full regression' if args.scope=='full' else 'Targeted validation',command)]
        case 'build'|'package':
            system=platform.system().lower()
            if args.platform=='windows' and args.target=='desktop':
                if system!='windows':raise BuildError('Portable Desktop requires Windows; remote Windows builders use --target installer.')
                if os.environ.get('SAP_LENS_WINDOWS_PACKAGING')=='python':
                    # Opt-in Python port of build-local.ps1; unverified on Windows, PowerShell stays the default.
                    command=[python,str(ROOT/'scripts/build_system/windows/local.py'),'-Mode','Package' if args.skip_setup else 'Build','-Version',args.version]
                else:
                    command=[powershell(),'-NoProfile','-File',str(ROOT/'scripts/build-local.ps1'),'-Mode','Package' if args.skip_setup else 'Build','-Version',args.version]
                if args.output:command+=['-OutputDirectory',str(args.output)]
            else:
                targets={'windows':(['desktop','service'] if args.target=='all' else ['desktop'] if args.target=='installer' else ['service']),
                         'linux':['linux-native'],'docker':['docker'],'all':['all']}[args.platform]
                if args.platform=='windows' and system!='windows' and not args.windows_host:raise BuildError('Windows packaging requires a Windows runner or explicit --windows-host/--windows-repository.')
                if args.platform=='linux' and system!='linux' and not args.linux_host:raise BuildError('Linux native packaging requires Linux or an explicit trusted Linux builder.')
                command=[python,'scripts/deployment/build-deployments.py','--version',args.version,'--scope',args.scope]
                for target in targets:command+=['--platform',target]
                if args.skip_setup:command+=['--reuse-validation']
                if args.no_cache:command+=['--no-cache']
                if args.native_acceptance:command+=['--native-acceptance']
                if args.output:command+=['--output-dir',str(args.output)]
                for name in ('windows_host','windows_repository','linux_host','linux_repository'):
                    if getattr(args,name):command+=['--'+name.replace('_','-'),getattr(args,name)]
            commands=[('Canonical '+args.platform+' '+args.target,command)]
        case 'release':
            # Prepare only; publication remains the existing guarded manual workflow.
            branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()
            policy=module('deployment-release')
            try:policy.require_release_ref('stable' if '-' not in args.version else 'beta','refs/heads/'+branch)
            except policy.DeliveryError as error:raise BuildError(str(error)) from None
            selected={'windows':(['desktop','service'] if args.target=='all' else ['desktop'] if args.target in ('desktop','installer') else ['service']),'linux':['linux-native'],'docker':['docker'],'all':['all']}[args.platform]
            verify=[python,'scripts/deployment/build-deployments.py','--verify-output','--version',args.version,'--output-dir',str(args.output)]
            for target in selected:verify+=['--platform',target]
            commands=[('Verify release artifacts',verify),('Validate source identity',[python,'scripts/packaging/local-build.py','quick','--version',args.version]),
                      ('Release workflow contracts',[python,'scripts/check-workflows.py'])]
        case 'clean':pass
    return commands

from .layout import GENERATED as CLEAN_PATHS  # one authoritative list of generated output
def clean(args,runner):
    # Deterministic validation order, each condition independent: 1 confirmation, 2 allowlisted target, 3 no linked directory,
    # 4 never delete the running interpreter's environment. Confirmation is first so a missing flag is always reported as such,
    # whatever environment the interpreter happens to run from (a venv inside backend/build on Windows made 4 mask 1).
    if not args.confirm_clean:raise BuildError('Clean needs explicit --confirm-clean (or use --dry-run to inspect paths).')
    paths=[ROOT/name for name in CLEAN_PATHS]
    if args.output:
        chosen=args.output.resolve()
        if chosen not in paths:raise BuildError('Clean output must be one of the documented generated directories, never arbitrary user storage.')
        paths=[chosen]
    for path in paths:
        if any(parent.is_symlink() or parent.is_junction() for parent in (path,*path.parents)):raise BuildError('Refusing to clean a linked build directory (symbolic link or Windows junction).')
        if Path(sys.executable).resolve().is_relative_to(path.resolve()):raise BuildError('Run clean from a Python interpreter outside the directory being cleaned.')
    guard=ROOT/'dist/.sap-lens-clean.lock'
    guard.parent.mkdir(parents=True,exist_ok=True)
    try:
        descriptor=os.open(guard,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except OSError as error:raise BuildError('Another cleanup owns the guard. Verify its owner before removing a stale guard.',3) from error
    try:
        if (ROOT/'backend/build/deployment-builder.lock').exists():raise BuildError('A deployment build lock exists; verify its owner before cleaning.',3)
        local=ROOT/'backend/build/local-build.lock'
        if local.exists():
            try:
                with local.open('a+b'):pass  # Windows FileShare.None denies this while the local builder owns it.
            except OSError as error:raise BuildError('The Windows local builder still owns its lock; cleanup refused.',3) from error
        for path in paths:
            if path.exists():shutil.rmtree(path)
    finally:
        os.close(descriptor)
        guard.unlink(missing_ok=True)
    print('Removed only generated build directories; installations, .venv and application data preserved.')
