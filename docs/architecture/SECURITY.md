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

## Authentication and portable-state implementation contract (2026-11-12)

**Approved design, not a claim of completed implementation.** Phase gates are
tracked in development/PROGRESS.md. This contract supersedes earlier planned
mandatory reviewer/approver separation: self-approval is permitted, but completion
and explicit approval remain separate authenticated events.

### Runtime and persistence boundaries

Server clients use application login and revocable server-side sessions. Desktop
retains its loopback launch capability and requires no login. Its local reviewer
profile has a generated stable identifier and explicit unverified-local provenance.
React/Vite and the existing domain, source-validation and evidence services remain.

A dedicated durable `security/accounts.sqlite3` under application state owns users,
sessions, bootstrap/reset verifiers, security policy, migrations and security audit.
It is NOT the optional rebuildable `store/sap-lens.sqlite3`; corruption/missing
security state fails closed. One leased runtime remains supported. WAL, bounded
busy handling and BEGIN IMMEDIATE protect writes; account changes, last-admin
checks, audit records and revocation are committed together. No external database
or second frontend state store is introduced.

Logical tables: users (immutable UUID, exact username, display name, role, enabled,
password verifier/format, credential version, revision, created/last-login times);
sessions (token digest, user UUID, credential version, CSRF verifier, creation,
last-use and expiry); bootstrap (purpose, verifier, expiry, attempts, consumed);
password resets (single-use digest, user UUID, expiry); policy (idle/absolute
session limits, revision); audit (UUID, UTC timestamp, actor UUID and identity
snapshot, operation, target UUID, safe before/after metadata); migration journal.
Passwords, session tokens, activation codes and password hashes never enter audit.

Argon2id is the preferred new verifier, with explicitly pinned maintained tooling.
Existing PBKDF2 verifiers remain verifiable and are upgraded after successful
login; no plaintext password is needed for migration. Minimum new password length
is 12 characters; allow Unicode/passphrases up to a documented bounded limit (at
least 1,024 UTF-8 bytes). Password verification occurs off the event loop, outside
the write transaction, then rechecks account/version before issuing a session.

### Sessions and transport

Session identifiers contain at least 256 random bits; only their digests persist.
Cookies are HttpOnly, host-only, SameSite=Lax, Path=/ and Secure under HTTPS.
Application tokens never enter localStorage. A separate session-bound CSRF value
is available to same-origin frontend code and must match a custom header on all
state-changing requests. Retain origin/host checks and JSON/custom-header guards
on login/bootstrap/reset routes to prevent login CSRF. Logout is an authenticated
CSRF-protected mutation. Password changes, resets, deactivation and administrative
revocation invalidate sessions. Session responses are non-cacheable.

Default policy: 30-minute idle timeout, 12-hour absolute timeout, administrator
configurable within bounded documented ranges. Record last-use at a bounded
interval rather than writing on every asset/API read. Revalidate account/security
versions on requests; never cache a revoked permission indefinitely. Login uses
bounded temporary throttling; bootstrap/reset verification also has durable
attempt limits and expiry. Unknown/disabled users and wrong passwords receive the
same safe external response. Log categories, never headers or credential values.

Remote password authentication requires verified TLS: direct TLS or an explicitly
trusted immediate proxy with HTTPS public origin and exact proxy policy. Client
forwarded headers alone are insufficient. The earlier remote HTTP acknowledgement
is not a session-authentication bypass. Incompatible legacy deployments stop with
operator guidance; they are not silently downgraded or remotely bootstrapped.

### Permission matrix

| Operation | Administrator | Reviewer | Viewer |
| --- | --- | --- | --- |
| Authorized investigation/search/compare/read | Yes | Yes | Yes |
| Authorized CSV/report generation | Yes | Yes | Yes |
| Decisions, remediation, explicit approval (including own) | Yes | Yes | No |
| Imports, settings, branding, retention, backup/restore | Yes | No | No |
| Users, role changes, resets, all-user revocation, security audit | Yes | No | No |
| Own profile/password/session management | Yes | Yes | Yes |

Protected operations deny by default, including newly introduced routes. Safe
report POSTs are explicit permissions, not blanket POST access. `/health/live`
and `/health/ready` disclose minimal process status. Public authentication/setup
routes expose only the state necessary to show login/setup, never an activation
code, account inventory or application data. Browser Basic credentials do not
bypass the new session model. Legacy `read-only` migrates to `viewer`.

### Bootstrap and controlled recovery

