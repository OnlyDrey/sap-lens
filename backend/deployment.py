"""Hosting policy only; desktop defaults and SAP processing remain independent."""
from collections import OrderedDict
from dataclasses import dataclass
import base64
import hmac
import ipaddress
import math
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit


def server_mode():
    return os.environ.get('SAP_LENS_DEPLOYMENT_MODE', 'desktop') == 'server'


def default_server_data():
    if os.name == 'nt': return Path(os.environ.get('PROGRAMDATA', 'C:/ProgramData')) / 'SAP Lens Server'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share')) / 'sap-lens-server'


@dataclass(frozen=True)
class ServerSettings:
    host: str
    port: int
    data: Path
    sources: Path
    origin: str
    hosts: tuple[str, ...]
    auth: str
    secret: str
    username: str
    proxies: tuple
    log_level: str
    max_failures: int = 5
    lockout_seconds: int = 60

    @classmethod
    def from_env(cls):
        host = os.environ.get('SAP_LENS_HOST', '127.0.0.1')
        address = ipaddress.ip_address(host)  # Numeric bindings prevent DNS-dependent exposure.
        port = int(os.environ.get('SAP_LENS_PORT', '18743'))
        if not 1 <= port <= 65535: raise ValueError('SAP_LENS_PORT must be between 1 and 65535.')
        data = Path(os.environ.get('SAP_LENS_DATA_DIR', str(default_server_data()))).expanduser()
        sources = Path(os.environ.get('SAP_LENS_SOURCE_DIR', str(data/'sources'))).expanduser()
        if not data.is_absolute() or not sources.is_absolute(): raise ValueError('Server directories must be absolute.')
        app_root = Path(__file__).resolve().parent.parent
        if data.resolve().is_relative_to(app_root): raise ValueError('Server data must be outside immutable application files.')
        if os.environ.get('SAP_LENS_CONFIG_DIR') and Path(os.environ['SAP_LENS_CONFIG_DIR']).resolve() != data.resolve():
            raise ValueError('Server storage overrides disagree; use SAP_LENS_DATA_DIR.')
        origin = os.environ.get('SAP_LENS_PUBLIC_ORIGIN', f'http://127.0.0.1:{port}')
        url = urlsplit(origin)
        if url.scheme not in {'http','https'} or not url.hostname or url.path or url.query or url.fragment or url.username or url.password:
            raise ValueError('Public origin must be an explicit HTTP(S) origin without a path or credentials.')
        try: _ = url.port  # raises ValueError for an invalid port
        except ValueError: raise ValueError('Invalid public origin port.') from None
        hosts = tuple(x.strip().lower() for x in os.environ.get('SAP_LENS_ALLOWED_HOSTS', url.hostname).split(',') if x.strip())
        if not hosts or url.hostname.lower() not in hosts or any('*' in h or '/' in h or '://' in h for h in hosts):
            raise ValueError('Allowed hosts must explicitly include the public hostname; wildcards are forbidden.')
        auth = os.environ.get('SAP_LENS_AUTH', 'local')
        if auth not in {'local','basic','proxy'}: raise ValueError('Choose local, basic or proxy authentication boundary.')
        if auth == 'local' and (not address.is_loopback or url.hostname not in {'localhost','127.0.0.1','::1'}):
            raise ValueError('Local access requires both a loopback binding and a loopback public origin.')
        if url.scheme != 'https' and url.hostname not in {'localhost','127.0.0.1','::1'}:
            raise ValueError('Network browser origins require HTTPS termination.')
        secret = ''
        if auth != 'local':
            path = Path(os.environ.get('SAP_LENS_AUTH_SECRET_FILE',''))
            if not path.is_absolute(): raise ValueError('Configure an absolute authentication secret-file path.')
            with path.open('rb') as stream:
                check_secret_permissions(path, os.fstat(stream.fileno()), os.environ.get('SAP_LENS_AUTH_SECRET_GROUP_READ','').strip().lower() in {'1','true','yes'})
                raw = stream.read(513)
            try: secret = raw.decode('ascii').strip()
            except UnicodeError: raise ValueError('Authentication secret must be ASCII.') from None
            if not 32 <= len(secret) <= 256 or any(c.isspace() for c in secret):
                raise ValueError('Authentication secret must contain 32–256 non-whitespace ASCII characters.')
        proxies = tuple(ipaddress.ip_network(x.strip(),strict=False) for x in os.environ.get('SAP_LENS_TRUSTED_PROXIES','').split(',') if x.strip())
        if any(p.prefixlen == 0 for p in proxies): raise ValueError('Do not trust every peer as a proxy.')
        if auth == 'proxy' and not proxies: raise ValueError('Proxy mode requires explicit trusted proxy addresses/CIDRs.')
        username = os.environ.get('SAP_LENS_AUTH_USER','saplens')
        if not username or ':' in username or len(username)>100: raise ValueError('Invalid shared-access username.')
        level = os.environ.get('SAP_LENS_LOG_LEVEL','info').lower()
        if level not in {'error','warning','info'}: raise ValueError('Use error, warning or info operational logging.')
        max_failures = bounded_int('SAP_LENS_AUTH_MAX_FAILURES', 5, 3, 50)
        lockout = bounded_int('SAP_LENS_AUTH_LOCKOUT_SECONDS', 60, 10, 3600)
        return cls(host,port,data.resolve(),sources.resolve(),origin,hosts,auth,secret,username,proxies,level,max_failures,lockout)

    def authorized(self, request):
        try: peer = ipaddress.ip_address(request.client.host)
        except (ValueError,AttributeError): return False
        if self.auth == 'local': return peer.is_loopback
        if self.auth == 'basic':
            try:
                scheme, value = request.headers.get('authorization','').split(' ',1)
                decoded = base64.b64decode(value,validate=True).decode('utf-8')
                user, password = decoded.split(':',1)
                # Both comparisons always run, so neither the result nor its timing tells which part was wrong.
                user_ok = hmac.compare_digest(user.encode(),self.username.encode())
                password_ok = hmac.compare_digest(password.encode(),self.secret.encode())
                return scheme.lower()=='basic' and user_ok and password_ok
            except (ValueError,UnicodeError): return False
        identity = request.headers.get('x-sap-lens-identity','')
        return (any(peer in network for network in self.proxies if network.version==peer.version)
                and bool(identity.strip()) and len(identity)<=512
                and hmac.compare_digest(request.headers.get('x-sap-lens-proxy-token','').encode(),self.secret.encode())
                and (urlsplit(self.origin).scheme!='https' or request.headers.get('x-forwarded-proto')=='https'))

    def client_address(self, request):
        """Throttle identity of the caller: the TCP peer, or the real client behind a configured trusted proxy.

        X-Forwarded-For is read only when the immediate peer is one of SAP_LENS_TRUSTED_PROXIES. Entries are then taken from the
        right, skipping trusted proxies; the first other address is the client. Anything malformed falls back to the peer, and a
        header sent by an untrusted peer is ignored, so a caller cannot choose its own throttle identity. IPv6 clients share
        one identity per /64, which is what a single subscriber can rotate through.
        """
        try: peer = ipaddress.ip_address(request.client.host)
        except (ValueError,AttributeError): return 'unknown'
        trusted = lambda address: any(address in network for network in self.proxies if network.version==address.version)
        client = peer
        if self.proxies and trusted(peer):
            entries = [part.strip() for line in request.headers.getlist('x-forwarded-for') for part in line.split(',') if part.strip()]
            for entry in reversed(entries):
                try: address = ipaddress.ip_address(entry)
                except ValueError: client = peer; break
                if trusted(address): continue
                client = address; break
        if client.version == 6 and client.ipv4_mapped: client = client.ipv4_mapped
        return str(ipaddress.ip_network(f'{client}/64',strict=False)) if client.version == 6 else str(client)


