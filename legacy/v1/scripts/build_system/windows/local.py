"""Python port of scripts/build-local.ps1 (local Windows desktop pipeline with lock, run log, receipts and summary). Unverified on Windows.

The PowerShell original changed the process environment and restored it afterwards; the port builds a private environment for its children instead.
Differences that need Windows confirmation: the exclusive build lock is a CreateFileW handle with share mode 0 (the PowerShell original used FileShare.None; `build clean` probes it by
opening the file), and the run log tees the child output instead of using Start-Transcript."""
import os
import sys
from pathlib import Path
if __name__ == '__main__':  # direct execution: make the build_system package importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import argparse
import datetime
import json
import shutil
import subprocess
import time
import uuid

from build_system.windows import server, stages
from build_system.windows.stages import ROOT, Process, StageError, powershell, venv_python

MODES = ('Build', 'Quick', 'Validate', 'Package')


class TeeProcess(Process):
    """Runs commands with output both on the console and in the run log (the PowerShell original used Start-Transcript)."""
    def __init__(self, log=None):
        self.log = log

    def run(self, command, cwd, env):
        if self.log is None:
            return super().run(command, cwd, env)
        with subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace') as child:
            for line in child.stdout:
                print(line, end='', flush=True)
                self.log.write(line)
                self.log.flush()
            return child.wait()


def acquire_lock(path):
    """Exclusive handle held for the whole build; returns a release callable or raises OSError."""
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        handle = kernel.CreateFileW(str(path), 0xC0000000, 0, None, 4, 0x80, None)   # GENERIC_READ|GENERIC_WRITE, share none, OPEN_ALWAYS, NORMAL
        if handle in (None, wintypes.HANDLE(-1).value):
            raise OSError(ctypes.get_last_error(), 'build lock is held')
        return lambda: kernel.CloseHandle(handle)
    import fcntl
    stream = open(path, 'a+b')
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise
    return stream.close


