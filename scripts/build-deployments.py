"""Local orchestration over the canonical deployment packagers. Never publishes.

Cross-OS targets delegate to an explicitly configured, trusted SSH builder with
an already synchronized clean checkout. There is no Windows cross-compiler.
"""
import argparse
import base64
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from version import make_local_deployment_info

TARGETS = ('desktop', 'service', 'docker', 'linux-native')
STEMS = {'desktop': ('Windows-Desktop-x64', '.zip'), 'service': ('Windows-Service-x64', '.zip'),
         'docker': ('Linux-Docker-amd64', '.tar.gz'), 'linux-native': ('Linux-Native-x64', '.tar.gz')}


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'scripts' / (name + '.py'))
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def requested(values):
    return list(TARGETS) if not values or 'all' in values else list(dict.fromkeys(values))


def host_for(target, system):
    if target in ('desktop', 'service'): return 'Windows'
    if target == 'linux-native': return 'Linux'
    return system  # A Windows host must use a Linux Docker daemon.


def tool(name):
    found = shutil.which(name)
    if not found: raise ValueError(f'Missing {name}; install the documented build prerequisite and reopen the terminal.')
    return found


def checkout():
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=ROOT):
        raise ValueError('Commit source changes before building; packaging never resets or cleans Git work.')
    return sha


def prerequisite_versions():
    if sys.version_info[:2] != (3, 12) or platform.machine() not in ('x86_64', 'AMD64'):
        raise ValueError('Use Python 3.12 x64 on Windows x64 or Linux x86-64.')
    node = subprocess.check_output([tool('node'), '-p', 'process.versions.node'], text=True).strip()
    npm = subprocess.check_output([tool('npm'), '--version'], text=True).strip()
    if int(node.split('.')[0]) not in (24, 25) or int(npm.split('.')[0]) not in (10, 11):
        raise ValueError('Use Node 24 LTS (recommended) or 25, with npm 10 or 11.')
    return tool('pwsh') if shutil.which('pwsh') else tool('powershell')


def remote_command(system, repository, source, version, targets, flags):
    if not repository or any(char in repository for char in '\r\n`$;|&<>"\''):
        raise ValueError('Configure a dedicated absolute builder repository path without shell metacharacters.')
    arguments = [arg for target in targets for arg in ('--platform', target)] + ['--version', version, *flags]
    if system == 'Windows':
        if not re.match(r'^[A-Za-z]:[\\/]', repository): raise ValueError('Windows builder repository must be an absolute drive path.')
        # Encoded PowerShell preserves spaces and non-ASCII paths; no Invoke-Expression.
        script = (f"$ErrorActionPreference='Stop';Set-Location '{repository}';"
                  f"if ((git rev-parse HEAD) -ne '{source}') {{throw 'Builder source commit differs'}};"
                  "py -3.12 scripts/build-deployments.py " + ' '.join("'" + arg + "'" for arg in arguments) + ';exit $LASTEXITCODE')
        return 'powershell -NoProfile -EncodedCommand ' + base64.b64encode(script.encode('utf-16le')).decode('ascii')
    if not repository.startswith('/'): raise ValueError('Linux builder repository must be absolute.')
    return (f'cd {shlex.quote(repository)} && test "$(git rev-parse HEAD)" = {shlex.quote(source)} && '
            + shlex.join(['python3.12', 'scripts/build-deployments.py', *arguments]))


def verify_outputs(directory, version, source, targets, remote=False):
    if (directory / 'build-manifest.json').stat().st_size > 1024*1024: raise ValueError('Build manifest is too large.')
    manifest = json.loads((directory / 'build-manifest.json').read_text(encoding='utf-8'))
    if not isinstance(manifest,dict) or not isinstance(manifest.get('targets'),dict): raise ValueError('Malformed build manifest.')
    if manifest.get('version') != version or manifest.get('source_commit') != source:
        raise ValueError('Builder manifest source/version differs.')
    for target in targets:
        row = manifest.get('targets', {}).get(target, {})
        if not isinstance(row,dict): raise ValueError('Malformed target manifest.')
        if row.get('status') != 'passed': continue
        stem, extension = STEMS[target]
        name = f'SAP-Lens-{stem}-{version}{extension}'
        path = directory / name
        if (row.get('artifact') != name or not path.is_file() or path.is_symlink()
                or module('deployment-package').sha(path) != row.get('sha256')
                or path.with_name(name + '.sha256').read_text(encoding='utf-8').strip() != row['sha256'] + '  ' + name
                or row.get('package_verified') is not True or row.get('runtime_smoke_tested') is not True):
            raise ValueError('Builder artifact or verification evidence differs.')
    return manifest