def check_secret_permissions(path, status, allow_group_read=False):
    """POSIX policy for the shared-access secret, judged on the opened file (no check/use gap, symlinks resolve to their target).

    Allowed: owner-only access (0600 or 0400), the default. Group read (0640 or 0440) is accepted only when the administrator opted in
    with SAP_LENS_AUTH_SECRET_GROUP_READ=1 because a different account must read the file (a container user reading a host file,
    a service group) and the file's group is one the running account itself belongs to, so the group is the intended one. Anything
    that gives other users any access, or lets the group write or execute, is refused. The file is never changed here.
    Windows has no POSIX modes: its ACL is applied when the service is provisioned (docs/deployment/WINDOWS_SERVICE.md).
    """
    if os.name == 'nt': return
    mode, fix = status.st_mode & 0o777, f"Run: chmod 600 '{path}'"
    if mode & 0o007: raise ValueError(f'Authentication secret {path} (mode {mode:04o}) is accessible to other users. {fix}')
    if mode & 0o030: raise ValueError(f'Authentication secret {path} (mode {mode:04o}) is writable or executable by its group. {fix}')
    if mode & 0o040:
        if not allow_group_read:
            raise ValueError(f'Authentication secret {path} (mode {mode:04o}) is readable by group {status.st_gid}. {fix}, or, when a dedicated service group must read it, '
                             'set SAP_LENS_AUTH_SECRET_GROUP_READ=1 and keep the mode at 0640.')
        if status.st_gid not in {os.getegid(), *os.getgroups()}:
            raise ValueError(f'Authentication secret {path} is group-readable by group {status.st_gid}, which the service account does not belong to. '
                             'Use a group of the service account (chgrp) or chmod 600.')


