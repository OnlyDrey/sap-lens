"""Pinned project-local tools: verified archives, bounded acquisition and atomic publication.

System runtimes remain the responsibility of prerequisites/python_env. No system
installation, TLS override, arbitrary mirror or unverified executable fallback.
"""
from contextlib import contextmanager
import hashlib
import http.client
import io
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import ssl
import stat
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
ACTIONLINT_VERSION = '1.7.12'
ACTIONLINT_SHA256 = '8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8'
ACTIONLINT_WINDOWS_SHA256 = '6e7241b51e6817ea6a047693d8e6fed13b31819c9a0dd6c5a726e1592d22f6e9'
INNO_VERSION = '7.1.0'
INNO_URL = 'https://github.com/jrsoftware/issrc/releases/download/is-7_1_0/innosetup-7.1.0-x64.exe'
INNO_SHA256 = '0362a383ed217d4c4239b5933866dd96d3eb2102737da92f80f6057a4b40df2f'
MAX_BYTES = 32 * 1024 * 1024


class ToolUnavailable(RuntimeError):
    """A prerequisite was not verified, never a successful validation result."""


class SecureRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != 'https':
            raise ToolUnavailable('HTTPS download redirected to an insecure scheme; refused.')
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def open_url(request):
    # Default ProxyHandler and HTTPSHandler retain standard proxy/CA configuration.
    return urllib.request.build_opener(SecureRedirect()).open(request, timeout=30)


def cache_directory(root=ROOT):
    return Path(os.environ.get('SAP_LENS_TOOL_CACHE') or root / '.build-tools')


def verified(path, expected):
    if path.is_symlink():
        raise ToolUnavailable('Tool archive must not be linked.')
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        return None
    data = path.read_bytes()
    return data if hashlib.sha256(data).hexdigest() == expected else None


def atomic_write(path, data, executable=False):
    if path.is_symlink():
        raise ToolUnavailable('Tool destination must not be linked.')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.tool-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if executable:
            os.chmod(temporary, 0o700)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def cache_lock(directory):
    """Kernel-owned cross-process lock; never remove a lock inode another process may hold."""
    if directory.is_symlink():
        raise ToolUnavailable('Tool cache directory must not be linked.')
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / '.acquisition.lock'
    if path.is_symlink():
        raise ToolUnavailable('Tool cache lock must not be linked.')
    with path.open('a+b') as stream:
        stream.seek(0, 2)
        if not stream.tell():
            stream.write(b'0'); stream.flush()
        deadline = time.monotonic() + 30
        while True:
            try:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ToolUnavailable('Tool cache is busy; acquisition lock timed out.') from None
                time.sleep(0.05)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_UN)


def safe_url(url):
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ''
    if parts.port:
        host += ':' + str(parts.port)
    # Internal repository paths may themselves carry credentials. Keep only the asset name.
    path = parts.path if parts.hostname == 'github.com' else '/' + parts.path.rsplit('/', 1)[-1]
    return urllib.parse.urlunsplit((parts.scheme, host, path, '', ''))


def acquire_archive(package, expected, url, directory, report=print, *, tool='actionlint', version=ACTIONLINT_VERSION, env_prefix='SAP_LENS_ACTIONLINT', artifact_name=None):
    """Explicit artifact > verified persistent/run cache > configured HTTPS mirror > upstream."""
    explicit = os.environ.get(env_prefix + '_ARCHIVE')
    if explicit:
        data = verified(Path(explicit), expected)
        if data is None:
            raise ToolUnavailable(f'{env_prefix}_ARCHIVE is missing or SHA-256 does not match the pinned artifact.')
        report(f'{tool} {version} OK (local archive SHA-256 verified)')
        return data
    name = artifact_name or f'{tool}-{version}-{package}'
    persistent = os.environ.get('SAP_LENS_TOOL_CACHE')
    caches = ([Path(persistent)] if persistent else []) + [Path(directory), ROOT / 'backend/build']
    for cache in caches:
        if cache.is_symlink():
            raise ToolUnavailable('Tool cache directory must not be linked.')
        data = verified(cache / name, expected)
        if data is not None:
            if cache != caches[0]:
                atomic_write(caches[0] / name, data)
            report(f'{tool} {version} CACHED (archive SHA-256 verified)')
            return data
    mirror = os.environ.get(env_prefix + '_MIRROR')
    sources = ([mirror.rstrip('/') + '/' + (artifact_name or f'{tool}_{version}_{package}')] if mirror else []) + [url]
    failures = []
    if os.environ.get('SAP_LENS_TOOLS_OFFLINE') == '1':
        failures.append('offline: no verified cache')
    else:
        for source in sources:
            parsed = urllib.parse.urlsplit(source)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ToolUnavailable('Tool source must be HTTPS without embedded credentials, query or fragment; use an approved proxy or local artifact.')
            for attempt in range(3):
                try:
                    request = urllib.request.Request(source, headers={'User-Agent': 'sap-lens-build/1', 'Accept': 'application/octet-stream'})
                    with open_url(request) as response:
                        data = response.read(MAX_BYTES + 1)
                    if len(data) > MAX_BYTES or hashlib.sha256(data).hexdigest() != expected:
                        raise ToolUnavailable(f'{tool} checksum mismatch for {safe_url(source)}; artifact discarded.')
                except urllib.error.HTTPError as error:
                    category = f'HTTP {error.code}'
                    transient = error.code in {408, 429, 500, 502, 503, 504}
                except (urllib.error.URLError, OSError, socket.timeout, http.client.HTTPException) as error:
                    reason = getattr(error, 'reason', error)
                    category = ('TLS verification failure' if isinstance(reason, ssl.SSLError) else
                                'proxy failure' if 'proxy' in str(reason).lower() else type(reason).__name__)
                    transient = not isinstance(reason, ssl.SSLError)
                else:
                    try:
                        atomic_write(caches[0] / name, data)
                    except OSError as error:
                        raise ToolUnavailable(f'{tool} verified download could not be cached ({type(error).__name__}); check cache permissions/free space.') from None
                    report(f'{tool} {version} DOWNLOADED (archive SHA-256 verified)')
                    return data
                failures.append(f'{safe_url(source)}: {category}')
                if not transient or attempt == 2:
                    break
                time.sleep(0.25 * 2 ** attempt)
    raise ToolUnavailable(f'Could not download {tool} {version}. Sources attempted: {"; ".join(failures)}. '
                          f'Cache searched: {", ".join(map(str, caches))}; no verified artifact; checksum required: {expected}. '
                          f'Mirror configured: {bool(mirror)}. Recovery: configure {env_prefix}_MIRROR or {env_prefix}_ARCHIVE; '
                          'HTTPS_PROXY/NO_PROXY and approved CA trust are supported; TLS verification is never disabled.')


