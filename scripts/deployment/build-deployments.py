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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'scripts'))
from build_system import artifacts, failures, frontend_workspace, python_env
from build_system.layout import deployment_output_name as output_name, is_linked_output
from build_system.runner import StageProgress
from version import make_local_deployment_info,product_version

TARGETS = ('desktop', 'service', 'docker', 'linux-native')
STEMS = {'desktop': ('win-desktop-x64', '.zip'), 'service': ('win-service-x64', '.zip'),
         'docker': ('linux-docker-amd64', '.tar.gz'), 'linux-native': ('linux-native-x64', '.tar.gz')}


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), next((ROOT / 'scripts').rglob(name + '.py')))
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
    return shutil.which('pwsh') or shutil.which('powershell')  # None is acceptable only when no local target needs PowerShell


def remote_command(system, repository, source, version, targets, flags):
    if not repository or any(char in repository for char in '\r\n`$;|&<>"\''):
        raise ValueError('Configure a dedicated absolute builder repository path without shell metacharacters.')
    arguments = [arg for target in targets for arg in ('--platform', target)] + ['--version', version, *flags]
    if system == 'Windows':
        if not re.match(r'^[A-Za-z]:[\\/]', repository): raise ValueError('Windows builder repository must be an absolute drive path.')
        # Encoded PowerShell preserves spaces and non-ASCII paths; no Invoke-Expression.
        script = (f"$ErrorActionPreference='Stop';Set-Location '{repository}';"
                  f"if ((git rev-parse HEAD) -ne '{source}') {{throw 'Builder source commit differs'}};"
                  "py -3.12 scripts/deployment/build-deployments.py " + ' '.join("'" + arg + "'" for arg in arguments) + ';exit $LASTEXITCODE')
        return 'powershell -NoProfile -EncodedCommand ' + base64.b64encode(script.encode('utf-16le')).decode('ascii')
    if not repository.startswith('/'): raise ValueError('Linux builder repository must be absolute.')
    return (f'cd {shlex.quote(repository)} && test "$(git rev-parse HEAD)" = {shlex.quote(source)} && '
            + shlex.join(['python3.12', 'scripts/deployment/build-deployments.py', *arguments]))


def smoke_evidence(target, row, release):
    """Runtime evidence of a passed row. A Windows service built without the privileged SCM acceptance is a valid package (`scm_acceptance.status`
    `not_run`), but a release verification requires the acceptance to have passed."""
    if row.get('runtime_smoke_tested') is True: return True
    return not release and target == 'service' and (row.get('native_acceptance') or {}).get('status') == 'not_run'


