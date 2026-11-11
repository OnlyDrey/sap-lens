"""Prerequisites report, repair and target-specific preflight. Check mode is strictly read-only; nothing here installs a system tool."""
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import time
from . import prerequisites as deps, python_env
from .runner import ROOT, BuildError

READY, WARNING, MISSING, INCOMPATIBLE, REPAIR = 'Ready', 'Warning', 'Missing', 'Incompatible', 'Repair required'
PACKAGING_TARGETS = {'desktop', 'installer', 'server', 'service', 'all'}
PY_HINT = 'Install Python 3.12 x64 (python.org or `winget install Python.Python.3.12`); other versions may stay installed and stay the default.'


def item(name, status, detail='', action='', required=True):
    return dict(name=name, status=status, detail=detail, action=action, required=required)


def needs_packaging(args):
    return args.mode in ('build', 'package') or (args.mode == 'prerequisites' and getattr(args, 'target_given', False))


def requirements(args):
    """Which tools matter for this request: (windows_service_compiler, docker, powershell, packaging_env)."""
    windows = args.platform == 'windows' and platform.system() == 'Windows'
    packaging = needs_packaging(args)
    return dict(csc=windows and packaging and args.target in ('service', 'all'),
                docker=args.platform in ('docker', 'all') and packaging,
                powershell=windows and packaging,
                packaging_env=packaging and args.target in PACKAGING_TARGETS,
                git=args.mode != 'clean', node=args.mode not in ('clean', 'release'))


def needs_managed_tools(args):
    # Skip-setup packaging reuses a source-validation receipt and does not run Repository lint.
    return needs_packaging(args) and not getattr(args, 'skip_setup', False)


def tool_item(name, required):
    probe = deps.probe_tool(name)
    if probe.status == 'missing':
        return item(name, MISSING if required else WARNING, 'not found on PATH', f'Install {name} through your approved tools and reopen the terminal.', required)
    if probe.status != 'ok':
        return item(name, REPAIR, f'{probe.status}: {(probe.detail or "")[:120]}', f'Run {probe.path} {" ".join(deps.PROBES[name])} in this terminal and repair that installation.', required)
    try:
        deps.inspect_tool(name)
    except BuildError as error:
        return item(name, INCOMPATIBLE, f'{probe.value} ({str(error).splitlines()[0][:140]})', 'Install Node.js 24 LTS (CI baseline; 25 is accepted) and npm 10 or 11.', required)
    if name == 'node' and int(probe.value.split('.')[0]) % 2:
        return item(name, WARNING, f'{probe.value} (Current, non-LTS; Node.js 24 LTS is the CI baseline)', 'Use Node.js 24 LTS for reproducible results.', required)
    return item(name, READY, probe.value, required=required)


def collect(args, root=ROOT):
    """Read-only inspection. Never creates, repairs or deletes anything and never touches the network."""
    need = requirements(args)
    items = [item('Operating system', READY, f'{platform.system()} {platform.release()} {platform.machine()}', required=False)]
    found, rejected = python_env.find_python()
    if found:
        items.append(item('Python 3.12 x64', READY, f"{found['path']} ({found['version']}, via {found['source']})"))
    else:
        detail = '; '.join(f"{row['source']}: {row['reason']}" for row in rejected) or 'no interpreter found'
        items.append(item('Python 3.12 x64', MISSING, detail, PY_HINT))
    environments = [('Project .venv', root / '.venv', 'backend/requirements-dev.txt', ['backend/requirements-dev.txt'])]
    if need['packaging_env']:
        environments.append(('Packaging environment', root / 'backend/build/python-env', 'backend/requirements-build.txt', ['backend/requirements-dev.txt', 'backend/requirements-build.txt']))
    for label, directory, _, files in environments:
        state, detail, info = python_env.inspect_venv(directory)
        rel = directory.relative_to(root).as_posix()
        if state == 'missing':
            items.append(item(label, MISSING, f'{rel} {detail}', 'Run the prerequisites setup; it creates the environment with Python 3.12.', label == 'Project .venv'))
            continue
        if state != 'ready':
            items.append(item(label, REPAIR if state == 'broken' else INCOMPATIBLE, f'{rel} {detail}', 'Run the prerequisites setup with --repair (the old directory is renamed, never deleted).'))
            continue
        items.append(item(label, READY, f'{rel} {detail}'))
        ok = python_env.dependencies_satisfied(python_env.venv_python(directory), root, files)
        items.append(item(f'{label} dependencies', READY if ok else REPAIR, 'all locked pins installed' if ok else 'a locked package is missing or differs from ' + ', '.join(files),
                          '' if ok else 'Run the prerequisites setup; it installs exactly the pinned versions.'))
    if need['node']:
        items += [tool_item('node', True), tool_item('npm', True)]
        current = deps.frontend_current(root)
        items.append(item('Frontend dependencies', READY if current else MISSING, 'node_modules matches package-lock.json' if current else 'node_modules is missing or older than package-lock.json',
                          '' if current else 'Run the prerequisites setup; it runs `npm ci`.', False))
    if need['git']:
        items.append(tool_item('git', True))
    if need['powershell']:
        shell = shutil.which('powershell') or shutil.which('pwsh')
        items.append(item('PowerShell', READY if shell else MISSING, shell or 'neither Windows PowerShell 5.1 nor PowerShell 7 found', 'Windows PowerShell 5.1 ships with Windows.'))
    if need['csc']:
        csc = os.path.join(os.environ.get('WINDIR', ''), 'Microsoft.NET/Framework64/v4.0.30319/csc.exe')
        items.append(item('.NET Framework csc.exe (service manager)', READY if os.path.isfile(csc) else MISSING, csc, 'Enable the .NET Framework 4.x developer components of Windows.'))
    if need['docker']:
        items.append(tool_item('docker', True))
    if platform.system() == 'Windows' and not need['powershell']:
        items.append(item('PowerShell', READY if (shutil.which('powershell') or shutil.which('pwsh')) else WARNING, 'only Windows packaging needs it', required=False))
    if needs_managed_tools(args):
        from . import managed_tools
        windows = platform.system() == 'Windows'
        package = 'windows_amd64.zip' if windows else 'linux_amd64.tar.gz'
        expected = managed_tools.ACTIONLINT_WINDOWS_SHA256 if windows else managed_tools.ACTIONLINT_SHA256
        location = managed_tools.cache_directory(root)
        archive = location / f'actionlint-{managed_tools.ACTIONLINT_VERSION}-{package}'
        explicit = os.environ.get('SAP_LENS_ACTIONLINT_ARCHIVE')
        try:
            available = managed_tools.verified(Path(explicit) if explicit else archive, expected) is not None
        except (OSError, managed_tools.ToolUnavailable):
            available = False
        items.append(item('actionlint', READY if available else MISSING,
                          'verified archive cached; executable/version checked by build preflight' if available else 'no verified pinned archive cached',
                          'Run prerequisites setup for this target; configure an approved mirror/local archive for restricted networks.'))
        if args.platform == 'windows' and args.target == 'installer':
            explicit = os.environ.get('SAP_LENS_INNO_ARCHIVE')
            artifact = Path(explicit) if explicit else location / f'innosetup-{managed_tools.INNO_VERSION}-x64.exe'
            try:
                available = managed_tools.verified(artifact, managed_tools.INNO_SHA256) is not None
            except (OSError, managed_tools.ToolUnavailable):
                available = False
            items.append(item('Inno Setup bootstrap', READY if available else MISSING,
                              'pinned installer cached; native compiler provisioning remains separate' if available else 'no verified pinned installer cached',
                              'Run prerequisites setup for the installer target or configure an approved Inno artifact/mirror.'))
    items.append(item('Security audit', READY, 'not part of prerequisites; run `npm --prefix frontend audit --omit=dev` separately (needs network)', required=False))
    return items


