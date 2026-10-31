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
cleanup does not erase Git history or establish legal ownership. The latest [security review (R8)](../development/SECURITY_REVIEW_R8.md) lists findings, verified controls and untested areas; the [dated source
review](../archive/implementation/SECURITY_REVIEW.md) is historical evidence, not a
formal penetration test or certification of the current deployment.
