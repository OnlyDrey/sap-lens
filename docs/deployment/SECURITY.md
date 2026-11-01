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
On POSIX the secret must be owner-only (0600 or 0400); `--init-secret` creates it that way. Group read (0640 or 0440) is refused unless you set
`SAP_LENS_AUTH_SECRET_GROUP_READ=1` because another account has to read the file (a container user reading a host file, a dedicated service
group) **and** the file's group is one the service account belongs to. Any access for other users, and group write or execute, is always refused,
and the file is never changed by SAP Lens. A refusal names the file, its mode and the fix (`chmod 600`). Existing installations with a 0640 secret
must either run `chmod 600` (when the service user owns the file) or add the variable; the Docker installer and `compose.yml` already do.
Windows has no POSIX modes: provisioning (`manage-server-service.ps1`) replaces the ACL with SYSTEM, Administrators and read for the service SID; the
runtime does not verify an ACL, so confirm it with `icacls` after manual changes.

For network browser access set `SAP_LENS_PUBLIC_ORIGIN=https://lens.example.test`,
`SAP_LENS_ALLOWED_HOSTS=lens.example.test` and terminate TLS at a reverse proxy.
The proxy forwards Authorization; direct backend requests still require credentials.
Keep backend binding loopback or isolate it on a private container network. Never
send Basic credentials over an unencrypted LAN. HTTP loopback origins are supported
for local testing only; the backend rejects nonlocal HTTP public origins.

Basic access is intentionally minimal: one shared administrator credential, no
logout/session management or per-user permissions. All people with access can import,
export and change settings. Prefer an enterprise gateway for real organizational
deployments, with throttling and access auditing.

### Failed sign-in throttling

A client that sends wrong Basic credentials `SAP_LENS_AUTH_MAX_FAILURES` times (default 5, range 3 to 50) within 15 minutes is locked out for
`SAP_LENS_AUTH_LOCKOUT_SECONDS` (default 60, range 10 to 3600); every further lock-out doubles the cooldown up to 15 minutes. While locked out
the client receives `429 Too Many Requests` with `Retry-After`, even for correct credentials, which are not evaluated. A correct sign-in clears the
client's record; requests without an Authorization header are only challenged and never counted; health probes are exempt. The wrong username and
the wrong password are indistinguishable, nothing secret is logged (the log line names only the client address and the cooldown).

The client is the TCP peer, or, when the peer is in `SAP_LENS_TRUSTED_PROXIES`, the first address from the right in `X-Forwarded-For` that is not
itself a trusted proxy; a header from any other peer is ignored, so it cannot be spoofed. IPv6 clients count per /64. Limits to know:

- State is per process and bounded (1024 clients, idle records dropped after 30 minutes); a restart or a second worker starts with empty counters, and the headless runtime uses one worker.
- Behind a reverse proxy that is **not** listed in `SAP_LENS_TRUSTED_PROXIES`, every user shares the proxy's address, so one attacker can lock everyone out. List the proxy and make it set `X-Forwarded-For`, or throttle at the gateway.
- People behind one NAT address share a lock-out. An attacker with many addresses is slowed, not stopped; the 32 character minimum for the secret is the real defence.

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
