"""Python port of scripts/build-windows.ps1 (the Windows build stages).

Status: implemented and contract-tested on Linux against golden command lists; NOT yet verified on Windows. The PowerShell original stays the default.
Opt in with SAP_LENS_WINDOWS_STAGES=python (the `windows-stage` CI adapter of build.py) or run this file directly:

    python scripts/build_system/windows/stages.py -Stage Package -ValidatedDeployment

The option names, stage names, order, commands, timing records, log markers and exit codes mirror the PowerShell script. Standard library only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
STAGES = ('All', 'Environment', 'Frontend', 'FrontendInstall', 'FrontendBuild', 'Python', 'Audit', 'JavaScriptAudit', 'Backend', 'Browser', 'Package', 'Verify', 'Smoke', 'Artifact')
TARGETED_BACKEND_TESTS = ('test_desktop.py', 'test_windows_package.py', 'test_server.py', 'test_build_version.py', 'test_local_build.py')


class StageError(RuntimeError):
    pass


def venv_python(root):
    return root / 'backend/build/python-env' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def powershell():
    return shutil.which('pwsh') or shutil.which('powershell') or 'pwsh'


class Process:
    """Executes commands; tests replace it with a recorder."""
    def run(self, command, cwd, env):
        return subprocess.run(command, cwd=cwd, env=env).returncode

    def capture(self, command, cwd, env):
        done = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
        return done.returncode, done.stdout.strip()


class WindowsStages:
    def __init__(self, options, root=ROOT, process=None, environ=None, printer=print):
        self.o = options
        self.root = Path(root)
        self.process = process or Process()
        self.environ = dict(os.environ if environ is None else environ)
        self.print = printer
        self.build_python = venv_python(self.root)
        self.host_python = options.PythonExecutable or shutil.which('python') or sys.executable
        self.audit_python = options.AuditPython or self.host_python

    # --- helpers mirroring the PowerShell functions -------------------------------------------------------------------------------------------
    def assert_success(self, stage, code):
        if code == 0:
            return
        message = f'{stage} failed with exit code {code}'
        if self.environ.get('GITHUB_ACTIONS') == 'true':
            self.print(f'::error title=SAP Lens build::{message}')
        raise StageError(message)

    def env(self):
        env = dict(self.environ)
        env['PATH'] = str(self.build_python.parent) + os.pathsep + env.get('PATH', '')
        return env

    def run(self, name, command, cwd=None):
        self.assert_success(name, self.process.run([str(part) for part in command], cwd or self.root, self.env()))

    def measure(self, name, action):
        started = time.monotonic()
        status = 'failed'
        self.print(f'::group::{name}')
        try:
            action()
            status = 'passed'
        finally:
            seconds = round(time.monotonic() - started, 2)
            self.print(f'TIMING {name} : {seconds} seconds ({status})')
            self.print('::endgroup::')
            try:
                directory = self.root / 'backend/build'
                directory.mkdir(parents=True, exist_ok=True)
                with (directory / 'timings.jsonl').open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps({'stage': name, 'seconds': seconds, 'status': status}, separators=(',', ':')) + '\n')
            except OSError:
                self.print('::warning::Stage timing could not be saved; inspect the task log.')

    def selected(self, name):
        stage = self.o.Stage
        return stage == 'All' or stage == name or (name in ('FrontendInstall', 'FrontendBuild') and stage == 'Frontend')

    def npm(self):
        return shutil.which('npm') or 'npm'

    # --- stages -------------------------------------------------------------------------------------------------------------------------------
    def environment(self):
        timings = self.root / 'backend/build/timings.jsonl'
        if timings.exists():
            timings.unlink()
        for report in ('package-verification.json', 'artifact-verification.json'):
            path = self.root / 'backend/build' / report
            if path.exists():
                path.unlink()
        self.measure('Python environment creation', lambda: self.run('Create build environment', [self.host_python, '-m', 'venv', 'backend/build/python-env']))

    def frontend_install(self):
        self.measure('npm installation', lambda: self.run('Install frontend dependencies', [self.npm(), 'ci', '--no-audit', '--no-fund'], self.root / 'frontend'))

    def frontend_build(self):
        self.measure('Frontend compilation', lambda: self.run('Build production frontend', [self.npm(), 'run', 'build'], self.root / 'frontend'))

    def python(self):
        def action():
            self.run('Install build and test dependencies', [self.build_python, '-m', 'pip', 'install', '--disable-pip-version-check', '-r', 'backend/requirements-build.txt', '-r', 'backend/requirements-dev.txt'])
            self.run('Check Python dependencies', [self.build_python, '-m', 'pip', 'check'])
        self.measure('Python dependency installation', action)

    def audit(self):
        # Audit tooling uses its own interpreter and cannot enter the packaged environment.
        self.measure('Audit tool provisioning', lambda: self.run('Install audit tooling', [self.audit_python, '-m', 'pip', 'install', '--disable-pip-version-check', '-r', 'scripts/requirements-audit.txt']))

        def action():
            code, site = self.process.capture([str(self.build_python), '-c', "import sysconfig; print(sysconfig.get_paths()['purelib'])"], self.root, self.env())
            self.assert_success('Locate build dependencies', code)
            self.run('Audit Windows dependencies', [self.audit_python, '-m', 'pip_audit', '--path', site, '--vulnerability-service', 'pypi', '--progress-spinner', 'off'])
        self.measure('Python vulnerability audit', action)

    def javascript_audit(self):
        self.measure('Production JavaScript audit', lambda: self.run('Audit production JavaScript dependencies', [self.npm(), 'audit', '--omit=dev'], self.root / 'frontend'))

    def backend(self):
        def action():
            if self.o.TargetedValidation:
                for pattern in TARGETED_BACKEND_TESTS:
                    self.run(f'Packaging backend tests: {pattern}', [self.build_python, '-W', 'error::DeprecationWarning', '-m', 'unittest', 'discover', '-s', 'backend/tests', '-p', pattern, '-v'])
            else:
                self.run('Backend regression tests', [self.build_python, '-W', 'error::DeprecationWarning', '-m', 'unittest', 'discover', '-s', 'backend/tests', '-v'])
        self.measure('Backend tests', action)

    def browser(self):
        frontend = self.root / 'frontend'
        self.measure('Production JavaScript audit', lambda: self.run('Audit production JavaScript dependencies', [self.npm(), 'audit', '--omit=dev'], frontend))
        self.measure('Playwright installation', lambda: self.run('Install test browser', ['node', 'node_modules/playwright/cli.js', 'install', 'chromium', '--only-shell'], frontend))

        def action():
            command = [self.npm(), 'run', 'test:browser', '--', '--reporter=line,github', '--workers=1']
            if self.o.TargetedValidation:
                command += ['--grep', '@smoke']
            self.run('Production browser tests', command, frontend)
        self.measure('Playwright tests', action)

    def package(self):
        python = self.build_python
        if self.o.ValidatedDeployment:
            # Deployment dispatches carry an explicit channel identity sealed by same-run shared validation.
            self.run('Require resolved build identity', [python, 'scripts/deployment-package.py', 'require-inputs'])
        else:
            self.run('Require resolved build identity', [python, 'scripts/release-windows.py', 'ensure-local-build'])
        self.run('Generate Windows metadata', [python, 'scripts/write-windows-metadata.py'])
        icon = self.root / 'assets/sap-lens.ico'
        metadata = self.root / 'backend/build/version-info.txt'
        frontend_dist = self.root / 'frontend/dist'
        identity = self.root / 'backend/build/build-version.json'
        resources = self.root / 'backend/resources'
        arguments = [
            '--noconfirm', '--onefile', '--windowed', '--noupx', '--name', 'SAP-Lens',
            '--icon', icon, '--version-file', metadata,
            '--add-data', f'{icon};assets', '--paths', 'backend',
            '--add-data', f'{identity};.', '--add-data', f'{resources};resources',
            '--add-data', f'{frontend_dist};frontend/dist', '--specpath', 'backend',
            '--collect-data', 'docx', '--collect-data', 'reportlab',
            '--hidden-import', 'tzdata', '--collect-data', 'tzdata', '--copy-metadata', 'tzdata',
            '--copy-metadata', 'python-docx', '--copy-metadata', 'reportlab', '--copy-metadata', 'lxml', '--copy-metadata', 'charset-normalizer',
            '--distpath', 'backend/dist', '--workpath', 'backend/build', 'backend/desktop.py',
        ]
        self.measure('PyInstaller packaging (clean)', lambda: self.run('Package Windows executable', [python, '-m', 'PyInstaller', '--clean', *arguments]))
        if self.o.BenchmarkPackaging:
            # A same-job experiment only; the resulting EXE still goes through the complete verifier and GUI smoke test.
            self.measure('PyInstaller packaging (same-job incremental)', lambda: self.run('Benchmark incremental packaging', [python, '-m', 'PyInstaller', *arguments]))

    def verify(self):
        def action():
            executable = self.root / 'backend/dist/SAP-Lens.exe'
            digest = hashlib.sha256(executable.read_bytes()).hexdigest()
            newline = '\r\n' if os.name == 'nt' else '\n'   # Set-Content ends the line with the platform newline
            (self.root / 'backend/dist/SAP-Lens.exe.sha256').write_bytes(f'{digest}  SAP-Lens.exe{newline}'.encode('ascii'))
            self.run('Verify Windows package assets and privacy', [self.build_python, 'scripts/verify-windows-package.py'])
        self.measure('Package verification and checksum', action)

    def smoke(self):
        # The PowerShell smoke test is Windows-native and stays PowerShell; it stops on error, so its exit code is the result.
        self.measure('EXE smoke testing', lambda: self.run('EXE smoke testing', [powershell(), '-NoProfile', '-File', self.root / 'scripts/test-windows-exe.ps1']))

    def artifact(self):
        if not self.o.ArtifactDirectory:
            raise StageError('Artifact verification needs a downloaded artifact directory.')

        def action():
            if self.o.ArtifactDownloadDirectory:
                self.run('Verify ZIP digest and exact distribution members', [self.build_python, 'scripts/verify-artifact-zip.py', '--download', self.o.ArtifactDownloadDirectory,
                                                                             '--destination', self.o.ArtifactDirectory, '--expected-digest', self.o.ArtifactDigest or ''])
            verified = json.loads((self.root / 'backend/build/package-verification.json').read_text(encoding='utf-8-sig'))
            self.run('Verify downloaded artifact matches the approved executable', [self.build_python, 'scripts/verify-windows-package.py', '--distribution', self.o.ArtifactDirectory,
                                                                                   '--expected-sha256', verified['exe_sha256'], '--report', 'backend/build/artifact-verification.json'])
        self.measure('Downloaded artifact verification', action)

    def execute(self):
        order = (('Environment', self.environment), ('FrontendInstall', self.frontend_install), ('FrontendBuild', self.frontend_build), ('Python', self.python), ('Audit', self.audit),
                 ('JavaScriptAudit', self.javascript_audit), ('Backend', self.backend), ('Browser', self.browser), ('Package', self.package), ('Verify', self.verify), ('Smoke', self.smoke))
        for name, action in order:
            if self.selected(name):
                action()
        if self.o.Stage == 'Artifact':
            self.artifact()
        self.print(f'Completed build stage: {self.o.Stage}')


def parser():
    result = argparse.ArgumentParser(description='SAP Lens Windows build stages (Python port of build-windows.ps1; unverified on Windows).')
    result.add_argument('-Stage', choices=STAGES, default='All')
    for name in ('ArtifactDirectory', 'ArtifactDownloadDirectory', 'ArtifactDigest', 'PythonExecutable', 'AuditPython'):
        result.add_argument('-' + name, default='')
    for name in ('ValidatedDeployment', 'TargetedValidation', 'BenchmarkPackaging'):
        result.add_argument('-' + name, action='store_true')
    return result


def main(argv=None):
    options = parser().parse_args(argv)
    try:
        WindowsStages(options).execute()
    except (StageError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
