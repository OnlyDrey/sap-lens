"""One menu/CLI for local and non-interactive CI execution."""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from . import doctor, prerequisites as deps, python_env, targets
from .runner import ROOT, BuildError, Runner

MODES=('quick','test','build','package','release','clean','prerequisites')
def parser():
    result=argparse.ArgumentParser(description='SAP Lens shared build engine. System installs require explicit consent; release prepares only.')
    result.add_argument('mode',nargs='?',type=str.lower,choices=MODES)
    result.add_argument('--platform',type=str.lower,choices=tuple(targets.TARGETS))
    result.add_argument('--target',type=str.lower)
    result.add_argument('--version')
    result.add_argument('--scope',type=str.lower,choices=('targeted','full'),default='targeted')
    result.add_argument('--area',help='Existing validation area, e.g. deployment, sod or shared-ui')
    result.add_argument('--output',type=Path)
    group=result.add_mutually_exclusive_group();group.add_argument('--setup',action='store_true');group.add_argument('--skip-setup',action='store_true')
    result.add_argument('--setup-only',action='store_true')
    result.add_argument('--check-only',action='store_true',help='prerequisites mode: report only, change nothing')
    result.add_argument('--repair',action='store_true',help='prerequisites mode: rename a broken or incompatible environment aside and recreate it')
    result.add_argument('--json',action='store_true',help='prerequisites mode: machine-readable report')
    result.add_argument('--install-system',action='store_true',help='Explicit opt-in to supported per-user winget installs; never assumed in CI')
    result.add_argument('--non-interactive',action='store_true')
    result.add_argument('--dry-run',action='store_true')
    result.add_argument('--verbose',action='store_true')
    result.add_argument('--confirm-clean',action='store_true')
    result.add_argument('--no-cache',action='store_true')
    result.add_argument('--native-acceptance',action='store_true',help='also run the privileged native Windows service (SCM) acceptance test; needs an elevated shell')
    for name in ('windows-host','windows-repository','linux-host','linux-repository'):result.add_argument('--'+name)
    result.add_argument('--benchmark-packaging', choices=('true','false'), default='false', help=argparse.SUPPRESS)
    result.add_argument('--ci-tool',choices=tuple(targets.CI_TOOLS),help='Internal adapter used only by existing Actions jobs; arguments follow --')
    return result

def choose(prompt,options,default,read=input):
    answer=read(f'{prompt} ({", ".join(options)}) [{default}]: ').strip().lower() or default
    if answer not in options:raise BuildError('Choose one of: '+', '.join(options))
    return answer

def configure(args,interactive,read=input):
    if args.setup_only and args.skip_setup:raise BuildError('--setup-only and --skip-setup are incompatible.')
    if args.check_only and args.repair:raise BuildError('--check-only and --repair are incompatible.')
    if (args.check_only or args.repair or args.json) and args.mode!='prerequisites':raise BuildError('--check-only, --repair and --json belong to the prerequisites mode.')
    args.target_given=args.target is not None
    if args.tool_args and not args.ci_tool:raise BuildError('Arguments after -- are accepted only by a named CI adapter.')
    if args.skip_setup and args.install_system:raise BuildError('--skip-setup cannot authorize system installation.')
    if args.setup_only and args.mode is None:args.mode='quick'
    if args.mode is None:args.mode=choose('Mode',MODES,'quick',read) if interactive else 'quick'
    if args.scope=='full' and args.mode!='test':raise BuildError('--scope full is reserved for an explicitly requested test run, never a packaging/release prerequisite.')
    native='windows' if platform.system()=='Windows' else 'linux'
    if args.platform is None:args.platform=choose('Platform',('windows','linux','docker'),native,read) if interactive and args.mode in ('build','package') else native
    if args.target is None:
        default='desktop' if args.platform=='windows' else 'all' if args.platform=='all' else 'server'
        args.target=choose('Target',targets.TARGETS[args.platform],default,read) if interactive and args.mode in ('build','package') else default
    if args.target not in targets.TARGETS[args.platform]:raise BuildError(f'{args.platform} supports targets: '+', '.join(targets.TARGETS[args.platform]))
    if args.mode=='release' and not args.output and not args.ci_tool:
        if interactive:args.output=Path(read('Validated artifact directory: ').strip())
        else:raise BuildError('release preparation requires --output pointing to validated deployment artifacts; it never publishes.')
    if args.output:
        raw=ROOT/args.output
        if any(path.is_symlink() for path in (raw,*raw.parents)):raise BuildError('Output cannot use a linked path.')
        args.output=raw.resolve()
    return args