def exit_code(items):
    """0 usable, 3 a required component is missing, incompatible or needs repair (matches the engine's prerequisite code)."""
    return 3 if any(row['required'] and row['status'] in (MISSING, INCOMPATIBLE, REPAIR) for row in items) else 0


def render(items, as_json=False):
    code = exit_code(items)
    if as_json:
        return json.dumps(dict(ok=code == 0, exit_code=code, items=items), indent=2)
    lines = ['SAP Lens prerequisites', '']
    for row in items:
        lines.append(f"  {row['status']:<15} {row['name']}: {row['detail']}")
        if row['action'] and row['status'] != READY:
            lines.append(f"  {'':<15} -> {row['action']}")
    lines += ['', 'Result: ' + ('ready' if code == 0 else 'action required (exit code 3)')]
    return '\n'.join(lines)


def quarantine(directory):
    """Repair never deletes: the unusable environment is renamed next to itself so nothing is lost and the user can inspect it."""
    target = directory.with_name(f"{directory.name}.broken-{time.strftime('%Y%m%d-%H%M%S')}")
    directory.rename(target)
    return target


def run_prerequisites(args, runner, root=ROOT):
    """prerequisites mode: check (read-only), setup (default) or repair. Returns the process exit code."""
    as_json = getattr(args, 'json', False)
    if args.check_only:
        items = collect(args, root)
        print(render(items, as_json))
        return exit_code(items)
    found, rejected = python_env.find_python()
    if not found:
        print(render(collect(args, root), as_json), file=sys.stderr)
        return 3
    packaging = needs_packaging(args) and args.target in PACKAGING_TARGETS
    for directory in [root / '.venv'] + ([root / 'backend/build/python-env'] if packaging else []):
        state, detail, _ = python_env.inspect_venv(directory)
        if state in ('broken', 'incompatible') and directory.is_symlink():
            raise BuildError(f'{directory} is a link; remove the link yourself.', 3)
        if state in ('broken', 'incompatible'):
            if not args.repair:
                raise BuildError(f'{directory.relative_to(root).as_posix()} {detail}. It was left untouched. Rerun with --repair to rename it aside and recreate it with Python 3.12.', 3)
            print(f'Repair: renamed {directory.name} to {quarantine(directory).name}')
    if needs_managed_tools(args):
        deps.resolve_managed_tools(root, installer=args.platform == 'windows' and args.target == 'installer')
    deps.prepare_environment(root, runner, packaging=False, frontend=True, creator=found['path'])
    if packaging:
        deps.prepare_environment(root, runner, packaging=True, frontend=False, creator=found['path'])
    items = collect(args, root)
    print(render(items, as_json))
    return exit_code(items)


def preflight(args):
    """Fail before expensive work when a required tool for exactly this platform/target is missing. Read-only."""
    problems = [row for row in collect(args) if row['required'] and row['status'] in (MISSING, INCOMPATIBLE) and row['name'] not in ('Project .venv', 'Packaging environment', 'actionlint', 'Inno Setup bootstrap')
                and not row['name'].endswith('dependencies') and row['name'] != 'Frontend dependencies']
    if problems:
        raise BuildError('Prerequisite preflight failed before any build step ran:\n' + '\n'.join(f"  - {row['name']}: {row['detail']}\n    {row['action']}" for row in problems), 3)
