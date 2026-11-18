"""Installer-first deployment with grouped evidence; portable payload remains an internal verified input."""
import argparse
import importlib.util
import json
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))


def load(name):
    spec=importlib.util.spec_from_file_location(name.replace('-','_'),next((ROOT/'scripts').rglob(name+'.py')))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def verify(directory, payload_directory):
    from version import BUILD_INFO
    packages=load('deployment-package')
    installer=f'SAP-Lens-Windows-Desktop-x64-{BUILD_INFO["version"]}-Setup.exe'
    expected={installer,'LICENSE.md','LICENSE-Inno-Setup.txt','README.md','metadata'}
    if {p.name for p in directory.iterdir()}!=expected or any(p.is_symlink() or (not p.is_file() and p.name!='metadata') for p in directory.iterdir()):raise ValueError('Unexpected desktop bundle contents.')
    metadata=directory/'metadata'
    if metadata.is_symlink() or {p.name for p in metadata.iterdir()}!={'package-manifest.json','installer-verification.json'}:raise ValueError('Unexpected desktop metadata.')
    manifest=json.loads((metadata/'package-manifest.json').read_text())
    actual=packages.files(directory);actual.pop('metadata/package-manifest.json')
    if manifest.get('schema')!=1 or manifest.get('layout')!='installer-only-v1' or manifest.get('platform')!='Windows-Desktop-x64' or manifest['identity']!=BUILD_INFO or manifest['files']!=actual:raise ValueError('Desktop bundle manifest differs.')
    packages.privacy(actual)
    sha=packages.sha(directory/installer)
    report=json.loads((metadata/'installer-verification.json').read_text(encoding='utf-8-sig'))
    if report.get('identity')!=BUILD_INFO or report.get('signing')!='disabled' or not report.get('native_installer_smoke','').startswith('passed:') or report.get('installer_sha256')!=sha or report.get('payload_sha256')!=packages.sha(payload_directory/'SAP-Lens.exe'):raise ValueError('Native installer validation receipt differs.')
    if report.get('acceptance_mode') not in (None,'isolated-app-id'):
        raise ValueError('Unknown native acceptance mode.')
    if report.get('acceptance_mode') == 'isolated-app-id':
        if (report.get('production_app_id') != '5DB5BC51-A860-44CA-93CA-09AE85812DF0'
                or not re.fullmatch('[A-F0-9]{8}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{12}', report.get('test_app_id',''))
                or report['test_app_id'] == report['production_app_id']
                or report.get('production_unchanged') is not True or report.get('cleanup_complete') is not True
                or not re.fullmatch('[a-f0-9]{64}',report.get('executed_installer_sha256',''))
                or not re.fullmatch('[a-f0-9]{64}',report.get('recipe_sha256',''))
                or report['executed_installer_sha256'] == sha):
            raise ValueError('Isolated native acceptance identity, production invariance or cleanup evidence differs.')
    with tempfile.TemporaryDirectory() as temp:
        incoming=Path(temp)/'incoming';incoming.mkdir();archive=incoming/'portable.zip'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as output:
            for name in ('SAP-Lens.exe','SAP-Lens.exe.sha256'):output.write(payload_directory/name,name)
        application=Path(temp)/'application'
        # Keep the canonical exactly-two-file ZIP guard; do not widen its allowlist.
        load('verify-artifact-zip').verify(incoming,application,packages.sha(archive))
        subprocess.run([sys.executable,str(ROOT/'scripts/packaging/verify-windows-package.py'),'--distribution',str(application)],check=True)
    load('verify-desktop-installer').verify(directory/installer)
    print('Desktop distribution exact contents, native receipt, portable integrity and installer metadata verified.')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path,required=True);parser.add_argument('--payload-directory',type=Path,required=True)
    args=parser.parse_args()
    try:verify(args.directory,args.payload_directory)
    except Exception as error:parser.exit(1,'Desktop distribution verification failed ('+type(error).__name__+'); private details omitted.\n')
