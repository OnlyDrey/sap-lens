"""Python port of scripts/package-windows-deployment.ps1 (desktop installer and service bundle packaging sequence). Unverified on Windows."""
import os
import sys
from pathlib import Path
if __name__ == '__main__':  # direct execution: make the build_system package importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import argparse
import json
import shutil
import uuid

from build_system.windows import installer, server, stages
from build_system.windows.stages import ROOT, Process, StageError, powershell, venv_python

README = """SAP Lens Desktop

Run SAP-Lens-Windows-Desktop-x64-{version}-Setup.exe to install for the current user under AppData. Administrator rights are not required. Microsoft Edge WebView2 Runtime is required.

For upgrades, close SAP Lens and run Setup again. Existing application data is preserved. Uninstall through Windows Installed Apps; data is retained by default.

The metadata directory contains integrity evidence, not launch choices. The portable EXE is an internal build input; this download contains only Setup.

Instructions: https://github.com/OnlyDrey/sap-lens/blob/work/docs/deployment/WINDOWS_DESKTOP.md
"""


def build(Target, OutputDirectory='', root=ROOT, process=None, environ=None, stage_runner=None, installer_build=None, server_build=None, guid=None, NativeAcceptance=False):
    process = process or Process()
    env = dict(os.environ if environ is None else environ)
    guid = guid or (lambda: uuid.uuid4().hex)

    def checked(command, message='Windows deployment packaging failed.'):
        if process.run([str(part) for part in command], root, env) != 0:
            raise StageError(message)

    def run_stage(stage, **flags):
        options = stages.parser().parse_args(['-Stage', stage] + [f'-{name}' for name, enabled in flags.items() if enabled])
        (stage_runner or (lambda o: stages.WindowsStages(o, root, process, env).execute()))(options)

    if Target not in ('Desktop', 'Service'):
        raise StageError('Target must be Desktop or Service.')
    checked(['python', 'scripts/deployment-package.py', 'require-inputs'])
    output = Path(OutputDirectory) if OutputDirectory else root / 'dist/deployment'
    if env.get('GITHUB_ACTIONS') == 'true':
        for stage in ('Environment', 'Python', 'Audit'):
            run_stage(stage)
    # A local receipt already binds this Windows dependency environment and audit.
    python = venv_python(root)
    for pattern in ('test_desktop.py', 'test_windows_package.py', 'test_server.py'):
        checked([python, '-W', 'error::DeprecationWarning', '-m', 'unittest', 'discover', '-s', 'backend/tests', '-p', pattern, '-v'])
    if Target == 'Desktop':
        run_stage('Package', ValidatedDeployment=True)
        run_stage('Verify')
        run_stage('Smoke')
        info = json.loads((root / 'backend/build/build-version.json').read_text(encoding='utf-8-sig'))
        bundle = root / ('backend/build/deployment-desktop-' + guid())
        bundle.mkdir(parents=True)
        shutil.copy2(root / 'LICENSE.md', bundle)
        (bundle / "README.md").write_bytes(README.format(version=info["version"]).rstrip("\n").encode("utf-8"))
        (installer_build or installer.build)(bundle)
        setup = bundle / f'SAP-Lens-Windows-Desktop-x64-{info["version"]}-Setup.exe'
        evidence = bundle / 'metadata'
        evidence.mkdir()
        checked([powershell(), '-NoProfile', '-File', root / 'scripts/test-desktop-installer.ps1', '-Installer', setup, '-Report', evidence / 'installer-verification.json'])
        # Compiler checksums remain internal; the bundle manifest binds shipped bytes.
        setup.with_name(setup.name + '.sha256').unlink()
        checked([python, 'scripts/deployment-package.py', 'finish', '--directory', bundle, '--platform', 'Windows-Desktop-x64', '--output', output])
        checked([python, 'scripts/packaging/verify-desktop-distribution.py', '--directory', bundle, '--payload-directory', 'backend/dist'])
    else:
        wrapper = root / 'backend/build/WinSW-x64.exe'
        checked([python, 'scripts/packaging/local-build.py', 'winsw', '--output', wrapper])
        bundle = root / ('backend/build/deployment-service-' + guid())
        (server_build or server.build)(WinSW=str(wrapper), ValidatedDeployment=True, OutputDirectory=str(bundle))
        if NativeAcceptance or (environ if environ is not None else os.environ).get('GITHUB_ACTIONS') == 'true':
            checked([powershell(), '-NoProfile', '-File', root / 'scripts/test-server-service.ps1', '-Bundle', bundle])
        else:
            print('Native SCM acceptance NOT RUN (packaging only). Run it elevated: scripts\\test-server-service.ps1 -Bundle ' + str(bundle))
        checked([python, 'scripts/deployment-package.py', 'finish', '--directory', bundle, '--platform', 'Windows-Service-x64', '--output', output])
    return bundle


def main(argv=None):
    parser = argparse.ArgumentParser(description='Python port of package-windows-deployment.ps1 (unverified on Windows).')
    parser.add_argument('-Target', required=True, choices=('Desktop', 'Service'))
    parser.add_argument('-OutputDirectory', default='')
    parser.add_argument('-NativeAcceptance', action='store_true')
    options = parser.parse_args(argv)
    try:
        build(options.Target, options.OutputDirectory, NativeAcceptance=options.NativeAcceptance)
    except (StageError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
