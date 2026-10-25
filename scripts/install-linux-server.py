"""Linux immutable-release installation and lifecycle. Mutable data is separate."""
import argparse
import grp
import http.client
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

sys.dont_write_bytecode = True
BUNDLE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BUNDLE / 'backend'))
import maintenance


def command(*args): return subprocess.run(list(map(str, args)), check=True)


def load_script(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), BUNDLE / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def validate_bundle():
    packages = load_script('deployment-package')
    manifest = json.loads((BUNDLE / 'package-manifest.json').read_text())
    packages.parse_build_info(manifest['identity'])
    actual = packages.files(BUNDLE); actual.pop('package-manifest.json')
    if actual != manifest['files'] or manifest['platform'] != 'Linux-Native-x64': raise maintenance.MaintenanceError('Bundle integrity mismatch.')
    packages.privacy(actual)
    return manifest


def installed(prefix):
    current = prefix / 'current'
    if not current.exists(): return None
    if not current.is_symlink() or not current.resolve().is_relative_to(prefix / 'releases'):
        raise maintenance.MaintenanceError('Current installation is not a managed release link.')
    value = json.loads((current / 'package-manifest.json').read_text())
    if value.get('platform') != 'Linux-Native-x64': raise maintenance.MaintenanceError('Unrecognized installed application.')
    return value['identity']


def configuration(path, data):
    settings = load_script('run-installed-server').configure(path)
    if settings.data != data: raise maintenance.MaintenanceError('The --data directory differs from administrator configuration; supply its actual value.')
    return settings


def process_owned(pid, prefix, config, ticks=None):
    try:
        arguments = (Path('/proc') / str(pid) / 'cmdline').read_bytes().split(b'\0')
        expected = str(prefix / 'current/scripts/run-installed-server.py').encode()
        actual_ticks = (Path('/proc') / str(pid) / 'stat').read_text().split(') ', 1)[1].split()[19]
        return expected in arguments and str(config).encode() in arguments and (ticks is None or str(ticks) == actual_ticks)
    except (OSError, IndexError): return False


def owns_port(pid, port):
    try:
        sockets = set()
        for path in (Path('/proc') / str(pid) / 'fd').iterdir():
            try:
                name = os.readlink(path)
                if name.startswith('socket:['): sockets.add(name[8:-1])
            except OSError: pass
        for protocol in ('tcp', 'tcp6'):
            for line in (Path('/proc') / str(pid) / 'net' / protocol).read_text().splitlines()[1:]:
                row = line.split()
                if row[3] == '0A' and int(row[1].rsplit(':', 1)[1], 16) == port and row[9] in sockets: return True
    except (OSError, IndexError, ValueError): pass
    return False


def user_pid(prefix, config):
    path = prefix / 'run/process.json'
    if not path.is_file() or path.is_symlink(): return None
    value = json.loads(path.read_text())
    return value['pid'] if process_owned(value['pid'], prefix, config, value.get('ticks')) else None


def ready(settings, pid, timeout=45):
    end = time.monotonic() + timeout
    host = '127.0.0.1' if settings.host == '0.0.0.0' else '::1' if settings.host == '::' else settings.host
    while time.monotonic() < end:
        if owns_port(pid, settings.port):
            connection = http.client.HTTPConnection(host, settings.port, timeout=1)
            try:
                connection.request('GET', '/health/ready', headers={'Host': settings.origin.split('://', 1)[1]})
                response = connection.getresponse()
                if response.status == 200 and json.loads(response.read()).get('status') == 'ready': return
            except (OSError, ValueError): pass
            finally: connection.close()
        time.sleep(.2)
    raise maintenance.MaintenanceError('Installed process did not own the listener and become ready. Stop it and inspect logs before recovery.')


