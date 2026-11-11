"""Python port of scripts/build-desktop-installer.ps1 (pinned per-user Inno Setup, installer compilation, compile check). Unverified on Windows."""
import os
import sys
from pathlib import Path
if __name__ == '__main__':  # direct execution: make the build_system package importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import argparse
import hashlib
import json
import re
import shutil
import uuid

from build_system.windows.stages import ROOT, Process, StageError, venv_python

from build_system import managed_tools
INNO_VERSION = managed_tools.INNO_VERSION
INNO_URL = managed_tools.INNO_URL
INNO_SHA256 = managed_tools.INNO_SHA256


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def download(url, target):
    managed_tools.atomic_write(Path(target), managed_tools.acquire_inno())


def build(OutputDirectory, CompileCheck=False, root=ROOT, process=None, environ=None, windows=None, fetch=download, host_python='python'):
    process = process or Process()
    env = dict(os.environ if environ is None else environ)
    if not (os.name == 'nt' if windows is None else windows):
        raise StageError('Build the desktop installer on Windows.')
    python = venv_python(root)
    if not CompileCheck:
        if process.run([str(python), str(root / 'scripts/deployment-package.py'), 'require-inputs'], root, env) != 0:
            raise StageError('Validated deployment inputs are required.')
    tool_root = root / f'backend/build/inno-setup-{INNO_VERSION}'
    compiler, receipt = tool_root / 'ISCC.exe', tool_root / 'compiler-sha256.txt'
    if not compiler.exists():
        installer = root / f'backend/build/innosetup-{INNO_VERSION}-x64.exe'
        fetch(INNO_URL, installer)
        if sha256(installer) != INNO_SHA256:
            raise StageError('Inno Setup download SHA-256 mismatch.')
        # One verbatim command line: Start-Process joined the arguments with literal quotes around /DIR, which list quoting would escape.
        command = f'"{installer}" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER /DIR="{tool_root}"'
        if process.run(command, root, env) != 0 or not compiler.exists():
            raise StageError('Pinned per-user Inno Setup provisioning failed. Review prerequisites and tool installer logs.')
        receipt.write_text(sha256(compiler), encoding='ascii')
    if not receipt.exists() or sha256(compiler) != receipt.read_text(encoding='utf-8-sig').strip():
        raise StageError('Build compiler changed after verified provisioning. Review the dedicated tool directory.')

    def compile_installer(source_exe, full_version, numeric_version, destination):
        arguments = [str(compiler), '/Qp', f'/O{destination}', f'/DSourceExe={source_exe}', f'/DProductLicense={root / "LICENSE.md"}', f'/DProductIcon={root / "assets/sap-lens.ico"}',
                     f'/DFullVersion={full_version}', f'/DNumericVersion={numeric_version}', str(root / 'deploy/windows/desktop-installer.iss')]
        if process.run(arguments, root, env) != 0:
            raise StageError('Inno Setup compilation failed.')

    output_directory = Path(OutputDirectory)
    if CompileCheck:
        # Compile the complete production recipe before any Python dependency or application packaging; the fixtures are never executed or distributed.
        check_environment = root / 'backend/build/installer-check-env'
        if process.run([host_python, '-m', 'venv', str(check_environment)], root, env) != 0:
            raise StageError('Installer check environment creation failed.')
        check_python = check_environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        pins = [line.strip() for line in (root / 'backend/requirements-build.txt').read_text(encoding='utf-8-sig').splitlines() if re.fullmatch(r'pefile==[0-9.]+', line.strip())]
        if len(pins) != 1:
            raise StageError('The existing PE verifier requires one canonical dependency pin.')
        if process.run([str(check_python), '-m', 'pip', 'install', '--disable-pip-version-check', pins[0]], root, env) != 0:
            raise StageError('Installer verifier dependency provisioning failed.')
        temporary = output_directory / ('recipe-' + uuid.uuid4().hex)
        temporary.mkdir(parents=True, exist_ok=True)
        try:
            payload = temporary / 'SAP-Lens.exe'
            shutil.copy2(compiler, payload)
            for channel in ('alpha', 'beta', 'rc', 'stable'):
                full = '0.1.0' if channel == 'stable' else f'0.1.0-{channel}.1'
                numeric = '0.1.0.0' if channel == 'stable' else '0.1.0.1'
                destination = temporary / channel
                destination.mkdir()
                compile_installer(payload, full, numeric, destination)
                produced = destination / 'SAP-Lens-Setup.exe'
                if not produced.is_file():
                    raise StageError('Inno Setup did not produce the compiler-check fixture.')
                if process.run([str(check_python), str(root / 'scripts/packaging/verify-desktop-installer.py'), '--installer', str(produced), '--compiler-fixture-channel', channel], root, env) != 0:
                    raise StageError('Compiled installer fixture resource verification failed.')
                print(f'Installer recipe compiled and PE resources verified: {channel}. Application installation was not tested.')
        finally:
            shutil.rmtree(temporary, ignore_errors=True)
        return None
    info = json.loads((root / 'backend/build/build-version.json').read_text(encoding='utf-8-sig'))
    version = str(info['version'])
    executable = root / 'backend/dist/SAP-Lens.exe'
    approved = json.loads((root / 'backend/build/package-verification.json').read_text(encoding='utf-8-sig'))
    if sha256(executable) != approved['exe_sha256']:
        raise StageError('Portable executable changed after canonical verification.')
    output_directory.mkdir(parents=True, exist_ok=True)
    compile_installer(executable, version, '.'.join(str(part) for part in info['file_version']), output_directory)
    named = output_directory / f'SAP-Lens-Windows-Desktop-x64-{version}-Setup.exe'
    shutil.move(str(output_directory / 'SAP-Lens-Setup.exe'), str(named))
    named.with_name(named.name + '.sha256').write_bytes(f'{sha256(named)}  {named.name}\n'.encode('ascii'))
    shutil.copy2(tool_root / 'license.txt', output_directory / 'LICENSE-Inno-Setup.txt')
    if process.run([str(python), str(root / 'scripts/packaging/verify-desktop-installer.py'), '--installer', str(named)], root, env) != 0:
        raise StageError('Installer verification failed.')
    print('Unsigned per-user installer compiled and metadata verified. Native installation/lifecycle acceptance is separate.')
    return named


def main(argv=None):
    parser = argparse.ArgumentParser(description='Python port of build-desktop-installer.ps1 (unverified on Windows).')
    parser.add_argument('-OutputDirectory', required=True)
    parser.add_argument('-CompileCheck', action='store_true')
    options = parser.parse_args(argv)
    try:
        build(options.OutputDirectory, options.CompileCheck)
    except (StageError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