def build(Mode='Build', Version='', IncludeService=False, OutputDirectory='', root=ROOT, process=None, environ=None, windows=None, stage_runner=None, server_build=None,
          lock=acquire_lock, clock=time.monotonic, now=datetime.datetime.now, token=None, printer=print):
    env = dict(os.environ if environ is None else environ)
    started = clock()
    results, state = [], {'stage': 'Prerequisites', 'completed': False, 'info': None, 'node': None, 'npm': None, 'run_directory': None, 'output': None}
    release = log = None
    original_cwd = Path.cwd()

    def finish(version):
        summary = {'mode': Mode, 'requested_version': version, 'status': 'passed' if state['completed'] else 'failed', 'last_stage': state['stage'], 'identity': state['info'],
                   'node': state['node'], 'npm': state['npm'], 'powershell': 'n/a (Python port)', 'stages': results, 'seconds': round(clock() - started, 2),
                   'artifact_directory': str(state['output']) if state['completed'] and Mode in ('Build', 'Package') and state['output'] else None,
                   'log_directory': str(state['run_directory']) if state['run_directory'] else None}
        if state['run_directory']:
            (Path(state['run_directory']) / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        printer(f"\nSAP Lens local {Mode} : {summary['status']} ({summary['seconds']} seconds)")
        if state['info']:
            printer(f"Version: {state['info'].get('version')} | Source: {state['info'].get('source_sha')}")
        for row in results:
            printer(f"{row['stage']}  {row['status']}  {row['seconds']}")
        if summary['artifact_directory']:
            printer(f"Verified artifacts: {summary['artifact_directory']}")
        if state['run_directory']:
            printer(f"Logs and summary: {state['run_directory']}")

    try:
        is_windows = (os.name == 'nt' and os.environ.get('PROCESSOR_ARCHITECTURE') == 'AMD64') if windows is None else windows
        if not is_windows:
            raise StageError('Local Windows builds require x64 Windows. Use the documented Linux validation commands on other operating systems.')
        windir = env.get('WINDIR', '')
        if IncludeService and not (Path(windir) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe').exists():
            raise StageError('-IncludeService requires .NET Framework 4.8 on the Windows builder.')
        if IncludeService and Mode not in ('Build', 'Package'):
            raise StageError('-IncludeService requires Build or Package mode.')
        if env.get('GITHUB_ACTIONS') == 'true':
            raise StageError('This entry point is local-only. GitHub Actions must use the Windows stage runner.')
        process = process or Process()
        os.chdir(root)
        for command in ('git', 'node', 'npm'):
            if not shutil.which(command) and windows is None:
                raise StageError(f'Missing {command}. Install Git for Windows and Node.js 24 LTS or 25 (including npm), then reopen the shell.')
        code, node = process.capture(['node', '-p', 'process.versions.node'], root, env)
        state['node'] = node
        if code != 0 or int(node.split('.')[0]) not in (24, 25):
            raise StageError('Use Node.js 24 LTS (recommended) or 25. Other major versions are not validated.')
        code, npm = process.capture(['npm', '--version'], root, env)
        state['npm'] = npm
        if code != 0 or int(npm.split('.')[0]) not in (10, 11):
            raise StageError('Use npm 10 or 11 supplied with the supported Node.js installation.')
        env['PYTHONUTF8'] = '1'
        env['PYTHONIOENCODING'] = 'utf-8'
        host = None
        if shutil.which('py') or windows is not None:
            code, found = process.capture(['py', '-3.12', '-c', 'import sys; print(sys.executable)'], root, env)
            host = found if code == 0 and found else None
        if not host:
            host = shutil.which('python') or (sys.executable if windows is not None else None)
        if not host:
            raise StageError('Install 64-bit Python 3.12 with the Python launcher, then reopen the shell.')
        if process.run([host, '-c', "import sys,struct; sys.exit(0 if sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8 else 1)"], root, env) != 0:
            raise StageError('Python 3.12 x64 is required, matching CI. Install it with the Python launcher.')
        guard = root / 'dist/.sap-lens-clean.lock'
        if guard.exists():
            raise StageError('Cleanup owns build paths; retry after it finishes.')
        build_directory = root / 'backend/build'
        build_directory.mkdir(parents=True, exist_ok=True)
        try:
            release = lock(build_directory / 'local-build.lock')
        except OSError:
            raise StageError('Another local build is running, or backend/build is not writable. Close the other build and retry.') from None
        if guard.exists():
            raise StageError('Cleanup started while acquiring build ownership; retry after it finishes.')
        run = now().strftime('%Y%m%d-%H%M%S') + '-' + (token or uuid.uuid4().hex)[:8]
        run_directory = root / 'dist/local/runs' / run
        run_directory.mkdir(parents=True)
        state['run_directory'] = run_directory
        log = (run_directory / 'build.log').open('w', encoding='utf-8')
        process = TeeProcess(log) if isinstance(process, Process) and type(process) is Process else process
        env['SAP_LENS_CONFIG_DIR'] = str(build_directory / 'local-test-settings' / run)
        env['DATA_CSV_PATH'] = ''
        env['USER_CSV_PATH'] = ''
        helper = root / 'scripts/packaging/local-build.py'
        build_python = venv_python(root)
        audit_python = build_directory / 'audit-env' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        env['PATH'] = str(build_python.parent) + os.pathsep + env.get('PATH', '')

        def native(command, cwd=None):
            if process.run([str(part) for part in command], cwd or root, env) != 0:
                raise StageError('Command failed with exit code 1')

        def capture(command):
            code, text = process.capture([str(part) for part in command], root, env)
            return code, text

        def stage_port(name, **flags):
            options = stages.parser().parse_args(['-Stage', name, '-PythonExecutable', host] + [f'-{k}' for k, v in flags.items() if v is True]
                                                  + [part for k, v in flags.items() if v not in (True, False, None) for part in (f'-{k}', str(v))])
            (stage_runner or (lambda o: stages.WindowsStages(o, root, process, env).execute()))(options)

        def run_stage(name, action):
            state['stage'] = name
            timer = clock()
            status = 'failed'
            printer(f'\n=== {name} ===')
            try:
                action()
                status = 'passed'
            finally:
                results.append({'stage': name, 'status': status, 'seconds': round(clock() - timer, 2)})

        def resolve_version():
            nonlocal Version
            if not Version:
                code, Version = capture([host, helper, 'version'])
                if code != 0:
                    raise StageError('Unable to resolve backend/resources/product-version.json. Check its version and JSON syntax.')
        run_stage('Version resolution', resolve_version)
        env['SAP_LENS_LOCAL_VERSION'] = Version
        if Mode == 'Quick':
            def quick():
                code, text = capture([host, helper, 'quick', '--version', Version])
                if code != 0:
                    raise StageError('Build configuration check failed. Resolve the reported prerequisite before Build.')
                state['info'] = json.loads(text)
                native(['node', 'scripts/product-version.mjs'])
                native([host, 'scripts/check-docs.py'])
                native([powershell(), '-NoProfile', '-File', root / 'scripts/check-powershell.ps1'])
                native(['git', 'diff', '--check'])
            run_stage('Quick build configuration', quick)
        else:
            if Mode in ('Build', 'Package'):
                run_stage('Clean source check', lambda: native([host, helper, 'clean']))
            # Validate the requested version before dependency installation or packaging.
            run_stage('Local identity', lambda: native([host, helper, 'identity', '--version', Version]))
            info = json.loads((build_directory / 'build-version.json').read_text(encoding='utf-8-sig'))
            state['info'] = info
            output = Path(OutputDirectory) if OutputDirectory else root / 'dist' / (info['version'] + '-' + info['source_sha'][:12])
            state['output'] = output
            if Mode != 'Package':
                run_stage('Managed tool preflight', lambda: native([host, 'scripts/testing/ci.py', 'prerequisites']))
            if Mode == 'Package':
                run_stage('Validated input freshness', lambda: native([host, helper, 'check', '--version', Version]))
            else:
                run_stage('Invalidate previous validation', lambda: native([host, helper, 'invalidate']))
                run_stage('Environment', lambda: stage_port('Environment'))
                run_stage('Python', lambda: stage_port('Python'))

            run_stage('Packaging tool versions', lambda: native([build_python, helper, 'tools']))
            if Mode != 'Package':
                def frontend():
                    stage_port('Frontend')
                    native(['npm', '--prefix', 'frontend', 'run', 'check:types'])
                    native(['node', 'scripts/sync-lucide-catalog.mjs', '--check'])
                run_stage('Frontend', frontend)

            def audit():
                native([host, '-m', 'venv', build_directory / 'audit-env'])
                options = stages.parser().parse_args(['-Stage', 'Audit', '-PythonExecutable', host, '-AuditPython', str(audit_python)])
                (stage_runner or (lambda o: stages.WindowsStages(o, root, process, env).execute()))(options)
                if Mode == 'Package':   # Package also rechecks current vulnerability data without reinstalling inputs.
                    native(['npm', '--prefix', 'frontend', 'audit', '--omit=dev'])
            run_stage('Audit', audit)
            if Mode != 'Package':
                run_stage('PackagingBackend', lambda: stage_port('Backend', TargetedValidation=True))
                run_stage('PackagingBrowser', lambda: stage_port('Browser', TargetedValidation=True))

                def repository():
                    native([build_python, 'scripts/check-workflows.py'])
                    native([build_python, 'scripts/testing/ci.py', 'lint'])
                    native([powershell(), '-NoProfile', '-File', root / 'scripts/check-powershell.ps1'])
                    native(['git', 'diff', '--check'])
                run_stage('Repository', repository)
                run_stage('Validation receipt', lambda: native([build_python, helper, 'record', '--version', Version, '--stages', 'Frontend', 'Python', 'Audit', 'PackagingBackend', 'PackagingBrowser', 'Repository']))
            if Mode in ('Build', 'Package'):
                run_stage('Validated input freshness', lambda: native([build_python, helper, 'check', '--version', Version]))
                run_stage('Package', lambda: stage_port('Package'))
                run_stage('Verify', lambda: stage_port('Verify'))
                run_stage('Smoke', lambda: stage_port('Smoke'))
                run_stage('Distribution roundtrip', lambda: native([build_python, helper, 'export', '--version', Version, '--output', output]))
            if IncludeService:
                def service():
                    service_directory = build_directory / ('local-service-' + run)
                    (server_build or server.build)(Version=Version, OutputDirectory=str(service_directory))
                    native([build_python, 'scripts/deployment-package.py', 'finish', '--directory', service_directory, '--platform', 'Windows-Service-x64', '--output', output])
                run_stage('Service bundle', service)
        state['completed'] = True
    except (StageError, OSError, ValueError, KeyError) as error:
        printer(f"Local {Mode} failed in stage '{state['stage']}': {error}")
    finally:
        try:
            finish(Version)
        finally:
            if log:
                log.close()
            if release:
                release()
            os.chdir(original_cwd)
    return state['completed']


def main(argv=None):
    parser = argparse.ArgumentParser(description='Python port of build-local.ps1 (unverified on Windows).')
    parser.add_argument('-Mode', choices=MODES, default='Build')
    parser.add_argument('-Version', default='')
    parser.add_argument('-IncludeService', action='store_true')
    parser.add_argument('-OutputDirectory', default='')
    options = parser.parse_args(argv)
    return 0 if build(options.Mode, options.Version, options.IncludeService, options.OutputDirectory) else 1


if __name__ == '__main__':
    raise SystemExit(main())
