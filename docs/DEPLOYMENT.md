# SAP Lens deployment

SAP Lens uses one React production build and one FastAPI application. Desktop
starts that application in the existing WebView2 lifecycle. `backend/server.py`
starts it headlessly using one Uvicorn worker, serving frontend and `/api` on the
same origin. It does not import WebView2. No SAP interpretation changes are made.

| Mode | Host | Interface | Mutable storage |
| --- | --- | --- | --- |
| Windows Desktop | Existing EXE | WebView2, native dialogs | Existing per-user SAP Lens directory |
| Windows Server | WinSW + headless onedir EXE | Browser | Separate ProgramData SAP Lens Server directory |
| Linux Docker | Compose container | Browser | Named `/data` volume |
| Linux native/client | Python, optional systemd | Browser | Explicit directory or XDG data home/sap-lens-server |

For downloadable artifacts, manual platform selection and Build All, start with
[deployment packages](DEPLOYMENT_PACKAGES.md).

Start with [security](DEPLOYMENT_SECURITY.md), then choose
[Windows Server](DEPLOYMENT_WINDOWS_SERVER.md), [Docker](DEPLOYMENT_LINUX_DOCKER.md)
or [Linux native](DEPLOYMENT_LINUX_NATIVE.md). Existing desktop builds remain
covered by [LOCAL_WINDOWS_BUILD.md](LOCAL_WINDOWS_BUILD.md).

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
permissions. Review [security limitations](DEPLOYMENT_SECURITY.md) before real data.
Native Windows/SCM/WebView2, UNC and non-Chromium mobile validation require their
actual target environments; Linux automated tests are not substitutes.
