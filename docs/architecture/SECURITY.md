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

## Local session lifecycle and start-up recovery

**Mechanism.** Each desktop process draws a random capability (`secrets.token_urlsafe(32)`), keeps it only in memory and requires it as `X-SAP-Lens` on every `/api/` request. The desktop window receives it in a URL fragment
(never sent in HTTP) and the frontend keeps it in the window's `sessionStorage`. The guarded root document `GET /` hands the *current* capability to a request that is a verified top-level navigation to the exact loopback
listener (`Sec-Fetch-Mode: navigate`, `Sec-Fetch-Dest: document`, `Sec-Fetch-Site` none/same-origin/same-site, an allowed `Origin` if present, an allowed `Host`, a loopback peer). Frames, scripts, `fetch`, cross-site pages, other hosts and other peers never receive it.

**Root cause of the start-up message.** A window that holds a capability from an earlier run (a surviving `sessionStorage` or tab at the same, fixed port) sends it to the new process. The backend correctly answers
`403` with `code: stale_session` (a missing capability is treated the same). Before this change the start-up gate treated that answer as final and asked the person to choose between *Reload trusted session*, *Retry connection* and *Open Backup & Restore*,
although the recovery it offered (reload the guarded document) needs no decision. Readiness was not the cause: the desktop launcher only navigates after the backend answered its readiness probe. Which Windows condition leaves
the old capability in the window is not reproducible on Linux (see the validation steps below); the recovery works for every cause because it starts from the server's answer, not from a guess about the client.

**Recovery.** `StartupGate` classifies the first configuration answer (`frontend/src/lib/startupRecovery.ts`):

| Answer | Class | Behavior |
| --- | --- | --- |
| no response, 502, 503, 504 | unavailable | label "Connecting to local service…", at most 6 retries with 0.5, 1, 2, 3, 4, 5 s back-off, then the recovery screen |
| 403 `stale_session` | session | label "Restoring workspace…": one automatic reload of the guarded document per 60 s (`sessionStorage` key `sap-lens-session-recovery`), then loading again; a second stale answer inside the window shows the recovery screen, never a loop |
| 401, 403 without the marker | rejected | recovery screen "Access was not accepted"; no restore, no retry loop |
| 500 and other | failed | recovery screen "could not load its configuration"; no automatic retry; *Open Backup & Restore* offered here only |

The recovery screen has one primary action (*Retry connection*), collapsed technical details (class, status, message; never the capability) and no other session-specific action. While the application runs, a backend restart
produces the same automatic restore when nothing typed into an open form would be lost; otherwise the existing notification keeps its explicit *Reconnect session* action.

**Boundaries.** Authentication is unchanged. The restore sends no credential and trusts no client claim: the server decides, per request, whether the navigation may receive the capability. Server-hosted deployments never inject a capability and never emit
`stale_session` (they answer `401` with their own authentication); the frontend therefore never restores automatically there. Unsaved input is never discarded by an automatic restore, writes are never replayed, and no stored data is touched.

**Windows validation (not run here).** Reproduce on a Windows desktop: (1) start SAP Lens, open Settings, note the window; (2) close it completely (tray *Exit*) and start it again: it must open without a recovery screen; (3) to force the stale case start SAP Lens,
open `http://127.0.0.1:18743/` in a browser tab, exit SAP Lens, start it again, and reload the old tab: it must show "Restoring workspace…" briefly and then the application; (4) block the new process (rename the exe for 20 s) and start the tab's reload: "Connecting to local service…", then the unreachable screen after about 15 s;
(5) confirm `%LOCALAPPDATA%\SAP Lens` logs contain no capability.

