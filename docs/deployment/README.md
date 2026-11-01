# SAP Lens deployment

SAP Lens uses one React production build and one FastAPI application. Desktop
starts that application in the existing WebView2 lifecycle. `backend/server.py`
starts it headlessly using one Uvicorn worker, serving frontend and `/api` on the
same origin. It does not import WebView2. No SAP interpretation changes are made.

## Choose a target

| Target | Packaging / runtime | Build | Install, configuration and troubleshooting |
| --- | --- | --- | --- |
| Windows Desktop | Windows Desktop x64 / EXE + WebView2 | [Build](BUILD.md) | [Desktop guide](WINDOWS_DESKTOP.md) |
| Windows Server | Windows Service x64 / WinSW + SCM | [Build](BUILD.md) | [Service guide](WINDOWS_SERVICE.md) |
| Linux Docker | Linux Docker amd64 / container | [Build](BUILD.md) | [Docker guide](LINUX_DOCKER.md) |
| Linux Native | Linux Native x64 / Python 3.12 + systemd or manual process | [Build](BUILD.md) | [Native guide](LINUX_NATIVE.md) |

Start with the **[central build guide](BUILD.md)** to select an operating system and package (or all),
choose a version and obtain artifacts from Actions or local builds. Installation
machines do not need Node.js or React compilation. Desktop/service contain their
Python runtime; Linux Native requires Python 3.12 and system libraries.
Linux client support is browser-based, not a standalone GUI.

Read [security](SECURITY.md) before remote access. Application preferences and
recovery live in [Configuration](../getting-started/CONFIGURATION.md); server hosting
variables are defined below. [Releases](RELEASES.md) separates deployment publication
from legacy Windows release allocation. [Code signing](CODE_SIGNING.md) remains a
readiness guide, not an enabled build feature.

## Validation status

| Target | Implemented checks | Recorded execution / acceptance boundary |
| --- | --- | --- |
| Desktop | Canonical PE/resources/privacy/checksum, EXE and installer smoke definitions | Native installer compilation/SCM-independent desktop and WebView2 acceptance not executed in the recorded Linux environment |
| Windows Service | Headless runtime, pinned WinSW, service install/start/health/stop/uninstall and lifecycle smoke definitions | Native Windows/SCM, reboot/recovery and UNC acceptance pending |
| Docker | Offline image packaging, container health/authentication/persistence and lifecycle checks | Local Linux container integration recorded; no new CI build or current-source production image is certified by this documentation migration |
| Linux Native | Offline wheelhouse, extraction/install/start/persistence/upgrade/uninstall checks | Linux user-mode integration recorded; real systemd boot/recovery and target OS acceptance pending |

See [lifecycle evidence](../archive/validation/INSTALLATION_LIFECYCLE_VALIDATION.md),
[packaging evidence](../archive/validation/PACKAGING_VALIDATION.md) and
[local build evidence](../archive/validation/LOCAL_BUILD_VALIDATION.md). Packaging
implemented, package built, CI passed, runtime smoke-tested, native acceptance and
production readiness are separate claims. Check the actual source SHA/run before
distributing a package; successful historical tests do not certify a newer commit.

## Configuration ownership

Server environment selects hosting/security and storage; application settings
continue to own imports, module preferences, review decisions, saved filters and
branding. Server mode is explicit in its entry point. Desktop defaults are unchanged.
`deploy/server.env.example` is a native configuration template. The program does
not implicitly load it: systemd, WinSW or the invoking shell supplies environment.