def stop(args):
    if not args.user:
        command('systemctl', 'stop', 'sap-lens')
        return
    pid = user_pid(args.prefix, args.config)
    if pid:
        os.kill(pid, signal.SIGTERM)
        for _ in range(150):
            if not process_owned(pid, args.prefix, args.config): break
            time.sleep(.1)
        else: raise maintenance.MaintenanceError('Server did not stop gracefully; no forced signal or data replacement was attempted.')
    (args.prefix / 'run/process.json').unlink(missing_ok=True)
    if args.data.exists() and (args.data / 'deployment.json').exists():
        with maintenance.stopped(args.data, 'server'): pass  # Detect manually started processes; never kill by name.


def start(args, settings):
    if not args.user:
        command('systemctl', 'start', 'sap-lens')
        pid = int(subprocess.check_output(['systemctl', 'show', '--property=MainPID', '--value', 'sap-lens'], text=True))
        ready(settings, pid)
        return
    if user_pid(args.prefix, args.config):
        ready(settings, user_pid(args.prefix, args.config)); return
    runtime = args.prefix / 'run'; runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    logs = args.data / 'logs'; logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    log = logs / 'server-console.log'
    if log.exists() and log.stat().st_size > 2_000_000:
        for index in range(2, 0, -1):
            previous = log.with_name(log.name + ('' if index == 1 else '.' + str(index - 1)))
            if previous.exists(): previous.replace(log.with_name(log.name + '.' + str(index)))
    with log.open('ab') as output:
        log.chmod(0o600)
        env = os.environ.copy()
        for key in ('SAP_LENS_CONFIG_DIR', 'SAP_LENS_DATA_DIR', 'SAP_LENS_DEPLOYMENT_MODE'): env.pop(key, None)
        process = subprocess.Popen([str(args.prefix / 'current/.venv/bin/python'), str(args.prefix / 'current/scripts/run-installed-server.py'), '--env', str(args.config)], env=env, stdout=output, stderr=output, start_new_session=True)
    try:
        ready(settings, process.pid)
        if process.poll() is not None: raise maintenance.MaintenanceError('The new process exited during startup.')
        ticks = (Path('/proc') / str(process.pid) / 'stat').read_text().split(') ', 1)[1].split()[19]
        path = runtime / 'process.json'; path.write_text(json.dumps(dict(pid=process.pid, ticks=ticks))); path.chmod(0o600)
    except Exception:
        if process.poll() is None: process.terminate(); process.wait(timeout=20)
        raise


