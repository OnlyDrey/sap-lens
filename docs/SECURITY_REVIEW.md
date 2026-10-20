# Security and optimization review

Scope: current backend, CSV ingestion, frontend requests/rendering, local settings, desktop lifecycle/native bridge, dependencies and Windows packaging. This is a source-backed implementation review with tests/audits, not a completed formal Codex Security scan or penetration test; that skill's supporting scan resources were unavailable. Windows-specific claims remain conditional on the Windows workflow and target-PC checklist.

## Implemented improvements

| Area | Improvement |
| --- | --- |
| Local ownership | Prebound loopback socket; conflict selects an OS-assigned port without probing or terminating its owner |
| Browser boundary | Exact selected desktop origin, no wildcard, explicit Host checks and a fresh per-launch capability for API reads/writes |
| Native bridge | Capability-guarded CSV/logo pickers, configuration export and fixed configuration-folder action |
| Request validation | Absolute filesystem CSV paths only, no URLs; two-to-five-role comparison limit; duplicate rejection; route-specific streamed POST limits (16 KiB default) |
| Process lifecycle | In-process daemon API/CSV workers, readiness check, graceful bounded shutdown and Windows instance-handle ownership; no detached backend subprocess |
| Startup | CSV loads asynchronously; missing data does not prevent the window or Settings; missing WebView2 is explained before starting a service |
| Cache correctness | Atomic details/summaries/module/index generations; refresh cannot leave a stale T-code index |
| Failed operations | Validated file/location changes publish only after persistence succeeds; old data/settings remain on failure |
| Sensitive data | No source CSV in artifacts; no-store API responses; sanitized counts/stages instead of CSV values, source paths, launch tokens or tracebacks in app logs |
| Frontend | React text rendering, same-origin native fetch, no external fonts; strict script/frame policy; no offline SAP response cache |
| Packaging | Windowed EXE, icon/version metadata, pinned action commits, read-only workflow permissions and checkout credential persistence disabled |
| Smoke cleanup | Tracks owned process handles/ancestry instead of terminating every process with a matching name |

The desktop capability arrives in a fragment, which HTTP requests do not send. The frontend immediately removes it from the URL and keeps it only in private window session storage so reloads work. It is regenerated on each launch and never included in runtime diagnostics. CSP restricts scripts to bundled resources and prohibits framing. Local same-user malware, administrator access and compromised WebView2/source code remain outside this capability boundary.

## Dependency checks

On 2026-10-20:

- `npm audit --omit=dev`: **zero reported production advisories**.
- Full `npm audit`: **seven affected development packages** (five high, two moderate), all in Tailwind 3 glob/selector tooling. The earlier lockfile returned 29. These advisory counts are not confirmed remotely exploitable SAP Lens findings. Do not build untrusted source trees/CSS. A Tailwind 4 migration could remove that chain but changes styling/build semantics and is deferred to preserve the UI.
- `pip-audit -r backend/requirements-desktop.txt --vulnerability-service pypi`: **24 resolved Linux-platform desktop packages, no known advisories**. Windows-only transitive packages are not covered by this Linux resolution; Windows CI runs a separate installed-environment audit. Audit feeds and pinned packages do not prove vulnerability absence.
- `pip check`: no broken installed requirements.

Vite, its React plugin, concurrently, FastAPI/Uvicorn and transitive frontend packages were updated. Axios and pandas/numpy runtime requirements were removed. Python direct application/desktop versions are pinned; transitive versions are not fully hash-locked. Unsigned executable distribution and dependencies remain supply-chain trust decisions. The repository does not contain credentials, live SAP exports, local settings or runtime logs as build inputs.

## Performance and remaining limits

CSV parsing streams required fields instead of materializing pandas plus dictionary copies. Summaries/counts and the reverse T-code index are built once per refresh. Comparisons are bounded, and each request holds one cache generation. The production JavaScript is approximately 333 kB / 99 kB gzip including settings and native-picker integration. No measured end-user startup latency or EXE-size improvement is claimed until Windows packaging is run.

A complete role graph still resides in RAM; there is no strict dataset-size sandbox. Filesystem reads can block at OS level; loads are serialized and new requests receive a busy response while waiting. Initial loads do not delay API readiness, and canceled daemon workers cannot prevent process exit. Cancel the pending load and use a trusted local export; publication generation checks prevent abandoned reads replacing newer state. At most two CSV worker threads and two preview slots are accepted.

UNC paths can use the signed-in user's network credentials: choose trusted shares only. Per-user settings/session diagnostics use normal filesystem permissions, not encryption. The app has no multi-user account model and must not be exposed on a LAN. A nonstandard port is not authentication. Windows signing/SmartScreen, actual picker behavior, runtime prerequisites and OS focus behavior require real Windows validation.

See [validation](VALIDATION.md), [architecture](ARCHITECTURE.md) and [desktop checklist](DESKTOP.md).

## Enterprise configuration boundary

Strict schema/version/revision checks, exact-byte recovery backups and atomic writes protect settings. Images are decoded with Pillow, pixel/size/frame checked, stripped of metadata and reencoded; SVG is rejected. Missing logo assets fall back safely. Configuration exports default to redacted content; CSV paths/records and capabilities are always excluded. Private export is explicit. Imported packages cannot select a new local CSV path. Settings/backups/logos remain private filesystem data, not encrypted secrets storage.

Regex classification has per-match and total deadlines; parser size/row/identifier limits and bounded workers reduce resource exhaustion. Reserved object-property IDs are rejected, and frontend keyed maps guard inherited properties. Conflicting classification is visible rather than silently assigned. No telemetry, external fonts or service-worker data cache is introduced.

The historical privacy review found organization logo binaries in reachable history. Current files/distribution inputs are cleaned, but history is unchanged. See PRIVACY.md; a current-tree audit cannot erase past exposure.

## UX and theme configuration 1.2

The startup WebView uses an in-memory, product-owned document with an embedded image and authored inline status logic. It enables no remote resources or file URL access; the HTTP application retains its strict bundled-script CSP. The service is started off the GUI thread and its owned instance identity is checked before navigating. Native Close, Open logs and Export diagnostics actions require the same per-launch capability. Diagnostic exports use an explicit allowlist and exclude local paths, SAP records, logs, organization identity and credentials.

Theme colors accept only six-digit HEX; both palettes require AA primary-text contrast against their canvas and card surfaces. Foreground/focus/status tokens derive consistently. Configuration limits and atomic write/revision safeguards remain intact. Theme colors and custom preset names are included in both portable export modes; review names before sharing. No formal security scan or real Windows 1.2 runtime validation is claimed by these source/test checks.
