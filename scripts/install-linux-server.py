"""Target-side installation; creates a venv here, never relocates one. Data is preserved."""
import argparse
import grp
import json
import os
from pathlib import Path
import platform
import shutil
import shlex
import subprocess
import sys
import tempfile

sys.dont_write_bytecode=True
BUNDLE=Path(__file__).resolve().parents[1]


def command(*args):subprocess.run(list(map(str,args)),check=True)


def validate_bundle():
    sys.path.insert(0,str(BUNDLE/'scripts'))
    import importlib.util
    spec=importlib.util.spec_from_file_location('packages',BUNDLE/'scripts/deployment-package.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    manifest=json.loads((BUNDLE/'package-manifest.json').read_text())
    actual=module.files(BUNDLE);actual.pop('package-manifest.json')
    if actual!=manifest['files'] or manifest['platform']!='Linux-Native-x64':raise ValueError('Bundle integrity mismatch.')
    module.privacy(actual)
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['install','uninstall']);p.add_argument('--user',action='store_true',help='Local workstation installation without systemd/root')
    p.add_argument('--prefix',type=Path,default=Path('/opt/sap-lens'))
    p.add_argument('--data',type=Path,default=Path('/var/lib/sap-lens'));p.add_argument('--config',type=Path,default=Path('/etc/sap-lens/server.env'))
    p.add_argument('--no-start',action='store_true')
    a=p.parse_args()
    if sys.platform!='linux' or platform.machine()!='x86_64' or sys.version_info[:2]!=(3,12):raise ValueError('Linux x86-64 and Python 3.12 are required.')
    libc,version=platform.libc_ver()
    if libc!='glibc' or tuple(map(int,version.split('.')[:2]))<(2,35):raise ValueError('glibc 2.35+ is required (Ubuntu 22.04/24.04 baseline).')
    for path in (a.prefix,a.data,a.config):
        if not path.is_absolute() or any(c in str(path) for c in '\n\r%') or path.is_symlink():raise ValueError('Use absolute paths without links/control characters/specifiers.')
    a.prefix=a.prefix.resolve();a.data=a.data.resolve();a.config=a.config.resolve()
    protected={Path(value) for value in ('/','/etc','/usr','/var','/opt','/home','/srv','/root','/bin','/sbin','/tmp')}
    if a.prefix in protected or a.data in protected:raise ValueError('Choose dedicated application and data directories, never an OS directory.')
    if a.data.is_relative_to(a.prefix) or a.config.is_relative_to(a.prefix):raise ValueError('Keep mutable data/config outside binaries.')
    if not a.user and os.geteuid()!=0:raise ValueError('Use sudo for systemd installation, or --user with explicit user-owned paths.')
    unit=Path('/etc/systemd/system/sap-lens.service')
    marker='# Managed by SAP Lens deployment installer\n'
    if not a.user:
        if not shutil.which('systemctl') or not Path('/run/systemd/system').is_dir():raise ValueError('A running systemd host is required; use --user for a workstation process.')
        if unit.exists() and (not unit.read_text().startswith(marker) or str(a.prefix/'current') not in unit.read_text()):
            raise ValueError('An administrator-managed service unit exists; review/migrate it explicitly.')
    if a.action=='uninstall':
        if not a.user and unit.exists():
            command('systemctl','disable','--now','sap-lens');unit.unlink();command('systemctl','daemon-reload')
        print('Service registration removed. Application, configuration, sources and data are preserved.');return
    if a.prefix.exists() and any(p.name not in {'releases','current'} for p in a.prefix.iterdir()):raise ValueError('Installation prefix contains unrelated files; migrate explicitly.')
    if a.data.exists() and any(a.data.iterdir()):
        marker=a.data/'deployment.json'
        if not marker.is_file() or json.loads(marker.read_text())!={'version':1,'mode':'server'}:
            raise ValueError('Existing data directory is not an initialized SAP Lens server store.')
    manifest=validate_bundle()
    if not a.user:
        result=subprocess.run(['id','-u','saplens'],capture_output=True,text=True)
        if result.returncode:command('useradd','--system','--home-dir',str(a.data),'--shell','/usr/sbin/nologin','saplens')
        elif result.stdout.strip()=='0':raise ValueError('Refusing a root runtime identity.')
    a.prefix.mkdir(parents=True,exist_ok=True);a.data.mkdir(parents=True,exist_ok=True,mode=0o700)
    new_parent=not a.config.parent.exists()
    new_config=not a.config.exists()
    a.config.parent.mkdir(parents=True,exist_ok=True,mode=0o750)
    if new_config:
        defaults={'SAP_LENS_DEPLOYMENT_MODE':'server','SAP_LENS_HOST':'127.0.0.1','SAP_LENS_PORT':'18743',
                  'SAP_LENS_DATA_DIR':str(a.data),'SAP_LENS_SOURCE_DIR':str(a.data/'sources'),
                  'SAP_LENS_PUBLIC_ORIGIN':'http://127.0.0.1:18743','SAP_LENS_ALLOWED_HOSTS':'127.0.0.1',
                  'SAP_LENS_AUTH':'local','SAP_LENS_LOG_LEVEL':'info'}
        with a.config.open('x') as output:
            os.chmod(a.config,0o640)
            output.write('\n'.join(k+'='+json.dumps(v,ensure_ascii=False) for k,v in defaults.items())+'\n')
    command(sys.executable,BUNDLE/'scripts/run-installed-server.py','--env',a.config,'--check')
    current=a.prefix/'current'
    if current.exists() and not current.is_symlink():raise ValueError('Current installation is not a managed link.')
    release=a.prefix/'releases'/(manifest['identity']['version']+'-'+manifest['identity']['source_sha'][:12])
    if release.exists():raise ValueError('This release directory already exists; do not overwrite an installation.')
    release.parent.mkdir(parents=True,exist_ok=True)
    # Stage an immutable release. Only change the active link after offline install and configuration checks.
    shutil.copytree(BUNDLE,release)
    for path in [release,*release.rglob('*')]:path.chmod(0o755 if path.is_dir() else 0o644)
    command(sys.executable,'-m','venv',release/'.venv')
    python=release/'.venv/bin/python'
    command(python,'-m','pip','install','--no-index','--require-hashes','--find-links',release/'wheelhouse','-r',release/'requirements-runtime.txt')
    command(python,'-m','pip','check')
    command(python,release/'scripts/run-installed-server.py','--env',a.config,'--check')
    if not a.user:
        command('chown','saplens:saplens',a.data)
        if new_config:os.chown(a.config,-1,grp.getgrnam('saplens').gr_gid)
        if new_parent:os.chown(a.config.parent,-1,grp.getgrnam('saplens').gr_gid)
        def quote(path):return str(path).replace('\\','\\\\').replace('"','\\"')
        generated=(BUNDLE/'deploy/linux/sap-lens.service').read_text()
        generated=generated.replace('WorkingDirectory=/opt/sap-lens',f'WorkingDirectory="{quote(current)}"')
        generated=generated.replace('EnvironmentFile=/etc/sap-lens/server.env',f'EnvironmentFile="{quote(a.config)}"')
        generated=generated.replace('ExecStart=/opt/sap-lens/.venv/bin/python /opt/sap-lens/backend/server.py',f'ExecStart="{quote(current)}/.venv/bin/python" "{quote(current)}/backend/server.py"')
        generated=generated.replace('ReadWritePaths=/var/lib/sap-lens',f'ReadWritePaths="{quote(a.data)}"').replace('StateDirectory=sap-lens\n','').replace('StateDirectoryMode=0700\n','')
        generated=marker+generated
        if unit.exists() and unit.read_text()!=generated:raise ValueError('Existing unit differs; preserve it and review configuration explicitly.')
        if not unit.exists():unit.write_text(generated);unit.chmod(0o644)
        if current.exists():command('systemctl','stop','sap-lens')
    temporary=a.prefix/'current.new'
    if temporary.exists() or temporary.is_symlink():raise ValueError('An interrupted link replacement needs administrator review.')
    temporary.symlink_to(release,target_is_directory=True);temporary.replace(current)
    if not a.user:
        command('systemctl','daemon-reload')
        if not a.no_start:command('systemctl','enable','--now','sap-lens')
    print('Installed immutable release. Configuration/data preserved. Current application: '+str(current))
    print('Manual launch: '+' '.join(map(shlex.quote,[str(current/'.venv/bin/python'),str(current/'scripts/run-installed-server.py'),'--env',str(a.config)])))


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,subprocess.CalledProcessError):sys.exit('Installation failed; check prerequisites, integrity, configuration and permissions. Existing active data/configuration are preserved.')