def test_python(args,runner):
    candidate=ROOT/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if args.setup:return deps.prepare_environment(ROOT,runner,frontend=args.mode!='release')
    if args.mode=='release' and not candidate.is_file():candidate=ROOT/'backend/build/python-env'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if (ROOT/'.venv').is_symlink():raise BuildError('Project .venv must not be a linked interpreter directory.',3)
    if candidate.is_file():
        try:
            subprocess.check_output([str(candidate),'-c','import sys; assert sys.version_info[:2]==(3,12); import fastapi,yaml; import importlib.metadata as m; m.version("ruff")'],stderr=subprocess.DEVNULL,timeout=15)
            return candidate
        except (OSError,subprocess.SubprocessError):
            if args.skip_setup:raise BuildError('Project test dependencies are missing; rerun with --setup.',3) from None
    if args.skip_setup:raise BuildError('Project .venv is missing; omit --skip-setup or run --setup-only first.',3)
    return deps.prepare_environment(ROOT,runner,frontend=args.mode!='release')

def reexec(argv):
    """The engine is standard-library only, but its child commands use sys.executable: when it was started by another Python (for example a
    3.15 default), run it again under the resolved 3.12 x64 interpreter instead of failing or silently using the wrong one. None = stay."""
    if (sys.version_info[:2]==python_env.REQUIRED and sys.maxsize>2**32) or os.environ.get('SAP_LENS_REEXEC')=='1':return None
    found,_=python_env.find_python()
    if not found:
        if '--check-only' in argv:return None
        print('Python 3.12 x64 was not found; the default python is never used for SAP Lens builds. Install Python 3.12 (other versions may stay installed), then rerun.',file=sys.stderr)
        return 3
    print(f"Using Python {found['version']} ({found['path']}) instead of {sys.version.split()[0]}.")
    return subprocess.call([found['path'],str(Path(__file__).resolve().parents[1]/'build.py'),*argv],env=dict(os.environ,SAP_LENS_REEXEC='1'),stdin=subprocess.DEVNULL if not sys.stdin or not sys.stdin.isatty() else None)

def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    redirected=reexec(argv)
    if redirected is not None:return redirected
    split=argv.index('--') if '--' in argv else len(argv)
    args=parser().parse_args(argv[:split]);args.tool_args=argv[split+1:]
    interactive=not args.non_interactive and os.environ.get('GITHUB_ACTIONS')!='true' and sys.stdin.isatty()
    runner=Runner(verbose=args.verbose)
    try:
        configure(args,interactive)
        # CI adapters use setup-actions and the existing attestation boundary, never local bootstrap/setup.
        if args.ci_tool:
            if args.setup or args.setup_only or args.install_system:raise BuildError('CI adapters cannot run system/bootstrap setup.')
        elif args.mode=='prerequisites':return doctor.run_prerequisites(args,runner)
        elif not args.dry_run:
            deps.check_tools(args,runner,interactive)
            if args.mode in ('build','package'):doctor.preflight(args)
        args.version=targets.validate_version(args.version or targets.product_version())
        commands=targets.plan(args)
        if args.dry_run:
            print(json.dumps(dict(mode=args.mode,platform=args.platform,target=args.target,version=args.version,scope=args.scope,
                                  setup_only=args.setup_only,setup_requested=args.setup or args.setup_only,system_install_opt_in=args.install_system,commands=[dict(operation=name,argv=list(map(str,command))) for name,command in commands],
                                  clean_paths=list(targets.CLEAN_PATHS) if args.mode=='clean' else []),indent=2))
            return 0
        if args.setup_only:
            deps.prepare_environment(ROOT,runner,packaging=args.mode in ('build','package'))
        elif args.mode=='clean':targets.clean(args,runner)
        else:
            if args.setup and args.mode=='quick':deps.prepare_environment(ROOT,runner)
            if args.mode in ('test','release') and not args.ci_tool:commands=targets.plan(args,test_python(args,runner))
            for name,command in commands:runner.run(name,command,timeout=7200 if args.mode=='test' and args.scope=='full' else 1800)
        if args.mode in ('build','package') and not args.ci_tool and runner.last_output:
            for line in runner.last_output.read_text(encoding='utf-8',errors='replace').splitlines():
                if line.startswith(('Verified artifacts:', 'Manifest:', 'Verified deployment archive:')):print(line)
        if runner.directory:print('Logs: '+str(runner.directory))
        if args.mode=='release':print('Preparation checks complete. No tag/release was created. Promote through the approved main/manual-release process.')
        print('SAP Lens '+args.mode+' completed.')
        return 0
    except (BuildError,ValueError,OSError,subprocess.SubprocessError) as error:
        print(str(error),file=sys.stderr)
        return getattr(error,'code',2)
