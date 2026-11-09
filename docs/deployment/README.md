# SAP Lens deployment

SAP Lens uses one React production build and one FastAPI application. Desktop
starts that application in the existing WebView2 lifecycle. `backend/server.py`
starts it headlessly using one Uvicorn worker, serving frontend and `/api` on the
same origin. It does not import WebView2. No SAP interpretation changes are made.

## Choose a target

| Target | Packaging / runtime | Build | Install, configuration and troubleshooting |
| --- | --- | --- | --- |
| Windows Desktop | Windows Desktop x64 / EXE + WebView2 | [Build](../BUILD.md) | [Desktop guide](WINDOWS_DESKTOP.md) |
| Windows Server | Windows Service x64 / WinSW + SCM | [Build](../BUILD.md) | [Service guide](WINDOWS_SERVICE.md) |
| Linux Docker | Linux Docker amd64 / container | [Build](../BUILD.md) | [Docker guide](LINUX_DOCKER.md) |
| Linux Native | Linux Native x64 / Python 3.12 + systemd or manual process | [Build](../BUILD.md) | [Native guide](LINUX_NATIVE.md) |

Start with the **[central build guide](../BUILD.md)** to select an operating system and package (or all),
choose a version and obtain artifacts from Actions or local builds. Installation
machines do not need Node.js or React compilation. Desktop/service contain their
Python runtime; Linux Native requires Python 3.12 and system libraries.
Linux client support is browser-based, not a standalone GUI.

How validation relates to building and publishing (Fast Validation, Build & Release, manual Full Regression) is in [CI/CD](CI_CD.md).

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

Windows regression follow-up (backend run 1,724 tests, 5 failures, 3 errors, 46 skipped on native Windows, Python 3.12.10): path-separator assumptions in two backup tests, symlink creation without privilege (now an explicit skip, coverage gap on unprivileged Windows), a Linux-shell interpreter stub in a probe test, tie-sensitive timestamp comparisons (Functional Group reconfirmation, SoD reopened classification) and the Windows secret-file ACL check are fixed and covered by tests that run on Linux; the native Windows re-run is pending.

### Validation matrix (cross-platform stabilization)

| Environment | Verified | Not verified |
| --- | --- | --- |
| Linux native (Python 3.12, Node 24.22.2, Playwright 1.64.1 with its pinned Chromium 1248 = Chrome for Testing 156.0.8078.4) | FULL (9 Nov 2026, `run-tests.py full --browser-jobs 3`, one uninterrupted run, 15 min 45 s): backend 1,786 tests OK, 2 skipped (build-only PyInstaller / PE-resource tests); browser 859 OK with 3 processes; build, docs, workflow contracts, Lucide, ruff, ESLint, `pip check`, frontend unit, `npm audit`, PowerShell checks; `pip-audit` (separate audit environment) no known vulnerabilities. Runner failure paths with real Playwright: a failing test exits 1 and keeps artifacts, a busy port exits 2, no scratch directories or processes left | actionlint |
| PowerShell 7.6.9 on Linux | Parse of every `.ps1`, parameter binding, argument forwarding, paths with spaces, exit codes, bounded hung child, read-only `prerequisites --check-only`, real `--repair` | PSScriptAnalyzer (PowerShell Gallery blocked) |
| PowerShell 5.1, static | `check-powershell-compat.ps1`: 0 errors, 9 warnings (encoding defaults/BOM, redirection, `Start-Process` quoting) | Any 5.1 execution; static analysis cannot prove runtime behavior |
| Simulated Windows | DACL policy, secret lifecycle, tie-sensitive clocks, symlink skip, `.cmd` probe stub, `nt` branches with mocked APIs | The real APIs these mock |
| Native Windows | Last known: backend 1,724 tests, 5 failures, 3 errors, 46 skipped (all eight analysed and fixed) | **Pending:** backend re-run, Playwright (887 passed, 18 failed, 4 skipped; failing names not recovered), ACL via `GetNamedSecurityInfoW`/`icacls`/service SID, `RepairSecret`, `py -3.12` with a newer default Python, `npm.cmd`, PowerShell 5.1 execution, installer/SCM acceptance |

Supported PowerShell: Windows PowerShell 5.1 (production) and PowerShell 7 (development and Linux validation). Playwright investigation: the repository and local logs contain only the counts of the Windows run, not test names or errors, so no fixes were made on speculation; send the report or failing names for a targeted investigation.

Not executable in the Linux container used for the last validation, and therefore unverified for this version: native Windows process handling (the browser-test parent watch in `scripts/testing/serve-browser-tests.py` is skipped on Windows because `getppid` does not change there, and `cleanup_on_signals` only maps the signals Windows has), WebView2, the Windows service control manager and UNC paths, and a real systemd boot, restart-on-failure and reboot recovery. The SQLite store, retention, fast paths and revision tokens are platform independent Python and are covered by the Linux unit and browser suites; the Windows packaging and desktop lifecycle checks run in `.github/workflows/build-windows.yml` only on an authorized run.

Packaging
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

Settings → **Backup & Restore** provides [application-data backup and restart restore](BACKUP_RESTORE.md), including Desktop-to-server transfer. Host maintenance remains available independently.

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
