"""HTTP session boundary: explicit public auth routes, deny-by-default writes."""
import re
import hmac
from auth_store import AuthError, AuthStore, require
from routers.authentication import COOKIE, router_for

PUBLIC = {'/api/auth/state', '/api/auth/login', '/api/auth/reset', '/api/auth/activate', '/api/auth/recover'}
ADMIN_READ = ('/api/backups', '/api/storage', '/api/retention', '/api/diagnostics', '/api/configuration', '/api/settings')


def permission(method, path):
    if path == '/api/branding/preview': return 'unknown'
    if path.startswith('/api/auth/users') or path in {'/api/auth/audit','/api/auth/policy'}: return 'accounts'
    if path.startswith('/api/auth/'): return 'profile'
    if method in {'GET', 'HEAD'}:
        return 'admin' if path.startswith(ADMIN_READ) else 'read'
    if method != 'POST': return 'unknown'
    if path == '/api/compare': return 'read'
    from server_access import may_access
    if may_access('read-only', 'POST', path): return 'export'
    if re.fullmatch(r'/api/sod/periods/[^/]+/transition', path): return 'approve'
    if may_access('reviewer', 'POST', path): return 'review'
    if path.startswith(('/api/settings','/api/configuration','/api/refresh','/api/server/','/api/data-sources','/api/sources','/api/branding','/api/storage','/api/retention','/api/backups','/api/import','/api/sod/configuration','/api/sod/reference','/api/sod/periods','/api/saved-filters','/api/functional-groups','/api/user-import','/api/employees','/api/data/cancel','/api/refresh-schedule','/api/sod/catalogue')): return 'admin'
    return 'unknown'


def install(app, server):
    store = AuthStore(server.data / 'security/accounts.sqlite3')
    app.state.identity_store = store
    app.include_router(router_for(store, server.origin.startswith('https://')))
    return store


def authorize(store, request, server):
    # A TLS public origin alone is not proof of secure browser transport.
    if request.url.scheme != 'https':
        try:
            import ipaddress
            peer = ipaddress.ip_address(request.client.host)
            local = peer.is_loopback and server.host in {'127.0.0.1', '::1'} and not server.origin.startswith('https://')
            proxied = (server.origin.startswith('https://') and any(peer in network for network in server.proxies)
                       and request.headers.get('x-forwarded-proto') == 'https' and bool(server.secret)
                       and hmac.compare_digest(request.headers.get('x-sap-lens-proxy-token','').encode(), server.secret.encode()))
            if not (local or proxied): raise AuthError('secure_transport_required', 403)
        except (ValueError, AttributeError): raise AuthError('secure_transport_required', 403) from None
    if request.url.path in PUBLIC or not request.url.path.startswith('/api/'):
        return None
    actor = store.session(request.cookies.get(COOKIE, ''))
    require(actor, permission(request.method, request.url.path))
    if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        store.csrf(actor, request.headers.get('x-sap-lens-csrf', ''))
    return actor