| Variable | Default / meaning |
| --- | --- |
| `SAP_LENS_DEPLOYMENT_MODE` | `desktop`; server entry point explicitly sets `server` |
| `SAP_LENS_HOST` | `127.0.0.1`; numeric bind IP, no automatic port fallback |
| `SAP_LENS_PORT` | `18743` |
| `SAP_LENS_DATA_DIR` | ProgramData/SAP Lens Server or XDG data home/sap-lens-server |
| `SAP_LENS_SOURCE_DIR` | Data directory/sources; absolute permitted CSV root |
| `SAP_LENS_PUBLIC_ORIGIN` | `http://127.0.0.1:18743`; exact browser origin, no path/trailing slash |
| `SAP_LENS_ALLOWED_HOSTS` | Public origin hostname; comma-separated exact hostnames without ports |
| `SAP_LENS_AUTH` | `local`, `basic` or `proxy`; see security guide |
| `SAP_LENS_AUTH_SECRET_FILE` | Required private file for basic/proxy, never sent to browser settings |
| `SAP_LENS_AUTH_USER` | `saplens`, shared Basic username |
| `SAP_LENS_AUTH_SECRET_GROUP_READ` | `1` accepts a group-readable (0640) secret whose group the service account belongs to; default requires owner-only |
| `SAP_LENS_AUTH_MAX_FAILURES` | `5` (3 to 50) failed Basic sign-ins per client before a lock-out |
| `SAP_LENS_AUTH_LOCKOUT_SECONDS` | `60` (10 to 3600) first lock-out; doubles up to 15 minutes |
| `SAP_LENS_TRUSTED_PROXIES` | Explicit peer CIDRs required in proxy mode; no `/0` |
| `SAP_LENS_LOG_LEVEL` | `info`, also `warning`/`error` |

Use absolute data/source paths, separate from application files. Do not set a
conflicting `SAP_LENS_CONFIG_DIR`; server uses its data directory. A process-held
OS lock and deployment marker prevent concurrent writers and desktop/server
sharing. **One process/worker per data store**, no horizontal replicas/shared NFS
storage. Use independent data directories and ports for separate installations.
Use `backend/server.py`, not a raw `uvicorn main:app` command: the supported entry
point owns the storage lease and listener lifecycle.

## CSV sources and browsers

Settings → Data Sources retains the existing validate, preview and explicit
confirmation workflow. In server mode a CSV upload control stages a private file
on the server. Uploading alone does not activate data. Role/user sources become
Static; Employee Directory becomes Static on confirmed import. Existing validated
data stays active on failed upload, preview or replacement. Uploaded filenames
cannot select a destination. Upload limits: 128 MiB roles/users, 50 MiB employees.
Unreferenced staging files are pruned; active configured files are preserved.

Static sources retain durable snapshots and are not re-read by Global Refresh.
Dynamic sources reference server-visible files beneath `SAP_LENS_SOURCE_DIR` and
are re-read on Global Refresh. Full validated replacement removes stale records;
failure preserves the last valid dataset and produces existing change/error reports.
No scheduled synchronization is introduced. A browser cannot configure its local
file as a dynamic server path. For Docker use container paths; for Windows Service
use local absolute paths or UNC, never mapped drives. Symlinks escaping the source
root are rejected. CSV imports remain optional for core application startup.

Browser exports download locally; server mode never invokes a desktop save dialog.
Native desktop file/save operations are retained. Server-side arbitrary image-path
preview is disabled; validated portable branding configuration remains supported.

## Operations, health and diagnostics

`GET /health/live` reports process availability. `/health/ready` returns 503 during
dataset loading and 200 when requests can be served. Missing optional CSVs do not
make a running service unhealthy. These two endpoints expose no dataset details
and require no credentials. All other server routes, including `/health`, frontend,
configuration and diagnostics, require the configured access boundary.

Logs use stdout/stderr, no access log with usernames/query strings, and redacted
unexpected-error categories. Windows wrapper logs rotate; SCM/wrapper events are
available through Event Viewer. Linux uses Docker logs or journald. Diagnostics
shows platform/deployment mode; server diagnostics uses the redacted snapshot.
Existing diagnostic export omits personal records and private paths.

Stop gracefully before filesystem backup. Back up the **whole data directory**,
including settings, snapshots, source metadata, refresh history, saved filters,
review state and custom branding. Keep authentication secrets separately. Restore
to a stopped instance with correct service ownership; do not merge individual
snapshot files. Keep directory markers when restoring to the same deployment mode.
Never share a live store between desktop and server.

These deployments provide shared internal administrator access, not per-user
permissions. Review [security limitations](SECURITY.md) before real data.
Native Windows/SCM/WebView2, UNC and non-Chromium mobile validation require their
actual target environments; Linux automated tests are not substitutes.
