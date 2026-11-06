"""Python port of scripts/build-server-windows.ps1 (headless Windows service bundle). Unverified on Windows."""
import os
import sys
from pathlib import Path
if __name__ == '__main__':  # direct execution: make the build_system package importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import argparse
import hashlib
import json
import shutil

from build_system.windows import service_manager
from build_system.windows.stages import ROOT, Process, StageError, venv_python

WINSW_SHA256 = '05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(WinSW='', Version='', ValidatedDeployment=False, OutputDirectory='', root=ROOT, process=None, environ=None, windows=None, build_manager=None):
    process = process or Process()
    env = dict(os.environ if environ is None else environ)
    is_windows = (os.name == 'nt' and os.environ.get('PROCESSOR_ARCHITECTURE') == 'AMD64') if windows is None else windows
    if not is_windows:
        raise StageError('Build the server bundle on x64 Windows.')
    python = venv_python(root)
    if not python.exists():
        raise StageError('Run scripts\\build.ps1 -Mode build -Platform windows -Target service first.')

    def checked(command):
        if process.run([str(part) for part in command], root, env) != 0:
            raise StageError('Server build failed. No verified bundle was produced.')

    if not Version:
        code, Version = process.capture([str(python), 'scripts/packaging/local-build.py', 'version'], root, env)
        if code != 0:
            raise StageError('Unable to resolve the authoritative product version.')
    checked([python, 'scripts/packaging/local-build.py', 'tools'])
    if ValidatedDeployment:
        checked([python, 'scripts/deployment-package.py', 'require-inputs'])
        Version = json.loads((root / 'backend/build/build-version.json').read_text(encoding='utf-8-sig'))['version']
    else:
        checked([python, 'scripts/packaging/local-build.py', 'check', '--version', Version])
    if not WinSW:
        WinSW = str(root / 'backend/build/WinSW-x64.exe')
        checked([python, 'scripts/packaging/local-build.py', 'winsw', '--output', WinSW])
    if sha256(WinSW) != WINSW_SHA256:
        raise StageError('WinSW SHA-256 does not match the official pinned v2.12.0 x64 release.')
    output = Path(OutputDirectory) if OutputDirectory else root / 'dist/server' / Version
    if output.exists():
        raise StageError('Output already exists. Use a new empty output directory/version after reviewing the previous build.')
    checked([python, 'scripts/packaging/write-windows-metadata.py'])
    frontend_dist, icon, image = root / 'frontend/dist', root / 'assets/sap-lens.ico', root / 'assets/sap-lens.png'
    identity, resources, metadata = root / 'backend/build/build-version.json', root / 'backend/resources', root / 'backend/build/version-info.txt'
    for required in (frontend_dist, icon, image, identity, metadata):
        if not required.exists():
            raise StageError('A required server packaging input is missing.')
    # Console bootloader is required for WinSW Ctrl+C shutdown. No WebView2 runtime hooks.
    checked([python, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--console', '--noupx', '--name', 'SAP-Lens', '--distpath', f'{output}/app', '--workpath', 'backend/build/server',
             '--specpath', 'backend/build/server', '--paths', root / 'backend', '--icon', icon, '--version-file', metadata, '--add-data', f'{frontend_dist};frontend/dist',
             '--add-data', f'{icon};assets', '--add-data', f'{image};assets', '--add-data', f'{identity};.', '--add-data', f'{resources};resources', '--collect-data', 'docx',
             '--collect-data', 'reportlab', '--hidden-import', 'tzdata', '--collect-data', 'tzdata', '--copy-metadata', 'tzdata', '--copy-metadata', 'python-docx', '--copy-metadata', 'reportlab',
             '--copy-metadata', 'lxml', '--copy-metadata', 'charset-normalizer', '--exclude-module', 'webview', '--exclude-module', 'pythonnet', '--exclude-module', 'clr', 'backend/server.py'])
    app = output / 'app'
    for entry in list((app / 'SAP-Lens').iterdir()):
        shutil.move(str(entry), str(app / entry.name))
    shutil.rmtree(app / 'SAP-Lens')
    shutil.copy2(WinSW, output / 'SAPLensService.exe')
    (build_manager or service_manager.build)(output)
    shutil.copy2(root / 'scripts/manage-server-service.ps1', output)
    shutil.copy2(root / 'deploy/windows/LICENSE-WinSW.txt', output)
    shutil.copy2(root / 'LICENSE.md', output)
    shutil.copy2(root / 'docs/deployment/WINDOWS_SERVICE.md', output / 'README.md')
    checked([python, 'scripts/deployment-package.py', 'readme', '--document', 'docs/deployment/WINDOWS_SERVICE.md', '--directory', output])
    checked([python, 'scripts/packaging/verify-server-bundle.py', output])
    print(f'Verified headless server bundle: {output}. Signing is disabled. Install/start and stop tests on the target Windows Server are still required.')
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description='Python port of build-server-windows.ps1 (unverified on Windows).')
    parser.add_argument('-WinSW', default='')
    parser.add_argument('-Version', default='')
    parser.add_argument('-ValidatedDeployment', '-ValidatedCI', action='store_true', dest='ValidatedDeployment')
    parser.add_argument('-OutputDirectory', default='')
    options = parser.parse_args(argv)
    try:
        build(options.WinSW, options.Version, options.ValidatedDeployment, options.OutputDirectory)
    except (StageError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
