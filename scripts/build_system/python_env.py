"""Pip bootstrap and locked-dependency checks shared by every build entry point. Standard library only.

Why this exists: `python -m venv` seeds pip through `ensurepip`, which installs the pip that ships with the interpreter (24.0 for
Python 3.12). That pip validates TLS only against its bundled certifi list, so on a Windows machine whose proxy or inspection CA lives in
the system store it fails with CERTIFICATE_VERIFY_FAILED, while a newer pip (24.2 and later) uses the operating system trust store by
default. The fix is to move pip to the project's pinned version once, over a verified connection, never to disable verification.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

#: First pip release that verifies TLS against the system trust store by default (Python 3.10 and later).
MINIMUM_PIP = (24, 2)
TLS_FAILURE = re.compile(r'CERTIFICATE_VERIFY_FAILED|SSLCertVerificationError|SSLError|certificate verify failed|unable to get local issuer certificate', re.I)


def parse_pip_version(text):
    """`pip 24.0 from ... (python 3.12)` -> (24, 0); None when pip is missing or the text is not pip's."""
    match = re.match(r'\s*pip (\d+)\.(\d+)', text or '')
    return (int(match[1]), int(match[2])) if match else None


def pip_version(python, timeout=30):
    try:
        done = subprocess.run([str(python), '-m', 'pip', '--version'], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_pip_version(done.stdout) if done.returncode == 0 else None


def pinned_pip(root):
    """The exact pip release the project pins (`pip==X` in requirements-build.txt), or None."""
    for line in (Path(root) / 'backend/requirements-build.txt').read_text(encoding='utf-8').splitlines():
        match = re.fullmatch(r'pip==(\d+(?:\.\d+)+)', line.strip())
        if match:
            return match[1]
    return None


def parse_pins(root, files):
    """Exact `name==version` pins from requirement files, following `-r` includes. Unpinned or marker lines are returned as None so callers install."""
    pins, seen = {}, set()

    def read(path):
        path = Path(path).resolve()
        if path in seen:
            return True
        seen.add(path)
        for raw in path.read_text(encoding='utf-8').splitlines():
            line = raw.split('#', 1)[0].strip()
            if not line:
                continue
            include = re.fullmatch(r'-r\s+(\S+)', line)
            if include:
                if not read(path.parent / include[1]):
                    return False
                continue
            match = re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9.!+_-]+)', line)
            if not match:
                return False
            pins[re.sub(r'[-_.]+', '-', match[1]).lower()] = match[2]
        return True

    for file in files:
        if not read(Path(root) / file):
            return None
    return pins