class Builder:
    def __init__(self, args):
        self.args = args
        self.started = time.monotonic()
        self.system = platform.system()
        if self.system not in ('Windows', 'Linux'): raise ValueError('Use a Windows or Linux build host.')
        self.source = checkout()
        self.info = make_local_deployment_info(args.version, self.source)
        raw_output = args.output_dir or ROOT / 'dist' / args.version
        if any(path.is_symlink() for path in [raw_output, *raw_output.parents]): raise ValueError('Output may not be linked.')
        self.output = raw_output.resolve()
        if self.output.is_relative_to(ROOT):
            ignored = subprocess.run(['git','check-ignore','--no-index','--quiet',str(self.output / 'build-manifest.json')],cwd=ROOT)
            if ignored.returncode != 0: raise ValueError('Choose an ignored build output directory or a directory outside the checkout.')
        self.output.mkdir(parents=True, exist_ok=True)
        self.manifest = dict(schema=1, version=args.version, source_commit=self.source,
                             built_at=datetime.now(timezone.utc).isoformat(), invocation=args.invocation, targets={})
        old = self.output / 'build-manifest.json'
        if any(path.is_symlink() for path in self.output.iterdir()): raise ValueError('Output files may not be linked.')
        if any(self.output.iterdir()) and not old.is_file(): raise ValueError('Choose an empty output directory or an existing managed build output.')
        if old.exists():
            value = json.loads(old.read_text(encoding='utf-8'))
            if not isinstance(value,dict) or value.get('version') != args.version or value.get('source_commit') != self.source:
                raise ValueError('Existing output belongs to another source/version. Choose a new --output-dir; nothing was overwritten.')
            if not isinstance(value.get('targets'),dict) or not set(value['targets'])<=set(TARGETS): raise ValueError('Invalid existing target manifest.')
            verify_outputs(self.output,args.version,self.source,list(value['targets']))
            self.manifest['targets'] = value['targets']
        self.log = self.output / 'build.log'
        self.stage = 'Prerequisites'
        self.validated = False
        self.validation_started = False
        self.powershell = None
        self.env = os.environ.copy()
        for key in ('PIP_TARGET','PIP_PREFIX','PIP_USER','PYTHONPATH','PYTHONHOME','SAP_LENS_DATA_DIR','SAP_LENS_SOURCE_DIR','SAP_LENS_DEPLOYMENT_MODE'):
            self.env.pop(key,None)
        self.env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', DATA_CSV_PATH='', USER_CSV_PATH='')
        self.build = ROOT / 'backend/build'
        self.build.mkdir(parents=True, exist_ok=True)
        self.python = self.build / ('python-env/Scripts/python.exe' if self.system == 'Windows' else 'python-env/bin/python')
        self.audit = self.build / ('audit-env/Scripts/python.exe' if self.system == 'Windows' else 'audit-env/bin/python')
        self.env['PATH'] = str(self.python.parent) + os.pathsep + self.env.get('PATH', '')
        self.env['SAP_LENS_AUDIT_PYTHON'] = str(self.audit)
        self.env['RUNNER_TEMP'] = str(self.build / 'deployment-validation')
        self.env['SAP_LENS_CONFIG_DIR'] = str(self.build / 'deployment-test-settings')
        Path(self.env['RUNNER_TEMP']).mkdir(parents=True, exist_ok=True)

    def run(self, label, command, timed=None):
        self.stage = label
        print(label, flush=True)
        if timed:
            command = [str(self.python), 'scripts/ci.py', 'run', timed, '--', *map(str, command)]
        with self.log.open('a', encoding='utf-8') as log:
            log.write('\n' + label + '\n'); log.flush()
            subprocess.run(list(map(str, command)), cwd=ROOT, env=self.env, stdout=log,
                           stderr=subprocess.STDOUT, check=True)

    def save(self):
        if hasattr(self,'started'):self.manifest['total_seconds']=round(time.monotonic()-self.started,2)
        module('deployment-package').write(self.output / 'build-manifest.json', self.manifest)
        rows = [f'{row["sha256"]}  {row["artifact"]}' for row in self.manifest['targets'].values() if row.get('status') == 'passed']
        (self.output / 'checksums.sha256').write_text('\n'.join(rows) + '\n', encoding='ascii')

    def validate(self):
        if self.validated: return
        if self.validation_started: raise ValueError('Shared local validation failed earlier in this run; inspect build.log. No repeated full suite was started.')
        self.validation_started = True
        self.powershell = prerequisite_versions()
        pkg = module('deployment-package')
        if self.args.clean:
            for name in ('python-env', 'audit-env', 'deployment-local-validation.json'):
                path = self.build / name
                if path.is_symlink(): raise ValueError('Refusing to clean linked build inputs.')
                if Path(sys.executable).resolve().is_relative_to(path.resolve()): raise ValueError('Run --clean from the host Python, not the environment being cleaned.')
                if path.is_dir(): shutil.rmtree(path)
                elif path.exists(): path.unlink()
        pkg.write(self.build / 'build-version.json', self.info)
        if self.args.reuse_validation:
            self.run('Verify existing source/tool/frontend validation receipt', [sys.executable, 'scripts/deployment-package.py', 'require-inputs'])
            self.validated = True
            return
        receipt = self.build / 'deployment-local-validation.json'
        if receipt.is_symlink(): raise ValueError('Validation receipt may not be linked.')
        receipt.unlink(missing_ok=True)
        if self.args.no_cache:
            self.env['PIP_NO_CACHE_DIR'] = '1'
            self.env['PLAYWRIGHT_BROWSERS_PATH'] = str(self.build / 'deployment-validation' / ('cold-playwright-' + self.args.invocation))
            cold_npm = Path(self.env['RUNNER_TEMP']) / 'cold-npm'
            if cold_npm.is_symlink(): raise ValueError('Cold cache may not be linked.')
            if cold_npm.exists(): shutil.rmtree(cold_npm)
        self.run('Create dedicated build Python environment', [sys.executable, '-m', 'venv', self.python.parent.parent])
        self.run('Create dedicated audit environment', [sys.executable, '-m', 'venv', self.audit.parent.parent])
        pip_options = ['--no-cache-dir'] if self.args.no_cache else []
        self.run('Install pinned Python build and test dependencies', [self.python, '-m', 'pip', 'install', *pip_options, '-r', 'backend/requirements-dev.txt', '-r', 'backend/requirements-build.txt'])
        pip_pin = next(line for line in (ROOT / 'backend/requirements-build.txt').read_text().splitlines() if line.startswith('pip=='))
        self.run('Install pinned audit tooling', [self.audit, '-m', 'pip', 'install', *pip_options, pip_pin, '-r', 'scripts/requirements-audit.txt'])
        self.run('Install locked frontend dependencies', [tool('npm'), '--prefix', 'frontend', 'ci', '--no-audit', '--no-fund', *(['--cache', self.env['RUNNER_TEMP'] + '/cold-npm'] if self.args.no_cache else [])])
        timing = Path(self.env['RUNNER_TEMP']) / 'sap-lens-ci-timings.jsonl'
        if timing.exists(): timing.unlink()
        commands = [
            ('pip_check', [self.python, '-m', 'pip', 'check']),
            ('workflow_lint', [self.python, 'scripts/ci.py', 'lint']),
            ('powershell', [self.powershell, '-NoProfile', '-File', 'scripts/check-powershell.ps1']),
            ('backend', [self.python, '-W', 'error::DeprecationWarning', '-m', 'unittest', 'discover', '-s', 'backend/tests', '-v']),
            ('types', [tool('npm'), '--prefix', 'frontend', 'run', 'check:types']),
            ('catalog', [tool('node'), 'scripts/sync-lucide-catalog.mjs', '--check']),
            ('build', [tool('npm'), '--prefix', 'frontend', 'run', 'build']),
            ('javascript_audit', [tool('npm'), '--prefix', 'frontend', 'audit', '--omit=dev']),
        ]
        for stage, command in commands: self.run(stage, command, timed=stage)
        installed = subprocess.check_output([str(self.python), '-m', 'pip', 'list', '--format=freeze'], env=self.env, text=True)
        requirements = Path(self.env['RUNNER_TEMP']) / 'audit-installed.txt'; requirements.write_text(installed)
        self.run('Audit all installed build/runtime dependencies', [self.audit, '-m', 'pip_audit', '--disable-pip', '--no-deps', '-r', requirements], timed='python_audit')
        browser = self.env.get('PLAYWRIGHT_EXECUTABLE_PATH')
        if browser:
            if not Path(browser).is_file(): raise ValueError('Configured Playwright executable does not exist.')
            print('Using the explicitly configured Playwright browser executable.')
        else:
            self.run('Install the pinned Playwright Chromium headless shell', [tool('node'), 'frontend/node_modules/playwright/cli.js', 'install', 'chromium', '--only-shell'])
        self.run('Browser regression tests', [tool('npm'), '--prefix', 'frontend', 'run', 'test:browser'], timed='browser')
        self.run('Seal successful local validation', [self.python, 'scripts/deployment-package.py', 'record-local'])
        self.validated = True

    def local(self, target):
        if target == 'docker':
            actual = subprocess.check_output([tool('docker'), 'info', '--format', '{{.OSType}}/{{.Architecture}}'], text=True).strip()
            if actual not in ('linux/x86_64', 'linux/amd64'): raise ValueError('Select an x86-64 Linux Docker engine (Docker Desktop Linux containers on Windows).')
        self.validate()
        stem, ext = STEMS[target]; name = f'SAP-Lens-{stem}-{self.args.version}{ext}'
        if (self.output / name).exists(): raise ValueError('Artifact already exists. Choose a new --output-dir; existing packages are preserved.')
        with tempfile.TemporaryDirectory(prefix='deployment-', dir=self.build) as temporary:
            destination = Path(temporary)
            if target in ('desktop', 'service'):
                self.run('Canonical Windows package and native smoke tests', [self.powershell, '-NoProfile', '-File', 'scripts/package-windows-deployment.ps1', '-Target', 'Desktop' if target == 'desktop' else 'Service', '-OutputDirectory', destination])
            elif target == 'linux-native':
                self.run('Canonical Linux native package', [self.python, 'scripts/deployment-package.py', 'native', '--output', destination])
                self.run('Offline installation and runtime/persistence smoke tests', [self.python, 'scripts/test-native-deployment.py', '--artifacts', destination])
            else:
                self.run('Canonical Docker package and runtime/persistence smoke tests', [self.python, 'scripts/package-docker.py', '--output', destination, *(['--no-cache'] if self.args.no_cache else [])])
            self.stage = 'Final artifact collection and checksum'
            archive = destination / name
            if not archive.is_file(): raise ValueError('Canonical packager did not produce the expected versioned artifact.')
            digest = module('deployment-package').sha(archive)
            sidecar = archive.with_name(name + '.sha256')
            if sidecar.read_text(encoding='utf-8').strip() != digest + '  ' + name: raise ValueError('Canonical checksum differs.')
            shutil.copyfile(archive, self.output / name); shutil.copyfile(sidecar, self.output / sidecar.name)
        return dict(status='passed', built=True, package_verified=True, runtime_smoke_tested=True,
                    artifact=name, sha256=digest, host_os=self.system, build_environment=self.system + ' native' if target != 'docker' else 'Linux Docker engine',
                    tested_at=datetime.now(timezone.utc).isoformat())

    def remote(self, system, targets):
        host = self.args.windows_host if system == 'Windows' else self.args.linux_host
        repository = self.args.windows_repository if system == 'Windows' else self.args.linux_repository
        if not host or not repository:
            raise ValueError(f'Configure --{system.lower()}-host and --{system.lower()}-repository for a trusted {system} builder synchronized to this commit. No cross-compilation or silent skip.')
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]*', host): raise ValueError('Use a safe SSH host alias; configure ports/keys in SSH config.')
        flags = (['--clean'] if self.args.clean else []) + (['--no-cache'] if self.args.no_cache else []) + (['--reuse-validation'] if self.args.reuse_validation else [])
        nonce = uuid.uuid4().hex
        command = remote_command(system, repository, self.source, self.args.version, targets, [*flags,'--invocation',nonce])
        ssh = [tool('ssh'), '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', host, command]
        # All remote targets still run independently. A nonzero exit can have valid sibling outputs.
        with self.log.open('a') as log: subprocess.run(ssh, stdout=log, stderr=subprocess.STDOUT)
        with tempfile.TemporaryDirectory(prefix='remote-deployment-', dir=self.build) as temporary:
            destination = Path(temporary)
            remote_root = repository.replace('\\', '/').rstrip('/') + '/dist/' + self.args.version
            scp = [tool('scp'), '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes']
            subprocess.run([*scp, host + ':' + remote_root + '/build-manifest.json', str(destination)], check=True, stdout=subprocess.DEVNULL)
            result = json.loads((destination / 'build-manifest.json').read_text(encoding='utf-8'))
            if not isinstance(result,dict) or not isinstance(result.get('targets'),dict): raise ValueError('Malformed remote build manifest.')
            if result.get('source_commit') != self.source or result.get('version') != self.args.version or result.get('invocation') != nonce:
                raise ValueError('Remote source/version mismatch; no artifact was accepted.')
            for target in targets:
                row = result.get('targets', {}).get(target, {})
                if not isinstance(row,dict): raise ValueError('Malformed remote target result.')
                if row.get('status') != 'passed': continue
                stem, ext = STEMS[target]; name = f'SAP-Lens-{stem}-{self.args.version}{ext}'
                if row.get('artifact') != name or (self.output / name).exists(): raise ValueError('Unexpected remote filename or existing local artifact.')
                for filename in (name, name + '.sha256'):
                    subprocess.run([*scp, host + ':' + remote_root + '/' + filename, str(destination)], check=True, stdout=subprocess.DEVNULL)
            verify_outputs(destination, self.args.version, self.source, targets, remote=True)
            for target in targets:
                row = result.get('targets', {}).get(target, {})
                if row.get('status') == 'passed':
                    for filename in (row['artifact'], row['artifact'] + '.sha256'): shutil.copyfile(destination / filename, self.output / filename)
                self.manifest['targets'][target] = row or dict(status='failed', error='Remote builder did not report the requested target.')

    def execute(self):
        targets = requested(self.args.platform)
        remote_groups = {}
        for target in targets:
            required = host_for(target, self.system)
            if required != self.system: remote_groups.setdefault(required, []).append(target)
        for system, group in remote_groups.items():
            try: self.remote(system, group)
            except (ValueError, OSError, subprocess.CalledProcessError) as error:
                for target in group: self.manifest['targets'][target] = dict(status='failed', built=False, package_verified=False, runtime_smoke_tested=False, failed_stage='Remote builder admission/retrieval', error=str(error) if isinstance(error, ValueError) else type(error).__name__)
            self.save()
        for target in targets:
            if host_for(target, self.system) != self.system: continue
            try: self.manifest['targets'][target] = self.local(target)
            except (ValueError, OSError, subprocess.CalledProcessError) as error:
                self.manifest['targets'][target] = dict(status='failed', built=False, package_verified=False, runtime_smoke_tested=False, failed_stage=self.stage, error=str(error) if isinstance(error, ValueError) else type(error).__name__)
            self.save()
        for target in targets:
            row = self.manifest['targets'][target]
            print(f'{target}: {row["status"]} — {row.get("artifact", row.get("error", ""))}')
        print('Manifest: ' + str(self.output / 'build-manifest.json'))
        return 0 if all(self.manifest['targets'][target]['status'] == 'passed' for target in targets) else 1


