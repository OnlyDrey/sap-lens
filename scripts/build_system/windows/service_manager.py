"""Python port of scripts/build-service-manager.ps1 (compiles the .NET Framework GUI and runs its disposable self-test). Unverified on Windows."""
import os
import sys
from pathlib import Path
if __name__ == '__main__':  # direct execution: make the build_system package importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import argparse
import json
import shutil
import uuid

from build_system.windows.stages import ROOT, Process, StageError

REFERENCES = ['/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll', '/reference:System.Xml.Linq.dll', '/reference:System.Web.Extensions.dll', '/reference:System.ServiceProcess.dll']
HARNESS = 'class SapLensSelfTest { public static int Main() { try { SapLens.ServiceSetup.SelfTest(); return 0; } catch { return 1; } } }'
SELF_TEST_MANIFEST = ('<assembly manifestVersion="1.0" xmlns="urn:schemas-microsoft-com:asm.v1"><trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges>'
                      '<requestedExecutionLevel level="asInvoker" uiAccess="false"/></requestedPrivileges></security></trustInfo></assembly>')


def attributes(numbers, version):
    return (f'using System.Reflection;\r\n[assembly: AssemblyTitle("SAP Lens Service Manager")]\r\n[assembly: AssemblyProduct("SAP Lens")]\r\n'
            f'[assembly: AssemblyCompany("SAP Lens contributors")]\r\n[assembly: AssemblyVersion("{numbers}")]\r\n[assembly: AssemblyFileVersion("{numbers}")]\r\n'
            f'[assembly: AssemblyInformationalVersion("{version}")]\r\n')


def build(output_directory, root=ROOT, process=None, windir=None, environ=None, guid=None):
    process = process or Process()
    env = dict(os.environ if environ is None else environ)
    windir = windir if windir is not None else env.get('WINDIR', '')
    compiler = Path(windir) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    if not compiler.exists():
        raise StageError('Install .NET Framework 4.8 on the Windows builder.')
    identity = json.loads((root / 'backend/build/build-version.json').read_text(encoding='utf-8-sig'))
    numbers = '.'.join(str(part) for part in identity['file_version'])
    generated = root / 'backend/build/service-manager-version.cs'
    generated.write_text(attributes(numbers, identity['version']), encoding='utf-8-sig')
    output = Path(output_directory) / 'SAP-Lens-Service-Manager.exe'
    source = root / 'deploy/windows/ServiceManager.cs'
    command = [compiler, '/nologo', '/target:winexe', '/platform:x64', '/optimize+', f'/out:{output}', f'/win32icon:{root / "assets/sap-lens.ico"}',
               f'/win32manifest:{root / "deploy/windows/service-manager.manifest"}', *REFERENCES, source, generated]
    if process.run([str(part) for part in command], root, env) != 0:
        raise StageError('Service manager compilation failed.')
    # The shipped manager requires elevation; exercise the same SelfTest through a disposable asInvoker harness.
    temporary = root / 'backend/build' / ('service-manager-check-' + (guid or uuid.uuid4().hex))
    temporary.mkdir(parents=True)
    try:
        harness, manifest, check = temporary / 'SelfTest.cs', temporary / 'self-test.manifest', temporary / 'SelfTest.exe'
        harness.write_text(HARNESS, encoding='utf-8-sig')
        manifest.write_text(SELF_TEST_MANIFEST, encoding='utf-8-sig')
        command = [compiler, '/nologo', '/target:exe', '/platform:x64', '/main:SapLensSelfTest', f'/out:{check}', f'/win32manifest:{manifest}', *REFERENCES, source, harness]
        if process.run([str(part) for part in command], root, env) != 0:
            raise StageError('Service manager self-test harness compilation failed.')
        if process.run([str(check)], root, env) != 0:
            raise StageError('Service manager self-test failed.')
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Python port of build-service-manager.ps1 (unverified on Windows).')
    parser.add_argument('-OutputDirectory', required=True)
    options = parser.parse_args(argv)
    try:
        build(options.OutputDirectory)
    except (StageError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
