# Server security boundary

SAP Lens contains sensitive employee and access information. CORS, a private LAN,
firewall rules and an `X-SAP-Lens` marker are **not authentication**. Do not expose
an unauthenticated backend. No internet publishing is performed by these tools.

## Local testing

Native server defaults to loopback and `SAP_LENS_AUTH=local`. It rejects non-loopback
binds in this mode and validates real TCP peers. Local mode trusts other local users;
use Basic/proxy protection even locally when the machine is shared. Unauthenticated
liveness/readiness endpoints contain only a status word.

Compose binds inside its container on `0.0.0.0`, but publishes **only 127.0.0.1** on
the host by default and requires Basic authentication. Do not change that publication
without configuring the intended HTTPS origin and access boundary.

## Controlled internal deployment: shared Basic access

Generate an unpredictable access secret, without printing it:

```sh
python backend/server.py --init-secret /absolute/private/access.secret
```

Configure `SAP_LENS_AUTH=basic`, `SAP_LENS_AUTH_SECRET_FILE`, and optionally
`SAP_LENS_AUTH_USER` (default `saplens`). Read the secret locally in a trusted editor
when entering the browser's HTTP authentication prompt; never commit or log it.
For POSIX, file permissions must exclude other users (0600 or restricted 0640).
Windows installation grants the dedicated service SID read permission.

For network browser access set `SAP_LENS_PUBLIC_ORIGIN=https://lens.example.test`,
`SAP_LENS_ALLOWED_HOSTS=lens.example.test` and terminate TLS at a reverse proxy.
The proxy forwards Authorization; direct backend requests still require credentials.
Keep backend binding loopback or isolate it on a private container network. Never
send Basic credentials over an unencrypted LAN. HTTP loopback origins are supported
for local testing only; the backend rejects nonlocal HTTP public origins.

Basic access is intentionally minimal: one shared administrator credential, no
logout/session management, brute-force throttling or per-user permissions. All
people with access can import, export and change settings. Prefer an enterprise
gateway for real organizational deployments, with throttling and access auditing.

## Authenticated identity gateway

Use `SAP_LENS_AUTH=proxy`, a private shared secret file, and explicit
`SAP_LENS_TRUSTED_PROXIES` (real immediate peer IP/CIDR, not client addresses).
The authenticated gateway **must strip client-supplied values** and set:

- `X-SAP-Lens-Proxy-Token`: private gateway/backend secret.
- `X-SAP-Lens-Identity`: nonempty authenticated identity.
- `X-Forwarded-Proto: https` for an HTTPS public origin.

The backend validates all three plus the actual TCP peer before serving frontend
or API. Forged `X-Forwarded-For` cannot change that peer: Uvicorn proxy-header trust
is disabled. Configure an exact proxy CIDR, never `/0`. Do not put the secret in
client JavaScript, URLs or portable application configuration. Restrict gateway
configuration and file permissions. Proxy authorization proves gateway admission;
SAP Lens does not yet implement identity-based permissions or an audit ledger.

Nginx, Traefik and Caddy can either forward Basic authentication unchanged or sit
behind an authenticated gateway and overwrite the headers above. The following
examples use **backend Basic protection**, not a fictitious built-in SSO provider.
Use administrator-managed certificates and an explicitly configured internal host.

### Nginx (inside an administrator-managed HTTPS server block)

```nginx
server_name lens.example.test;
# listen 443 ssl; ssl_certificate /...; ssl_certificate_key /...;
location / {
    proxy_pass http://127.0.0.1:18743;
    proxy_set_header Host $host;
    proxy_set_header Authorization $http_authorization;
    proxy_set_header X-Forwarded-Proto https;
    proxy_request_buffering off;
    client_max_body_size 128m;
    proxy_read_timeout 180s;
}
```

### Caddy (explicit certificate, no automatic public registration)

```caddyfile
https://lens.example.test {
    tls /etc/caddy/lens.crt /etc/caddy/lens.key
    reverse_proxy 127.0.0.1:18743
}
```

### Traefik dynamic configuration (existing secured HTTPS entrypoint)

```yaml
http:
  routers:
    sap-lens:
      rule: Host(`lens.example.test`)
      entryPoints: [websecure]
      tls: {}
      service: sap-lens
  services:
    sap-lens:
      loadBalancer:
        passHostHeader: true
        servers:
          - url: http://127.0.0.1:18743
```

Do not use localhost to address a backend from a different container: select a
private service network, explicit proxy peer boundary and service DNS upstream.
No WebSocket application channel is currently required. API URLs are same-origin;
subpath mounting is not supported. Same-origin checks use the configured public
origin, not untrusted forwarded host headers. No application authentication cookies
are introduced; TLS termination and any gateway cookies remain gateway-owned.

## Files and privacy

Use separate immutable application, mutable data and read-only CSV source roots.
Uploaded file names are validated and destinations generated server-side. CSV reads
are confined to source/upload roots, including resolved symlink checks. Uploads
stream with enforced bounds and do not activate until existing validation/confirmation.
Never mount the Docker socket or run privileged. Restrict access to backups and
volumes: they contain personal/access data. Server diagnostics are redacted; logs
do not dump unexpected exception text, CSV rows or HTTP request details.

## Future authentication

Before wider multi-user hosting, implement/review local accounts or OIDC/enterprise
SSO, secure login/logout sessions, Administrator/Analyst/Viewer authorization,
import/settings/export permissions, user-specific preferences, and privacy-aware
audit logging. Define identity and retention policy first. This iteration deliberately
does not add a custom user database or claim shared access provides per-user audit.