def installed_packages(python, timeout=60):
    try:
        done = subprocess.run([str(python), '-m', 'pip', 'list', '--format=freeze', '--disable-pip-version-check'], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode:
        return None
    found = {}
    for line in done.stdout.splitlines():
        match = re.fullmatch(r'([^=\s]+)==(\S+)', line.strip())
        if match:
            found[re.sub(r'[-_.]+', '-', match[1]).lower()] = match[2]
    return found


def dependencies_satisfied(python, root, files):
    """True only when every locked pin is already installed at exactly that version; any doubt means install (which is idempotent)."""
    pins = parse_pins(root, files)
    if not pins:
        return False
    found = installed_packages(python)
    return bool(found) and all(found.get(name) == version for name, version in pins.items())


def ensure_pip(python, root, run, say=print):
    """Make pip usable and at least MINIMUM_PIP. `run(label, command)` returns (exit_code, output) and never raises for a failing command.

    Returns the action taken: 'ok', 'seeded' or 'upgraded'. Raises RuntimeError with actionable guidance when recovery is impossible.
    """
    action = 'ok'
    version = pip_version(python)
    if version is None:
        code, output = run('Seed pip in the project environment', [python, '-m', 'ensurepip', '--upgrade'])
        version = pip_version(python)
        if code or version is None:
            raise RuntimeError('pip is missing from the project Python environment and could not be seeded. The environment was left untouched; remove or repair only that environment and retry.')
        action = 'seeded'
    if version >= MINIMUM_PIP:
        return action
    target = pinned_pip(root)
    if not target:
        raise RuntimeError('backend/requirements-build.txt has no pip pin to upgrade to.')
    base = [python, '-m', 'pip', 'install', '--disable-pip-version-check', f'pip=={target}']
    code, output = run(f'Upgrade pip {version[0]}.{version[1]} to the pinned pip {target}', base)
    if code and TLS_FAILURE.search(output or ''):
        # Only this bootstrap step may opt in to the system trust store on an old pip; certificate verification stays on, no host is exempted
        # and no certificate is added to the machine. Once pip is current the system store is used by default and the flag is not needed.
        say('The old pip could not verify the package index with its bundled certificates; retrying once with the operating system trust store.')
        code, output = run('Upgrade pip using the system trust store', [python, '-m', 'pip', 'install', '--disable-pip-version-check', '--use-feature=truststore', f'pip=={target}'])
    if code:
        if TLS_FAILURE.search(output or ''):
            raise RuntimeError('pip could not verify the package index certificate even with the system trust store. Ask IT for the corporate CA, trust it in the operating system store (or point pip at it with `pip config set global.cert <file>`), and retry. SAP Lens never disables certificate verification or uses --trusted-host.')
        raise RuntimeError(f'pip could not be upgraded to {target} (exit {code}). Check network access to the package index or proxy settings, then retry.')
    upgraded = pip_version(python)
    if upgraded is None or upgraded < MINIMUM_PIP:
        raise RuntimeError(f'pip is still older than {MINIMUM_PIP[0]}.{MINIMUM_PIP[1]} after the upgrade. Repair the project environment and retry.')
    return 'upgraded'


# --- Interpreter discovery and project environment inspection (shared by the build engine, doctor and the test runners) -------------------
REQUIRED = (3, 12)
# No double quotes: Windows PowerShell 5.1 strips them from native arguments. `venv`/`ensurepip` are probed because Debian ships them separately.
# One line: a newline inside a .cmd/.bat argument would end the command line under cmd.exe.
PROBE = ('import sys,json,importlib.util as u;'
         'print(json.dumps([sys.executable,list(sys.version_info[:3]),64 if sys.maxsize>2**32 else 32,int(bool(u.find_spec(\'venv\') and u.find_spec(\'ensurepip\')))]))')


def probe_python(path, prefix=(), timeout=20):
    """Ask an interpreter who it is. Returns dict(path, version, bits, venv_module) or None when it cannot run; never raises."""
    try:
        done = subprocess.run([str(path), *prefix, '-c', PROBE], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        if done.returncode:
            return None
        exe, version, bits, venv_module = json.loads(done.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None
    return dict(path=exe, version='.'.join(map(str, version)), major_minor=tuple(version[:2]), bits=bits, venv_module=bool(venv_module))


def acceptable(info):
    return bool(info) and info['major_minor'] == REQUIRED and info['bits'] == 64


def candidates(environ=None):
    """(source, command, prefix) in a fixed order. The bare `python` on PATH is deliberately last and only ever accepted if it probes as 3.12 x64."""
    environ = os.environ if environ is None else environ
    found = []
    if environ.get('SAP_LENS_PYTHON'):
        found.append(('SAP_LENS_PYTHON', environ['SAP_LENS_PYTHON'], ()))
    found.append(('current interpreter', sys.executable, ()))
    launcher = shutil.which('py')
    if launcher:
        found.append(('Python launcher (py -3.12)', launcher, ('-3.12',)))
        try:
            rows = subprocess.run([launcher, '-0p'], capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL).stdout.splitlines()
        except (OSError, subprocess.SubprocessError):
            rows = []
        for row in rows:
            match = re.search(r'([A-Za-z]:\\.*python[w]?\.exe)\s*$', row)
            if match and '3.12' in row:
                found.append(('registered installation', match[1], ()))
    for name in ('python3.12', 'python3', 'python'):
        path = shutil.which(name)
        if path:
            found.append((f'PATH ({name})', path, ()))
    return found


def find_python(environ=None):
    """First interpreter that is exactly Python 3.12 x64 with venv support, plus every rejected candidate for the report."""
    rejected, seen = [], set()
    for source, command, prefix in candidates(environ):
        key = (os.path.normcase(os.path.abspath(command)) if os.path.exists(command) else command, prefix)
        if key in seen:
            continue
        seen.add(key)
        info = probe_python(command, prefix)
        if acceptable(info) and info['venv_module']:
            return dict(info, source=source), rejected
        reason = 'could not be started' if not info else f"Python {info['version']} {info['bits']}-bit" + ('' if info['venv_module'] or not acceptable(info) else ' without venv/ensurepip')
        rejected.append(dict(source=source, path=str(command), reason=reason))
    return None, rejected


def venv_python(directory):
    return Path(directory) / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def inspect_venv(directory):
    """(state, detail, info). state: missing | ready | incompatible | broken. Read-only: the directory is never touched."""
    directory = Path(directory)
    if not directory.exists() and not directory.is_symlink():
        return 'missing', 'not created yet', None
    if directory.is_symlink():
        return 'incompatible', 'is a link; the project environment must be a real directory', None
    python = venv_python(directory)
    if not (directory / 'pyvenv.cfg').is_file() or not python.is_file():
        return 'broken', 'is incomplete (pyvenv.cfg or the interpreter is missing)', None
    info = probe_python(python)
    if not info:
        return 'broken', 'its interpreter does not start (the base Python was probably removed or moved)', None
    if info['major_minor'] != REQUIRED:
        return 'incompatible', f"uses Python {info['version']}, not 3.12", info
    if info['bits'] != 64:
        return 'incompatible', 'uses 32-bit Python; 64-bit is required', info
    return 'ready', f"Python {info['version']}", info


def test_interpreter(root):
    """The interpreter for tests and validation: the current one when it already is 3.12 x64, otherwise the ready project .venv.
    Never silently falls back to another version; raises SystemExit(3) with the command that fixes it."""
    if sys.version_info[:2] == REQUIRED and sys.maxsize > 2**32:
        return sys.executable
    state, detail, info = inspect_venv(Path(root) / '.venv')
    if state == 'ready':
        return str(venv_python(Path(root) / '.venv'))
    raise SystemExit(f"Python 3.12 x64 is required but this command runs under Python {sys.version.split()[0]} and the project .venv is {state} ({detail}).\n"
                     "Prepare it once with:  .\\build.ps1 -Mode prerequisites   (Linux: python3.12 scripts/build.py prerequisites)")