State machine: uninitialized -> activation-issued -> administrator-created ->
initialized. The local manager/CLI creates a cryptographically random code and
shows it once to the local operator; only a verifier persists. Implemented
expiry is fifteen minutes, with five failed attempts invalidating that code. Rotation
invalidates its predecessor. Atomic consume plus first-admin creation rejects
replay/concurrent setup. Restart preserves issued/consumed state.

Never infer uninitialized state from an unreadable/missing account store. Fresh
setup requires an explicitly classified fresh installation. Existing populated
state needs migration or an explicit authenticated local recovery operation.
Recovery is an elevated/local-host action with confirmed scope, backup and audit;
it never silently reopens public first-run setup or resets an existing password.
Linux/Docker use an equivalent local CLI; the Windows manager is not a dependency.

### Identity and immutable evidence

New server decisions and approvals obtain actor UUID, username/display snapshot,
UTC timestamp and context from the backend session. Client reviewer strings are
not authoritative. Existing strings remain readable with legacy provenance; do not
infer mappings from matching names. Do not rewrite frozen snapshots or historic
events. New optional identity fields must be backward-compatible with old schemas.
Desktop uses its stable local profile, clearly distinguished from authenticated
server attribution. Preserve revision/evidence checks and explicit approval gates
other than the superseded different-person restriction.

### Migration and rollback

Detect legacy individual-account JSON explicitly, validate it and preserve password
verifiers, enabled state and roles. Assign UUIDs once in a versioned transaction;
retry uses the migration journal, not fresh duplicate users. Preserve the original
protected file and verified migration backup until administrator confirmation.
Missing/corrupt stores and ambiguous bootstrap states block startup with safe
recovery guidance. Shared Basic/proxy/local deployments do not become known-password
accounts: require controlled local activation and secure transport configuration.
No production data or installed service is automatically replaced by development.

A failed transaction rolls back. Cross-file upgrades/restores use staged activation
and the existing recovery journal/lease. Retain the previous application/security
state and a verified backup, but never select older binaries against a newer schema
without a compatibility check. Native SCM evidence for source 50e55d0 and its exact
package hash is historical evidence only; new packages need their own acceptance.

### Complete backup contract

Versioned manifest includes application/component/schema versions, UTC creation,
component inventory, checksums and compatibility requirements. Inventory includes
authentication database (accounts/roles/verifiers/audit, without active sessions),
source snapshots/metadata, settings, application and report branding configuration
and PNG assets, decisions, periods, approvals, evidence and persistent local identity.
SQLite cache remains separately identified as rebuildable; capture a consistent
SQLite database snapshot if included, never a live database/WAL file copy.

Encrypt portable archives using a maintained authenticated cipher (AES-256-GCM)
and a bounded password KDF; never invent cryptography. Authenticate envelope version,
KDF parameters and manifest. Keys are never adjacent to archives. Interactive
passphrases travel through secure UI/stdin. Unattended backup uses an explicit
protected host key/secret provider with separate escrow; a backup cannot be called
recoverable until that key has an operator-tested recovery procedure. Missing key
configuration fails backup, not confidentiality. Never log a passphrase/code/key.

Exclude active sessions, runtime locks, disposable caches/builds, OS registration,
service credentials, TLS private keys and host listener bindings. Portable account
state is encrypted, not silently excluded. Restore decrypts/authenticates, validates
paths/limits/checksums/versions, stages data, verifies database integrity and snapshot
references, previews all replacements and requires explicit account/data rollback
acknowledgement. Failed activation rolls back; restored accounts revoke sessions.
Branding references must resolve to restored validated assets.

Retain existing policy: automatic backups 90 days; manual backups until explicit
deletion; migration backups until administrator confirmation and authorized
retention; application data 24 months with active/evidence-reference protections.
No blanket destructive cleanup or silent empty-dataset activation is introduced.

### Phase acceptance

1. Inventory/design and migration scenarios reviewed against code/test definitions.
2. Authentication, permission negatives, concurrency, last-admin, revocation, CSRF.
3. Fresh bootstrap, replay/attempt limits, restart, interrupted/concurrent setup.
4. Login/profile/admin browser workflows, accessibility, server/desktop distinction.
5. Actor snapshots, legacy evidence, local profile, explicit self-approval.
6. Authenticated encryption, branding/accounts roundtrip, exclusions, rollback.
7. Populated upgrades, retries, missing/corrupt state, verified backups and recovery.
8. Integrated backend/frontend/full local suites; SoD browser single worker;
   platform builds only where supported, native acceptance reported separately.
