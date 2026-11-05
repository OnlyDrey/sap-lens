# Security architecture

## Runtime boundary

Desktop reserves an owned loopback socket and uses a fresh per-launch capability
for API reads/writes and native bridge operations. Host/origin checks target its
selected port and explicit loopback origins. WebView2 receives the capability in a
fragment, removed into session storage. Plain desktop browser root navigation can
receive it through a non-cacheable CSP-nonced handoff, restricted by Fetch Metadata,
exact Host/port and loopback peer. Cross-site/frame/resource requests cannot bootstrap
a session; API capability and Origin checks remain mandatory. Runtime diagnostics
do not contain it. See [desktop connectivity](DESKTOP.md).
WebView2 shutdown owns backend shutdown; unrelated listeners are never killed.

Headless server uses the same FastAPI factory without WebView2. The supported
server entry point owns storage locking and lifecycle. Defaults bind loopback;
non-local access requires explicit Basic/proxy protection, exact public origin,
allowed hosts and trusted peers where applicable. Public liveness/readiness expose
no records. All other routes enforce the configured boundary. See the authoritative
[deployment security guide](../deployment/SECURITY.md) for configuration and proxy examples.
CORS/firewalls are not authentication. This is shared internal access, not per-user RBAC.

## Data and mutations

Schema/revision checks, bounded parsing, staged immutable snapshots and atomic
configuration pointers prevent invalid replacements. Failed imports retain validated
data. Private records, paths, reports and credentials are excluded from sanitized
diagnostic exports and routine logs. Settings/backup/snapshot directories require
appropriate account permissions; local administrator access is outside this boundary.
See [CSV lifecycle](../data/IMPORT_AND_REFRESH.md) and [Configuration](../getting-started/CONFIGURATION.md).

Browser uploads go to the configured server only, with limits and server-selected
staging paths. Headless mode never opens native desktop dialogs. React text output,
same-origin requests and CSP preserve the browser boundary; no service worker
caches SAP data. Branding images are validated/reencoded, never trusted SVG or arbitrary paths.

## Supply chain and review

Canonical packagers verify manifests, exact archive members, frontend integrity,
privacy exclusions and checksums. Windows production verifiers also inspect PE,
resources and embedded identity. Packages remain unsigned; their own checksums
are not independent publisher authentication. Preserve [third-party and product
licensing](../../LICENSE.md). Run current [dependency checks](../development/TESTING.md),
not historical advisory counts, when assessing a new source revision.

[Privacy](PRIVACY.md) records accepted unresolved historical branding P-01; current
cleanup does not erase Git history or establish legal ownership.

## Findings register and verified controls

An internal, evidence-based review (not a penetration test or certification). Regression coverage:
`backend/tests/test_security_surface.py` calls every API operation without the launch capability, with a foreign `Origin`, a wrong capability and a
foreign `Host`, and in server mode without or with wrong credentials. The [validation tracker](../validation/README.md) (`SEC-001` to `SEC-008`,
`R81-01` to `R81-03`) holds the checks to repeat on each release.

| ID | Severity | Finding | Status |
| --- | --- | --- | --- |
| SEC-01 | Low | CSV formula neutralisation missed some leading characters | Fixed: every CSV writer uses `spreadsheet_cell` |
| SEC-02 | Low | No throttling of failed Basic sign-ins | Fixed: per-client lockout with 429 and `Retry-After` |
| SEC-03 | Low | Secret file accepted when group-readable | Fixed: created `0600`; readable-by-others files are rejected |
| SEC-04 | Informational | CSP allows inline styles (measured coordinates); no HSTS or `Permissions-Policy` | Accepted; set transport headers at the TLS proxy |
| SEC-05 | Informational | Upload response returns the staging path to the authenticated client | Accepted; the client needs it to select the source |
| SEC-06 | Informational | One shared access boundary; reviewer names are self-reported | Documented limitation |
| SEC-07 | Informational | Further systemd sandboxing possible | Open hardening opportunity |

Verified in practice: capability, origin and host checks on every `/api/` operation (only `/health*` is outside); custom `X-SAP-Lens` header and no
cookie authentication; no unsafe sinks (`eval`, `exec`, `pickle`, unsafe YAML, shell, HTML injection); path confinement for server reads and uploads;
bounded JSON, CSV and upload sizes; one generic 500 message; loopback binding by default; secrets from files only; no SAP data in browser storage
or a service worker; non-root, read-only containers with dropped capabilities. Run current `npm audit` and `pip-audit` for each source revision.

Not tested here: native Windows (WebView2 isolation, service account and ACLs, UNC, installer), real systemd and Docker runtime acceptance, active
penetration testing, parser fuzzing and TLS termination at a real proxy.