def bounded_int(name, default, low, high):
    raw = os.environ.get(name, '').strip()
    if not raw: return default
    try: value = int(raw)
    except ValueError: raise ValueError(f'{name} must be a whole number.') from None
    if not low <= value <= high: raise ValueError(f'{name} must be between {low} and {high}.')
    return value


class AuthThrottle:
    """Bounded, process-local throttle for failed shared-credential sign-ins.

    A client (see ServerSettings.client_address) that fails `max_failures` times within WINDOW seconds is refused for a cooldown that
    starts at `base_cooldown` and doubles with every further lock-out up to MAX_COOLDOWN, and is then answered with 429 and
    Retry-After without its credentials being evaluated. A correct sign-in clears the client's record. The record of a client that
    stays quiet for IDLE seconds is dropped. At most MAX_CLIENTS clients are tracked: entries that are not locked out go first, so
    address flooding cannot grow memory and cannot evict an active lock-out before the idle ones. State lives in this process only: a
    restart or a second worker starts with empty counters, and many source addresses multiply the attempts that are possible.
    The 32 character minimum for the access secret, not this throttle, is the defence against distributed guessing.
    """
    MAX_CLIENTS = 1024
    WINDOW = 900
    MAX_COOLDOWN = 900
    IDLE = 1800

    def __init__(self, max_failures=5, base_cooldown=60, clock=time.monotonic):
        self.max_failures, self.base_cooldown, self.clock = max_failures, base_cooldown, clock
        self._entries = OrderedDict()  # key -> {count, window, strikes, until, seen}
        self._lock = threading.Lock()

    def __len__(self):
        return len(self._entries)

    def blocked_for(self, key):
        """Seconds until the client may try again; 0 when it may."""
        with self._lock:
            entry = self._entries.get(key)
            remaining = entry['until'] - self.clock() if entry else 0
            return math.ceil(remaining) if remaining > 0 else 0

    def failure(self, key):
        """Record a failed sign-in; returns the cooldown it caused, or 0."""
        with self._lock:
            now = self.clock()
            entry = self._entries.get(key)
            if entry and now - entry['seen'] > self.IDLE: entry = None
            if entry is None:
                entry = self._entries[key] = {'count': 0, 'window': now, 'strikes': 0, 'until': 0.0, 'seen': now}
            elif now - entry['window'] > self.WINDOW:
                entry['count'], entry['window'] = 0, now
            entry['seen'] = now
            entry['count'] += 1
            self._entries.move_to_end(key)
            cooldown = 0
            if entry['count'] >= self.max_failures:
                entry['strikes'] += 1
                entry['count'], entry['window'] = 0, now
                cooldown = min(self.base_cooldown * 2 ** (entry['strikes'] - 1), self.MAX_COOLDOWN)
                entry['until'] = now + cooldown
            if len(self._entries) > self.MAX_CLIENTS: self._evict(now)
            return cooldown

    def success(self, key):
        with self._lock:
            self._entries.pop(key, None)

    def _evict(self, now):
        for key in [k for k, e in self._entries.items() if now - e['seen'] > self.IDLE]: del self._entries[key]
        for key in [k for k, e in self._entries.items() if e['until'] <= now]:
            if len(self._entries) <= self.MAX_CLIENTS: return
            del self._entries[key]
        while len(self._entries) > self.MAX_CLIENTS: self._entries.popitem(last=False)


def source_path(value):
    """Server file access is confined to a configured root or opaque managed uploads."""
    path = Path(value).expanduser()
    if not server_mode(): return path
    if not path.is_absolute(): raise ValueError('Use a server-visible absolute source path.')
    data = Path(os.environ.get('SAP_LENS_DATA_DIR',str(default_server_data()))).resolve()
    root = Path(os.environ.get('SAP_LENS_SOURCE_DIR',str(data/'sources'))).resolve()
    resolved = path.resolve()
    if not any(resolved.is_relative_to(parent) for parent in (root,data/'uploads')):
        raise ValueError('CSV source is outside the configured source directory.')
    return resolved


def validate_server_sources(settings):
    if not server_mode(): return
    data = Path(os.environ['SAP_LENS_DATA_DIR']).resolve()
    for source, path in [('roles',settings.data_csv_path),('users',settings.user_csv_path),('employees',settings.employee_csv_path),('sod',settings.sod_csv_path)]:
        if path:
            resolved = source_path(path)
            if resolved.is_relative_to(data/'uploads') and getattr(settings.source_modes,source)!='static':
                raise ValueError('Browser uploads must use Static source mode.')
