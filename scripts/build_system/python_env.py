"""Pip bootstrap and locked-dependency checks shared by every build entry point. Standard library only.

Why this exists: `python -m venv` seeds pip through `ensurepip`, which installs the pip that ships with the interpreter (24.0 for
Python 3.12). That pip validates TLS only against its bundled certifi list, so on a Windows machine whose proxy or inspection CA lives in
the system store it fails with CERTIFICATE_VERIFY_FAILED, while a newer pip (24.2 and later) uses the operating system trust store by
default. The fix is to move pip to the project's pinned version once, over a verified connection, never to disable verification.
"""
import re
import subprocess
from pathlib import Path

#: First pip release that verifies TLS against the system trust store by default (Python 3.10 and later).
MINIMUM_PIP = (24, 2)
TLS_FAILURE = re.compile(r'CERTIFICATE_VERIFY_FAILED|SSLError|certificate verify failed', re.I)


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