def verify_outputs(directory, version, source, targets, remote=False, release=False):
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
        name = f'sap-lens-{stem}-v{version}{extension}'
        path = directory / name
        if (row.get('artifact') != name or not path.is_file() or path.is_symlink()
                or module('deployment-package').sha(path) != row.get('sha256')
                or path.with_name(name + '.sha256').read_text(encoding='utf-8').strip() != row['sha256'] + '  ' + name
                or row.get('package_verified') is not True or not smoke_evidence(target, row, release)):
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
        raw_output = args.output_dir or ROOT / 'dist' / output_name(args.version, self.source)
        if any(is_linked_output(path) for path in [raw_output, *raw_output.parents]): raise ValueError('Output may not be linked.')
        self.output = raw_output.resolve()
        if self.output.is_relative_to(ROOT):
            ignored = subprocess.run(['git','check-ignore','--no-index','--quiet',str(self.output / 'build-manifest.json')],cwd=ROOT)
            if ignored.returncode != 0: raise ValueError('Choose an ignored build output directory or a directory outside the checkout.')
        self.output.mkdir(parents=True, exist_ok=True)
        self.manifest = dict(schema=1, version=args.version, source_commit=self.source,
                             built_at=datetime.now(timezone.utc).isoformat(), invocation=args.invocation, validation_scope=getattr(args,'scope','targeted'), targets={})
        old = self.output / 'build-manifest.json'
        if any(is_linked_output(path) for path in self.output.iterdir()): raise ValueError('Output files may not be linked.')
        if any(self.output.iterdir()) and not old.is_file(): raise ValueError('Choose an empty output directory or an existing managed build output.')
        if old.exists():
            value = json.loads(old.read_text(encoding='utf-8'))
            if not isinstance(value,dict) or value.get('version') != args.version or value.get('source_commit') != self.source:
                raise ValueError(f'Existing output {self.output} belongs to another source/version (manifest: version={value.get("version") if isinstance(value,dict) else "?"}, source_commit={str(value.get("source_commit") if isinstance(value,dict) else "?")[:12]}; requested: version={args.version}, source_commit={self.source[:12]}). Nothing was overwritten. Use a new directory, for example: -Output "{self.output}-{self.source[:8]}" (PowerShell) or --output-dir "{self.output}-{self.source[:8]}" (Python).')
            if not isinstance(value.get('targets'),dict) or not set(value['targets'])<=set(TARGETS): raise ValueError('Invalid existing target manifest.')
            verify_outputs(self.output,args.version,self.source,list(value['targets']))
            self.manifest['targets'] = value['targets']
        self.log = self.output / 'build.log'
        self.stage = 'Prerequisites'
        self.validated = False
        self.validation_started = False
        self.shared_failure = None
        self.powershell = None
        self.env = os.environ.copy()
        for key in ('PIP_TARGET','PIP_PREFIX','PIP_USER','PYTHONPATH','PYTHONHOME','SAP_LENS_DATA_DIR','SAP_LENS_SOURCE_DIR','SAP_LENS_DEPLOYMENT_MODE'):
            self.env.pop(key,None)
        self.env.update(SAP_LENS_BUILD_SCOPE=getattr(args,'scope','targeted'), PYTHONUTF8='1', PYTHONIOENCODING='utf-8', DATA_CSV_PATH='', USER_CSV_PATH='')
        self.build = ROOT / 'backend/build'
        self.build.mkdir(parents=True, exist_ok=True)
        self.workspace = self.build / 'frontend-workspace'
        self.python = self.build / ('python-env/Scripts/python.exe' if self.system == 'Windows' else 'python-env/bin/python')
        self.audit = self.build / ('audit-env/Scripts/python.exe' if self.system == 'Windows' else 'audit-env/bin/python')
        self.env['PATH'] = str(self.python.parent) + os.pathsep + self.env.get('PATH', '')
        self.env['SAP_LENS_AUDIT_PYTHON'] = str(self.audit)
        self.env['RUNNER_TEMP'] = str(self.build / 'deployment-validation')
        self.env['SAP_LENS_CONFIG_DIR'] = str(self.build / 'deployment-test-settings')
        Path(self.env['RUNNER_TEMP']).mkdir(parents=True, exist_ok=True)

    def failure_class(self, label):
        """Which part of the build a stage belongs to, so the manifest can tell a dependency problem from a packaging problem."""
        text = label.lower()
        if 'frontend dependencies' in text: return 'dependency_install'
        if 'python' in text and ('install' in text or 'environment' in text): return 'python_environment'
        if label == 'build': return 'frontend_build'
        if label in ('types', 'catalog'): return 'frontend_validation'
        if text.startswith('browser regression'): return 'browser_smoke'
        if 'canonical windows package' in text: return getattr(self, 'current_target', None) + '_packaging' if getattr(self, 'current_target', None) else 'packaging'
        if 'native' in text and 'smoke' in text or 'runtime' in text: return 'runtime_smoke'
        if 'package' in text: return 'packaging'
        return 'validation'

    def run(self, label, command, timed=None, cwd=None):
        self.stage = label
        print(label, flush=True)
        if timed:
            command = [str(self.python), str(ROOT / 'scripts/testing/ci.py'), 'run', timed, '--', *map(str, command)]
        child_env = self.env.copy()
        if any(Path(str(value)).name == 'test-native-deployment.py' for value in command):
            for key in ('SAP_LENS_CONFIG_DIR','SAP_LENS_DATA_DIR','SAP_LENS_SOURCE_DIR','SAP_LENS_DEPLOYMENT_MODE'):
                child_env.pop(key,None)
        directory = Path(cwd) if cwd else ROOT
        with self.log.open('a', encoding='utf-8') as log:
            log.write('\n' + label + '\n'); log.flush()
            start = log.tell()
            progress = StageProgress(label, self.log)
            try:
                with progress:
                    subprocess.run(list(map(str, command)), cwd=directory, env=child_env, stdout=log, stderr=subprocess.STDOUT, check=True)
            except subprocess.CalledProcessError as error:
                log.flush()
                # The terminal and the manifest get the real cause; the complete output stays in build.log.
                with self.log.open('r', encoding='utf-8', errors='replace') as reader:
                    reader.seek(start); output = reader.read()
                raise failures.StageFailure(label, command, directory, error.returncode, output, self.log, self.failure_class(label)) from None
            finally:
                if hasattr(self, 'manifest'):
                    error = sys.exc_info()[1]
                    self.manifest.setdefault('stages', []).append(dict(name=label, seconds=progress.seconds,
                        status='failed' if error else 'passed', exit_code=getattr(error, 'returncode', getattr(error, 'exit_code', 1)) if error else 0,
                        log=str(self.log)))

    def prepare_workspace(self):
        """Mirror the sources into the isolated frontend workspace. The developer's frontend/node_modules is never touched."""
        self.stage = 'Prepare isolated frontend workspace'
        if os.name == 'nt' and len(str(self.workspace)) > 110:
            raise frontend_workspace.WorkspaceError(f'The repository path is too long for the isolated frontend workspace ({self.workspace}). Move the checkout to a shorter path (for example C:\\src\\sap-lens) or enable Windows long paths.')
        frontend_workspace.mirror(ROOT, self.workspace)
        return self.workspace, self.workspace / 'frontend'

    def bootstrap_pip(self, interpreter):
        """Same pip bootstrap as the build engine: an old seeded pip is moved to the pinned release before any package is installed."""
        def run(label, command):
            self.stage = label
            done = subprocess.run(list(map(str, command)), cwd=ROOT, env=self.env, capture_output=True, text=True)
            with self.log.open('a', encoding='utf-8') as log: log.write('\n' + label + '\n' + done.stdout + done.stderr)
            return done.returncode, done.stdout + done.stderr
        try: python_env.ensure_pip(interpreter, ROOT, run, print)
        except RuntimeError as error: raise ValueError(str(error)) from None

    def save(self):
        if hasattr(self,'started'):self.manifest['total_seconds']=round(time.monotonic()-self.started,2)
        module('deployment-package').write(self.output / 'build-manifest.json', self.manifest)
        rows = [f'{row["sha256"]}  {row["artifact"]}' for row in self.manifest['targets'].values() if row.get('status') == 'passed']
        (self.output / 'SHA256SUMS.txt').write_text('\n'.join(rows) + '\n', encoding='ascii')

    def validate(self):
        if self.validated: return
        if self.validation_started: raise failures.BlockedByShared(getattr(self, 'shared_failure', None))
        self.validation_started = True
        try:
            self.run_shared_validation()
        except Exception as error:  # remembered once: every later target is blocked by it, never revalidated
            self.shared_failure = error
            raise

    def run_shared_validation(self):
        self.powershell = prerequisite_versions()
        needs_powershell = any(host_for(t, self.system) == self.system and t in ('desktop', 'service') for t in requested(self.args.platform))
        if not self.powershell and needs_powershell: raise ValueError('Windows packaging requires Windows PowerShell 5.1 or PowerShell 7.')
        # Linux and Docker packaging is Python-only. Without PowerShell the script parse check cannot run: it is recorded as not verified, never as passed.
        self.env.pop('SAP_LENS_SKIPPED_CHECKS', None)
        if not self.powershell: self.env['SAP_LENS_SKIPPED_CHECKS'] = 'powershell'
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
        tools = ['--installer'] if self.system == 'Windows' and 'desktop' in requested(self.args.platform) else []
        self.run('Managed tool preflight', [sys.executable, 'scripts/testing/ci.py', 'prerequisites', *tools])
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
        for interpreter in (self.python, self.audit): self.bootstrap_pip(interpreter)
        pip_options = ['--no-cache-dir'] if self.args.no_cache else []
        self.run('Install pinned Python build and test dependencies', [self.python, '-m', 'pip', 'install', *pip_options, '-r', 'backend/requirements-dev.txt', '-r', 'backend/requirements-build.txt'])
        pip_pin = next(line for line in (ROOT / 'backend/requirements-build.txt').read_text().splitlines() if line.startswith('pip=='))
        self.run('Install pinned audit tooling', [self.audit, '-m', 'pip', 'install', *pip_options, pip_pin, '-r', 'scripts/requirements-audit.txt'])
        workspace, frontend = self.prepare_workspace()
        cache = ['--cache', self.env['RUNNER_TEMP'] + '/cold-npm'] if self.args.no_cache else []
        node_version = subprocess.check_output([tool('node'), '--version'], text=True, env=self.env).strip().lstrip('v')
        frontend_workspace.install(workspace, frontend_workspace.dependency_stamp(ROOT, node_version), lambda label: self.run(
            label, [tool('npm'), '--prefix', frontend, 'ci', '--no-audit', '--no-fund', *cache], cwd=workspace))
        timing = Path(self.env['RUNNER_TEMP']) / 'sap-lens-ci-timings.jsonl'
        if timing.exists(): timing.unlink()
        commands = [
            ('pip_check', [self.python, '-m', 'pip', 'check']),
            ('workflow_lint', [self.python, 'scripts/testing/ci.py', 'lint']),
            ('backend', [self.python, 'scripts/run-tests.py', *(['regression'] if self.args.scope=='full' else ['targeted','deployment']), '--backend']),
            ('types', [tool('npm'), '--prefix', frontend, 'run', 'check:types']),
            ('catalog', [tool('node'), 'scripts/sync-lucide-catalog.mjs', '--check']),
            ('build', [tool('npm'), '--prefix', frontend, 'run', 'build']),
            ('javascript_audit', [tool('npm'), '--prefix', frontend, 'audit', '--omit=dev']),
        ]
        if self.powershell: commands.insert(2, ('powershell', [self.powershell, '-NoProfile', '-File', 'scripts/check-powershell.ps1']))
        for stage, command in commands: self.run(stage, command, timed=stage, cwd=workspace if stage in ('types', 'catalog', 'build', 'javascript_audit') else None)
        installed = subprocess.check_output([str(self.python), '-m', 'pip', 'list', '--format=freeze'], env=self.env, text=True)
        requirements = Path(self.env['RUNNER_TEMP']) / 'audit-installed.txt'; requirements.write_text(installed)
        self.run('Audit all installed build/runtime dependencies', [self.audit, '-m', 'pip_audit', '--disable-pip', '--no-deps', '-r', requirements], timed='python_audit')
        browser = self.env.get('PLAYWRIGHT_EXECUTABLE_PATH')
        if browser:
            if not Path(browser).is_file(): raise ValueError('Configured Playwright executable does not exist.')
            print('Using the explicitly configured Playwright browser executable.')
        else:
            self.run('Install the pinned Playwright Chromium headless shell', [tool('node'), frontend / 'node_modules/playwright/cli.js', 'install', 'chromium', '--only-shell'], cwd=workspace)
        self.run('Browser regression tests', [tool('npm'), '--prefix', frontend, 'run', 'test:browser', '--', '--workers=1', *(['--grep-invert','@repository-only'] if self.args.scope=='full' else ['--grep','@smoke'])], timed='browser', cwd=workspace)
        self.stage = 'Publish verified frontend assets'
        print(f'{self.stage}: {frontend_workspace.publish_dist(workspace, ROOT)} files', flush=True)
        self.run('Seal successful local validation', [self.python, 'scripts/deployment-package.py', 'record-local'])
        self.validated = True

    def local(self, target):
        if target == 'docker':
            actual = subprocess.check_output([tool('docker'), 'info', '--format', '{{.OSType}}/{{.Architecture}}'], text=True).strip()
            if actual not in ('linux/x86_64', 'linux/amd64'): raise ValueError('Select an x86-64 Linux Docker engine (Docker Desktop Linux containers on Windows).')
        self.current_target = target
        self.validate()
        stem, ext = STEMS[target]; name = f'sap-lens-{stem}-v{self.args.version}{ext}'
        if (self.output / name).exists(): raise ValueError('Artifact already exists. Choose a new --output-dir; existing packages are preserved.')
        accept = False
        with tempfile.TemporaryDirectory(prefix='deployment-', dir=self.build) as temporary:
            destination = Path(temporary)
            if target in ('desktop', 'service'):
                accept = target == 'service' and (getattr(self.args, 'native_acceptance', False) or os.environ.get('GITHUB_ACTIONS') == 'true')
                self.run('Canonical Windows package and native smoke tests', [self.powershell, '-NoProfile', '-File', 'scripts/package-windows-deployment.ps1', '-Target', 'Desktop' if target == 'desktop' else 'Service', '-OutputDirectory', destination, *(['-NativeAcceptance'] if accept else [])])
            elif target == 'linux-native':
                self.run('Canonical Linux native package', [self.python, 'scripts/deployment-package.py', 'native', '--output', destination])
                self.run('Offline installation and runtime/persistence smoke tests', [self.python, 'scripts/testing/test-native-deployment.py', '--artifacts', destination])
            else:
                self.run('Canonical Docker package and runtime/persistence smoke tests', [self.python, 'scripts/deployment/package-docker.py', '--output', destination, *(['--no-cache'] if self.args.no_cache else [])])
            self.stage = 'Final artifact collection and checksum'
            archive = destination / name
            if not archive.is_file(): raise ValueError('Canonical packager did not produce the expected versioned artifact.')
            digest = module('deployment-package').sha(archive)
            sidecar = archive.with_name(name + '.sha256')
            if sidecar.read_text(encoding='utf-8').strip() != digest + '  ' + name: raise ValueError('Canonical checksum differs.')
            artifacts.collect(archive, self.output, self.args.version, self.source, target, digest)
        # Three separate facts: the artifact was built, its package was verified, and (for the Windows service) the privileged native SCM acceptance ran.
        acceptance = dict(kind='windows-scm', status='passed' if accept else 'not_run', requires='administrator',
                          command='powershell -NoProfile -File scripts\\test-server-service.ps1 -Bundle <service bundle>  (elevated)') if target == 'service' else dict(kind='none', status='not_applicable')
        return dict(status='passed', built=True, package_verified=True, runtime_smoke_tested=(accept if target == 'service' else True), native_acceptance=acceptance,
                    artifact=name, sha256=digest, host_os=self.system, build_environment=self.system + ' native' if target != 'docker' else 'Linux Docker engine',
                    tested_at=datetime.now(timezone.utc).isoformat())

    def remote(self, system, targets):
        host = self.args.windows_host if system == 'Windows' else self.args.linux_host
        repository = self.args.windows_repository if system == 'Windows' else self.args.linux_repository
        if not host or not repository:
            raise ValueError(f'Configure --{system.lower()}-host and --{system.lower()}-repository for a trusted {system} builder synchronized to this commit. No cross-compilation or silent skip.')
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]*', host): raise ValueError('Use a safe SSH host alias; configure ports/keys in SSH config.')
        flags = ['--scope', self.args.scope] + (['--clean'] if self.args.clean else []) + (['--no-cache'] if self.args.no_cache else []) + (['--native-acceptance'] if getattr(self.args, 'native_acceptance', False) else []) + (['--reuse-validation'] if self.args.reuse_validation else [])
        nonce = uuid.uuid4().hex
        command = remote_command(system, repository, self.source, self.args.version, targets, [*flags,'--invocation',nonce])
        ssh = [tool('ssh'), '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', host, command]
        # All remote targets still run independently. A nonzero exit can have valid sibling outputs.
        with self.log.open('a') as log: subprocess.run(ssh, stdout=log, stderr=subprocess.STDOUT)
        with tempfile.TemporaryDirectory(prefix='remote-deployment-', dir=self.build) as temporary:
            destination = Path(temporary)
            remote_root = repository.replace('\\', '/').rstrip('/') + '/dist/' + output_name(self.args.version, self.source)
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
                stem, ext = STEMS[target]; name = f'sap-lens-{stem}-v{self.args.version}{ext}'
                if row.get('artifact') != name or (self.output / name).exists(): raise ValueError('Unexpected remote filename or existing local artifact.')
                for filename in (name, name + '.sha256'):
                    subprocess.run([*scp, host + ':' + remote_root + '/' + filename, str(destination)], check=True, stdout=subprocess.DEVNULL)
            verify_outputs(destination, self.args.version, self.source, targets, remote=True)
            for target in targets:
                row = result.get('targets', {}).get(target, {})
                if row.get('status') == 'passed':
                    artifacts.collect(destination / row['artifact'], self.output, self.args.version, self.source, target, row['sha256'])
                self.manifest['targets'][target] = row or dict(status='failed', error='Remote builder did not report the requested target.')

    def record_of(self, error):
        if isinstance(error, failures.StageFailure): return error.as_record()
        return dict(failed_stage=self.stage, failure_class='validation', error=str(error) if isinstance(error, ValueError) else type(error).__name__ + ': ' + str(error))

    def failed_row(self, target, error):
        """A target's own failure, or `blocked` when shared validation (not this target) failed. Blocked targets are never attempted or revalidated."""
        base = dict(built=False, package_verified=False, runtime_smoke_tested=False, host_os=self.system)
        shared = getattr(self, 'shared_failure', None)
        if shared is not None and (error is shared or isinstance(error, failures.BlockedByShared)):
            record = self.record_of(shared)
            if 'shared_validation' not in self.manifest:
                self.manifest['shared_validation'] = dict(status='failed', **record)
                print(shared.summary() if isinstance(shared, failures.StageFailure) else 'Shared validation failed: ' + str(shared), file=sys.stderr, flush=True)
            return dict(status='blocked', blocked_by='shared_validation', error=f'Not attempted (blocked, not a packaging failure): shared {record["failure_class"]} failure at "{record["failed_stage"]}": {record.get("error")}. Log: {record.get("log") or self.log}. Recovery: {record.get("hint") or "fix the cause in the log and run the same command again"}', **base)
        record = self.record_of(error)
        if isinstance(error, failures.StageFailure): print(error.summary(), file=sys.stderr, flush=True)
        if record.get('failure_class') == 'acceptance_prerequisite':
            # A missing prerequisite of the privileged acceptance is neither a packaging nor a validation failure: nothing was attempted past the check.
            return dict(status='blocked', blocked_by='acceptance_prerequisite', native_acceptance=dict(kind='windows-scm', status='blocked', reason='administrator rights required'), **base, **record)
        return dict(status='failed', **base, **record)

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
                self.manifest['targets'][target] = self.failed_row(target, error)
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
    parser.add_argument('--version', default=product_version())
    parser.add_argument('--clean', action='store_true')
    parser.add_argument('--no-cache', action='store_true')
    parser.add_argument('--native-acceptance', action='store_true', help='run the privileged native Windows service (SCM) acceptance; requires an elevated shell')
    parser.add_argument('--reuse-validation', action='store_true')
    parser.add_argument('--verify-output', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--scope', choices=('targeted','full'), default='targeted')
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--windows-host'); parser.add_argument('--windows-repository')
    parser.add_argument('--linux-host'); parser.add_argument('--linux-repository')
    parser.add_argument('--invocation', default=uuid.uuid4().hex, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not re.fullmatch('[0-9a-f]{32}',args.invocation): parser.error('Invalid build invocation identity.')
    if sys.version_info[:2] != (3,12): parser.error('Use Python 3.12 to match the supported build toolchain.')
    if os.environ.get('GITHUB_ACTIONS') == 'true': parser.error('Local orchestration cannot impersonate CI. Use the approved deployment workflow.')
    if args.verify_output:
        if not args.output_dir:parser.error('--verify-output requires --output-dir')
        verify_outputs(args.output_dir,args.version,checkout(),requested(args.platform),release=True)
        print('Release preparation: source, target artifacts, exact contents and checksums verified. No publication.')
        return 0
    if args.clean and args.reuse_validation: parser.error('--clean and --reuse-validation are mutually exclusive.')
    lock = None
    legacy_lock = None
    try:
        # Cross-platform exclusive ownership without a global machine setting.
        directory = ROOT / 'backend/build'; directory.mkdir(parents=True, exist_ok=True)
        if (ROOT/'dist/.sap-lens-clean.lock').exists():raise ValueError('Cleanup owns generated build paths; retry after it finishes.')
        lock = directory / 'deployment-builder.lock'
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)
        if (ROOT/'dist/.sap-lens-clean.lock').exists():raise ValueError('Cleanup started while acquiring build ownership; retry after it finishes.')
        if sys.platform == 'win32':
            # The legacy PowerShell builder opens this same file with FileShare.None.
            # Holding an open handle prevents either entry point from changing the
            # shared environments while the other owns them.
            legacy_lock = (directory / 'local-build.lock').open('a+b')
        return Builder(args).execute()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print('Local deployment build stopped: ' + (str(error) if isinstance(error, ValueError) else type(error).__name__) + '. Check prerequisites, lock ownership and build.log.', file=sys.stderr)
        return 1
    finally:
        if legacy_lock: legacy_lock.close()
        if lock and 'descriptor' in locals(): lock.unlink(missing_ok=True)


if __name__ == '__main__': sys.exit(main())
