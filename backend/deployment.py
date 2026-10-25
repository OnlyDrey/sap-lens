"""Hosting policy only; desktop defaults and SAP processing remain independent."""
from dataclasses import dataclass
import base64
import hmac
import ipaddress
import os
from pathlib import Path
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
        try: url.port
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
            with path.open('rb') as stream: raw = stream.read(513)
            try: secret = raw.decode('ascii').strip()
            except UnicodeError: raise ValueError('Authentication secret must be ASCII.') from None
            if not 32 <= len(secret) <= 256 or any(c.isspace() for c in secret):
                raise ValueError('Authentication secret must contain 32–256 non-whitespace ASCII characters.')
            if os.name != 'nt' and path.stat().st_mode & 0o007: raise ValueError('Authentication secret must not be accessible to other users.')
        proxies = tuple(ipaddress.ip_network(x.strip(),strict=False) for x in os.environ.get('SAP_LENS_TRUSTED_PROXIES','').split(',') if x.strip())
        if any(p.prefixlen == 0 for p in proxies): raise ValueError('Do not trust every peer as a proxy.')
        if auth == 'proxy' and not proxies: raise ValueError('Proxy mode requires explicit trusted proxy addresses/CIDRs.')
        username = os.environ.get('SAP_LENS_AUTH_USER','saplens')
        if not username or ':' in username or len(username)>100: raise ValueError('Invalid shared-access username.')
        level = os.environ.get('SAP_LENS_LOG_LEVEL','info').lower()
        if level not in {'error','warning','info'}: raise ValueError('Use error, warning or info operational logging.')
        return cls(host,port,data.resolve(),sources.resolve(),origin,hosts,auth,secret,username,proxies,level)

    def authorized(self, request):
        try: peer = ipaddress.ip_address(request.client.host)
        except (ValueError,AttributeError): return False
        if self.auth == 'local': return peer.is_loopback
        if self.auth == 'basic':
            try:
                scheme, value = request.headers.get('authorization','').split(' ',1)
                decoded = base64.b64decode(value,validate=True).decode('utf-8')
                user, password = decoded.split(':',1)
                return scheme.lower()=='basic' and hmac.compare_digest(user.encode(),self.username.encode()) and hmac.compare_digest(password.encode(),self.secret.encode())
            except (ValueError,UnicodeError): return False
        identity = request.headers.get('x-sap-lens-identity','')
        return (any(peer in network for network in self.proxies if network.version==peer.version)
                and bool(identity.strip()) and len(identity)<=512
                and hmac.compare_digest(request.headers.get('x-sap-lens-proxy-token','').encode(),self.secret.encode())
                and (urlsplit(self.origin).scheme!='https' or request.headers.get('x-forwarded-proto')=='https'))


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
    for source, path in [('roles',settings.data_csv_path),('users',settings.user_csv_path),('employees',settings.employee_csv_path)]:
        if path:
            resolved = source_path(path)
            if resolved.is_relative_to(data/'uploads') and getattr(settings.source_modes,source)!='static':
                raise ValueError('Browser uploads must use Static source mode.')