def main():
    sys.stdout.reconfigure(encoding='utf-8',errors='backslashreplace')
    sys.stderr.reconfigure(encoding='utf-8',errors='backslashreplace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--platform', action='append', choices=[*TARGETS, 'all'])
    parser.add_argument('--version', required=True)
    parser.add_argument('--clean', action='store_true')
    parser.add_argument('--no-cache', action='store_true')
    parser.add_argument('--reuse-validation', action='store_true')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--windows-host'); parser.add_argument('--windows-repository')
    parser.add_argument('--linux-host'); parser.add_argument('--linux-repository')
    parser.add_argument('--invocation', default=uuid.uuid4().hex, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not re.fullmatch('[0-9a-f]{32}',args.invocation): parser.error('Invalid build invocation identity.')
    if sys.version_info[:2] != (3,12): parser.error('Use Python 3.12 to match the supported build toolchain.')
    if os.environ.get('GITHUB_ACTIONS') == 'true': parser.error('Local orchestration cannot impersonate CI. Use the approved deployment workflow.')
    if args.clean and args.reuse_validation: parser.error('--clean and --reuse-validation are mutually exclusive.')
    lock = None
    try:
        # Cross-platform exclusive ownership without a global machine setting.
        directory = ROOT / 'backend/build'; directory.mkdir(parents=True, exist_ok=True)
        lock = directory / 'deployment-builder.lock'
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        return Builder(args).execute()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print('Local deployment build stopped: ' + (str(error) if isinstance(error, ValueError) else type(error).__name__) + '. Check prerequisites, lock ownership and build.log.', file=sys.stderr)
        return 1
    finally:
        if lock and 'descriptor' in locals(): lock.unlink(missing_ok=True)


if __name__ == '__main__': sys.exit(main())