def backup_state(args, python, application_version):
    if not args.data.exists() or not any(args.data.iterdir()): return None
    output = args.backup_dir / ('SAP-Lens-' + application_version.replace('+', '_') + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.sap-lens-backup.tar.gz')
    command(python, BUNDLE / 'backend/maintenance.py', 'backup', '--data', args.data, '--config-dir', args.config.parent,
            '--output', output, '--mode', 'server', '--application-version', application_version)
    return output


def managed_prefix(prefix):
    if not prefix.exists(): return
    if any(path.name not in {'current', 'releases', 'run'} for path in prefix.iterdir()): raise maintenance.MaintenanceError('Installation prefix contains unrelated files.')
    runtime = prefix / 'run'
    if runtime.is_symlink() or runtime.exists() and any(path.name != 'process.json' or path.is_symlink() or not path.is_file() for path in runtime.iterdir()):
        raise maintenance.MaintenanceError('Runtime directory contains unrelated files; preserve/review them explicitly.')
    releases = prefix / 'releases'
    if releases.is_symlink(): raise maintenance.MaintenanceError('Release directory may not be a link.')
    if releases.exists():
        for release in releases.iterdir():
            if release.is_symlink() or not release.is_dir(): raise maintenance.MaintenanceError('Unrecognized release path.')
            manifest = json.loads((release / 'package-manifest.json').read_text())
            if manifest.get('platform') != 'Linux-Native-x64': raise maintenance.MaintenanceError('Unrecognized release contents.')
            expected = set(manifest['files']) | {'package-manifest.json'}
            for path in release.rglob('*'):
                name = path.relative_to(release)
                if name.parts[0] == '.venv' or '__pycache__' in name.parts: continue
                if path.is_symlink() or path.is_file() and name.as_posix() not in expected:
                    raise maintenance.MaintenanceError('Installation contains administrator-added files; preserve/review them explicitly.')


def install(args, unit, marker):
    manifest = validate_bundle(); old = installed(args.prefix)
    if args.action == 'upgrade' and old is None: raise maintenance.MaintenanceError('No installation found; use install first.')
    if old: maintenance.ensure_upgrade(old['version'], manifest['identity']['version'])
    total = sum(path.stat().st_size for path in BUNDLE.rglob('*') if path.is_file())
    ancestor = args.prefix.parent
    while not ancestor.exists(): ancestor = ancestor.parent
    if shutil.disk_usage(ancestor).free < total * 4 + 64*1024*1024: raise maintenance.MaintenanceError('Insufficient free space to stage a new immutable release.')
    if not args.user:
        result = subprocess.run(['id', '-u', 'saplens'], capture_output=True, text=True)
        if result.returncode: command('useradd', '--system', '--home-dir', args.data, '--shell', '/usr/sbin/nologin', 'saplens')
        elif result.stdout.strip() == '0': raise maintenance.MaintenanceError('Refusing a root runtime identity.')
    args.prefix.mkdir(parents=True, exist_ok=True); args.data.mkdir(parents=True, exist_ok=True, mode=0o700)
    new_parent = not args.config.parent.exists(); new_config = not args.config.exists()
    args.config.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    if new_config:
        defaults = dict(SAP_LENS_DEPLOYMENT_MODE='server', SAP_LENS_HOST='127.0.0.1', SAP_LENS_PORT='18743',
                        SAP_LENS_DATA_DIR=str(args.data), SAP_LENS_SOURCE_DIR=str(args.data / 'sources'),
                        SAP_LENS_PUBLIC_ORIGIN='http://127.0.0.1:18743', SAP_LENS_ALLOWED_HOSTS='127.0.0.1',
                        SAP_LENS_AUTH='local', SAP_LENS_LOG_LEVEL='info')
        with args.config.open('x') as output:
            os.chmod(args.config, 0o640); output.write('\n'.join(key + '=' + json.dumps(value, ensure_ascii=False) for key, value in defaults.items()) + '\n')
    settings = configuration(args.config, args.data)
    release = args.prefix / 'releases' / (manifest['identity']['version'] + '-' + manifest['identity']['source_sha'][:12])
    same = old is not None and (args.prefix / 'current').resolve() == release
    if release.exists() and not same: raise maintenance.MaintenanceError('A staged release already exists. Inspect it; no files were overwritten.')
    if not same:
        release.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(BUNDLE, release)
        for path in [release, *release.rglob('*')]: path.chmod(0o755 if path.is_dir() else 0o644)
        command(sys.executable, '-m', 'venv', release / '.venv')
        python = release / '.venv/bin/python'
        command(python, '-m', 'pip', 'install', '--no-index', '--require-hashes', '--find-links', release / 'wheelhouse', '-r', release / 'requirements-runtime.txt')
        command(python, '-m', 'pip', 'check')
        command(python, release / 'scripts/run-installed-server.py', '--env', args.config, '--check')
    if not args.user:
        command('chown', 'saplens:saplens', args.data)
        if new_config: os.chown(args.config, -1, grp.getgrnam('saplens').gr_gid)
        if new_parent: os.chown(args.config.parent, -1, grp.getgrnam('saplens').gr_gid)
        def quote(path): return str(path).replace('\\', '\\\\').replace('"', '\\"')
        current = args.prefix / 'current'
        generated = (BUNDLE / 'deploy/linux/sap-lens.service').read_text()
        generated = generated.replace('WorkingDirectory=/opt/sap-lens', f'WorkingDirectory="{quote(current)}"')
        generated = generated.replace('EnvironmentFile=/etc/sap-lens/server.env', f'EnvironmentFile="{quote(args.config)}"')
        generated = generated.replace('ExecStart=/opt/sap-lens/.venv/bin/python /opt/sap-lens/backend/server.py', f'ExecStart="{quote(current)}/.venv/bin/python" "{quote(current)}/backend/server.py"')
        generated = generated.replace('ReadWritePaths=/var/lib/sap-lens', f'ReadWritePaths="{quote(args.data)}"').replace('StateDirectory=sap-lens\n', '').replace('StateDirectoryMode=0700\n', '')
        generated = marker + generated
        if unit.exists() and unit.read_text() != generated: raise maintenance.MaintenanceError('Existing unit differs; preserve and review its configuration explicitly.')
        if not unit.exists(): unit.write_text(generated); unit.chmod(0o644)
    previous = args.prefix / 'current'
    if old and not same:
        stop(args)
        backup_state(args, release / '.venv/bin/python', old['version'])
    if not same:
        temporary = args.prefix / 'current.new'
        if temporary.exists() or temporary.is_symlink(): raise maintenance.MaintenanceError('An interrupted activation needs administrator review.')
        temporary.symlink_to(release, target_is_directory=True); temporary.replace(previous)
    if not args.user:
        command('systemctl', 'daemon-reload')
        if not args.no_start:
            command('systemctl', 'enable', 'sap-lens')
            try: start(args, settings)
            except Exception:
                stop(args)
                raise maintenance.MaintenanceError('Upgrade/startup health failed; service stopped. Previous releases and private backup remain. Restore compatible data before switching binaries back.') from None
    print(json.dumps(dict(installed_version=manifest['identity']['version'], repeated_install=same, data_preserved=True,
                          runtime_verified=not args.user and not args.no_start,
                          next_action='Use start/status for user-mode runtime acceptance.' if args.user else 'Review status and logs.')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'upgrade', 'uninstall', 'start', 'stop', 'restart', 'status', 'backup', 'restore'])
    parser.add_argument('--user', action='store_true', help='Local process without systemd/root')
    parser.add_argument('--prefix', type=Path, default=Path('/opt/sap-lens'))
    parser.add_argument('--data', type=Path, default=Path('/var/lib/sap-lens'))
    parser.add_argument('--config', type=Path, default=Path('/etc/sap-lens/server.env'))
    parser.add_argument('--backup-dir', type=Path); parser.add_argument('--archive', type=Path)
    parser.add_argument('--restore-data', type=Path); parser.add_argument('--restore-config', type=Path)
    parser.add_argument('--confirm-restore', action='store_true'); parser.add_argument('--purge-data', action='store_true')
    parser.add_argument('--confirm-purge', action='store_true'); parser.add_argument('--no-start', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'linux' or platform.machine() != 'x86_64' or sys.version_info[:2] != (3, 12): raise maintenance.MaintenanceError('Linux x86-64 and Python 3.12 are required.')
    libc, version = platform.libc_ver()
    if libc != 'glibc' or tuple(map(int, version.split('.')[:2])) < (2, 35): raise maintenance.MaintenanceError('glibc 2.35+ is required.')
    args.prefix, args.data = maintenance.directory(args.prefix), maintenance.directory(args.data)
    args.config = maintenance.directory(args.config.parent) / args.config.name
    args.backup_dir = maintenance.directory(args.backup_dir or args.data.parent / (args.data.name + '-backups'))
    if args.data.is_relative_to(args.prefix) or args.prefix.is_relative_to(args.data) or args.config.is_relative_to(args.prefix): raise maintenance.MaintenanceError('Keep data/configuration separate from application binaries.')
    for first, second in ((args.config.parent, args.data), (args.config.parent, args.prefix)):
        if first.is_relative_to(second) or second.is_relative_to(first):
            raise maintenance.MaintenanceError('Use separate dedicated application, data and configuration directories.')
    if args.config.is_symlink(): raise maintenance.MaintenanceError('Configuration may not be a link.')
    if not args.user and os.geteuid() != 0: raise maintenance.MaintenanceError('Use sudo for systemd management or --user with dedicated user-owned paths.')
    if args.purge_data and (args.action != 'uninstall' or not args.confirm_purge): raise maintenance.MaintenanceError('Purge requires uninstall --purge-data --confirm-purge.')
    managed_prefix(args.prefix)
    unit = Path('/etc/systemd/system/sap-lens.service'); marker = '# Managed by SAP Lens deployment installer\n'
    if not args.user:
        if not shutil.which('systemctl') or not Path('/run/systemd/system').is_dir(): raise maintenance.MaintenanceError('A running systemd host is required; use --user for a workstation process.')
        if unit.exists() and (not unit.read_text().startswith(marker) or str(args.prefix / 'current') not in unit.read_text()): raise maintenance.MaintenanceError('An administrator-managed unit exists; no changes were made.')
    if args.action in ('install', 'upgrade'):
        if args.data.exists() and any(args.data.iterdir()): maintenance.owned(args.data, 'server')
        install(args, unit, marker); return
    current = installed(args.prefix)
    if current is None: raise maintenance.MaintenanceError('No recognized installation found.')
    settings = configuration(args.config, args.data)
    if args.action == 'status':
        pid = user_pid(args.prefix, args.config) if args.user else int(subprocess.check_output(['systemctl', 'show', '--property=MainPID', '--value', 'sap-lens'], text=True))
        healthy = False
        if pid:
            try: ready(settings, pid, timeout=1); healthy = True
            except ValueError: pass
        print(json.dumps(dict(version=current['version'], prefix=str(args.prefix), data=str(args.data), config=str(args.config),
                              pid=pid, ready=healthy, host=settings.host, port=settings.port, logs='journald' if not args.user else str(args.data / 'logs')))); return
    if args.action in ('stop', 'restart', 'backup', 'restore', 'uninstall'): stop(args)
    if args.action in ('start', 'restart'): start(args, settings)
    elif args.action == 'backup': backup_state(args, args.prefix / 'current/.venv/bin/python', current['version'])
    elif args.action == 'restore':
        if not args.archive or not args.restore_data or not args.confirm_restore: raise maintenance.MaintenanceError('Restore requires --archive --restore-data --confirm-restore, and empty target directories.')
        values = [args.prefix / 'current/.venv/bin/python', BUNDLE / 'backend/maintenance.py', 'restore', '--archive', args.archive,
                  '--data', args.restore_data, '--mode', 'server', '--target-version', current['version'], '--confirm-restore']
        if args.restore_config: values += ['--config-destination', args.restore_config]
        command(*values)
        print('Files restored to empty destinations; existing stores/configuration preserved. Review paths/permissions and start/status before declaring recovery complete.')
    elif args.action == 'uninstall':
        if not args.user and unit.exists():
            command('systemctl', 'disable', 'sap-lens'); unit.unlink(); command('systemctl', 'daemon-reload')
        if args.purge_data:
            maintenance.owned(args.data, 'server')
            with maintenance.stopped(args.data, 'server'): shutil.rmtree(args.data)
            args.config.unlink()
        shutil.rmtree(args.prefix)
        print('Application removed. Data/configuration ' + ('purged by explicit confirmation; external sources/secrets/backups retained.' if args.purge_data else 'preserved.'))


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, subprocess.CalledProcessError, RuntimeError) as error:
        detail = str(error) if isinstance(error, maintenance.MaintenanceError) else 'Inspect prerequisites, integrity, configuration and logs; private exception details omitted.'
        sys.exit('Lifecycle operation failed (' + type(error).__name__ + '): ' + detail + ' Existing backups are retained; do not assume binary-only rollback restores data.')