def resolve_actionlint(directory=None, *, expected=None, report=print):
    system = platform.system()
    if system not in {'Windows', 'Linux'} or platform.machine().lower() not in {'amd64', 'x86_64'}:
        raise ToolUnavailable('Pinned actionlint requires Windows or Linux x64.')
    windows = system == 'Windows'
    package = 'windows_amd64.zip' if windows else 'linux_amd64.tar.gz'
    expected = expected or (ACTIONLINT_WINDOWS_SHA256 if windows else ACTIONLINT_SHA256)
    directory = Path(directory) if directory is not None else cache_directory()
    url = f'https://github.com/rhysd/actionlint/releases/download/v{ACTIONLINT_VERSION}/actionlint_{ACTIONLINT_VERSION}_{package}'
    with cache_lock(directory):
        data = acquire_archive(package, expected, url, directory, report)
        try:
            if windows:
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    entries = [entry for entry in archive.infolist() if entry.filename == 'actionlint.exe']
                    if (len(entries) != 1 or entries[0].file_size > MAX_BYTES or entries[0].is_dir()
                            or stat.S_ISLNK(entries[0].external_attr >> 16)):
                        raise ToolUnavailable('Archive executable member is invalid.')
                    executable = archive.read(entries[0])
            else:
                with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
                    entries = [entry for entry in archive.getmembers() if entry.name == 'actionlint']
                    if len(entries) != 1 or not entries[0].isfile() or entries[0].size > MAX_BYTES:
                        raise ToolUnavailable('Archive executable member is invalid.')
                    executable = archive.extractfile(entries[0]).read()
        except (ValueError, KeyError, zipfile.BadZipFile, tarfile.TarError) as error:
            raise ToolUnavailable(f'actionlint archive is invalid ({type(error).__name__}); nothing executed.') from None
        tool = directory / (f'actionlint-{ACTIONLINT_VERSION}' + ('.exe' if windows else ''))
        if not executable:
            raise ToolUnavailable('Archive executable is empty; nothing executed.')
        binary_hash = hashlib.sha256(executable).hexdigest()
        # PATH is approved only when its bytes match the executable from the pinned archive.
        installed = shutil.which('actionlint')
        if installed and not Path(installed).is_symlink() and verified(Path(installed), binary_hash) is not None:
            tool = Path(installed)
        elif verified(tool, binary_hash) is None:
            atomic_write(tool, executable, executable=True)
        try:
            done = subprocess.run([str(tool), '-version'], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError) as error:
            raise ToolUnavailable(f'actionlint version probe failed ({type(error).__name__}); verify host policy/permissions.') from None
        if done.returncode or not re.match(r'^(?:actionlint[: ]+)?v?' + re.escape(ACTIONLINT_VERSION) + r'(?:\s|$)', done.stdout.strip()):
            raise ToolUnavailable(f'actionlint version mismatch; required {ACTIONLINT_VERSION}; mandatory validation blocked.')
        report(f'actionlint {ACTIONLINT_VERSION} OK (executable SHA-256 and version verified)')
        return tool



def acquire_inno(directory=None, report=print):
    """Only acquire the existing pinned per-user installer; provisioning stays in the Windows helper."""
    directory = Path(directory) if directory is not None else cache_directory()
    with cache_lock(directory):
        return acquire_archive('windows_x64.exe', INNO_SHA256, INNO_URL, directory, report,
                               tool='Inno Setup', version=INNO_VERSION, env_prefix='SAP_LENS_INNO',
                               artifact_name=f'innosetup-{INNO_VERSION}-x64.exe')
