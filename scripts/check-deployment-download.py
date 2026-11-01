"""Verify downloaded inner archives and checksums; print an honest per-platform summary."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def check(directory):
    spec=importlib.util.spec_from_file_location('packages',ROOT/'scripts/deployment-package.py')
    pkg=importlib.util.module_from_spec(spec);spec.loader.exec_module(pkg)
    info=pkg.identity()
    names={p.name for p in directory.iterdir()}
    archives=[p for p in directory.iterdir() if p.is_file() and not p.name.endswith('.sha256')]
    if len(archives)!=1 or names!={archives[0].name,archives[0].name+'.sha256'}:raise ValueError('Unexpected downloaded artifact contents.')
    archive=archives[0]
    value=archive.with_name(archive.name+'.sha256').read_text().strip()
    match=re.fullmatch(r'([0-9a-f]{64})  '+re.escape(archive.name),value)
    if not match or pkg.sha(archive)!=match[1]:raise ValueError('Distributed checksum mismatch.')
    with tempfile.TemporaryDirectory() as temp:
        manifest=pkg.verify_extract(archive,Path(temp)/'application',match[1])
        if manifest['identity']!=info:raise ValueError('Downloaded artifact identity mismatch.')
        if 'Windows-Desktop-x64-' in archive.name:
            import subprocess
            subprocess.run([str(ROOT/'backend/build/python-env/Scripts/python.exe'),str(ROOT/'scripts/verify-desktop-distribution.py'),
                            '--directory',str(Path(temp)/'application')],check=True)
    print('Distributed package checksum and exact contents verified: '+archive.name)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a',encoding='utf-8') as output:
            output.write('package_name='+archive.name+'\npackage_sha='+match[1]+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',type=Path);p.add_argument('--summary',action='store_true');a=p.parse_args()
    if a.summary:
        report=f"### {os.environ.get('PLATFORM_LABEL','Deployment')}\n\nResult: {os.environ.get('PLATFORM_RESULT','unknown')} · Version: {os.environ.get('DEPLOYMENT_VERSION','unknown')} · Source: {os.environ.get('GITHUB_SHA','local')}\n\nNative reboot/recovery/UNC and physical-device acceptance are not implied by automated packaging checks.\n"
        print(report)
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as output:output.write(report)
    else:check(a.directory)
