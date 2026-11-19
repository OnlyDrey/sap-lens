# Desktop and Server: builds, run commands and packaging assessment

Nothing here changes the production Desktop launcher, installers, services, workflows or release artifacts. All output goes to isolated
directories outside the repository (`artifacts/`, `bin/`, `obj/`, `out/` are ignored in `backend/.gitignore`).

## Status

| Target | Built | Ran | Evidence |
| --- | --- | --- | --- |
| Server, linux-x64, self-contained | Yes | Yes: health, readiness, imports, all endpoints, 15-client load, graceful and crash shutdown | [M], [T] |
| Server, win-x64, self-contained | Yes (Linux and the Windows 11 VM) | Not yet run as a service | Publish PASS on Windows [W] |
| Desktop, win-x64, self-contained single file (WinForms + WebView2) | Yes (Linux and the Windows 11 VM) | Launched on Windows 11 before the UI fix: window, WebView2 and loopback API (401 without token) worked, `GET /` returned 404 [W]. Fixed build **not yet verified on Windows** | [W], [U] |

[W] = reported from the clean Windows 11 VM by the person who ran it (evidence files are not in the repository).

## Windows finding: Desktop window showed no page (`GET /` 404)

Root cause [C, confirmed by the Windows symptoms]: the host only mapped static files when `<exe dir>\frontend\index.html` existed, and nothing in
the build produced that folder; the earlier instructions relied on a manual `cp` after publishing. Without it, no endpoint matched `/` and the
window received 404, while `/api` (401) and WebView2 worked. Copying the v1 React build would not have helped either: it calls the v1 routes
(`/api/roles`, `/api/access`, ...) and keeps a token in page script, neither of which exists in the `/api/v1` design.

Fix:

1. The UI is **embedded in `SapLens.Api.dll`** (`ManifestEmbeddedFileProvider`). Every host serves it regardless of working directory,
   publish layout or single-file bundling; nothing is copied after publishing. (First a small prototype UI; since Phase 1 the production React
   UI from `frontend/`, see [UI_INTEGRATION.md](../architecture/UI_INTEGRATION.md).)
2. A build without the UI fails at startup with a clear message instead of serving 404.
3. The Desktop navigates only after `StartupProbe` confirmed over the real listener that `/health/ready` is 200 **and** `/` serves the UI;
   otherwise it shows the reason and the log path and exits with code 2.
4. Security headers on every response: CSP (`script-src 'self'`, no inline script), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: same-origin` (not `no-referrer`: Chromium then sends `Origin: null` on the sign-in form post, which the origin check rejects; found by the browser check below).



## Server

```bash
cd backend
dotnet publish src/SapLens.Api -c Release -r linux-x64 --self-contained true -o <out>/server-linux-x64   # folder publish
dotnet publish src/SapLens.Api -c Release -r win-x64 -o <out>/server   # single file: SapLens.Api.exe + e_sqlite3.dll (settings in the project)
# run (no .NET or Python needed on the host)
SAP_LENS_TOKEN=<at least 32 chars> <out>/server-linux-x64/SapLens.Api --data-dir /var/lib/saplens-v2 --port 18790 [--no-worker]
```

- **Options**: `SapLens.Api --help`; full reference in [SERVER_NETWORK_ACCESS.md](SERVER_NETWORK_ACCESS.md#2-configuration-reference); Windows
  VM runbook and test launcher in [WINDOWS_TEST_VM.md](WINDOWS_TEST_VM.md).
- **Data directory**: `--data-dir` or `SAP_LENS_DATA_DIR` (required, no default); must be absolute and local (UNC, `//host/share` and network drives refused).
- **Token**: `SAP_LENS_TOKEN`, otherwise generated once into `<data>/api-token` (mode 0600 on Linux; on Windows it inherits the data
  directory ACL, which an installer must restrict to the service account [U]). Every `/api` request needs `X-SAP-Lens-Token`.
- **Binding**: `127.0.0.1` by default. Access from other devices only with `--network`, one private LAN address, HTTPS with a validated
  certificate and explicit `--allowed-hosts`; everything else is refused at startup. See [SERVER_NETWORK_ACCESS.md](SERVER_NETWORK_ACCESS.md).
- **UI**: `http://127.0.0.1:<port>/` serves the React UI. By default (`--auth accounts`) people sign in with individual v1-compatible
  accounts and roles; the first administrator is activated with a one-time code from `SapLens.Cli accounts-code --data <data-dir>`
  ([details](SERVER_NETWORK_ACCESS.md#accounts-mode-default)). API clients keep using the access-token header. `--auth shared-token`
  keeps the earlier single-secret sign-in through `/login.html` for isolated tests.
- **Health**: `/health/live` (process up), `/health/ready` (database initialized, migrated, integrity-checked); `503` with the reason
  otherwise. **OpenAPI**: `/openapi/v1.json`.
- **Logging**: JSON lines on stdout with UTC timestamps, scopes (correlation id, job id, attempt). systemd/journald or the Windows service
  wrapper captures them. A rolling file sink is not implemented.
- **Shutdown**: SIGTERM / service stop. Measured 164 ms with data loaded; a running import is handed back (status Queued, attempt not
  counted, staging discarded) and resumes on the next start [M]. After a crash (SIGKILL) the job is recovered when its 30 s lease expires,
  staging is discarded and the import completes exactly once (35.7 s after restart in the test) [M].
- **Service hosting**: the same executable runs as a Windows service (`AddWindowsService`, file log in `<data-dir>\logs`) and as a systemd
  `Type=notify` service (`AddSystemd`); both are no-ops in a console. Deployment commands: [SERVER_NETWORK_ACCESS.md](SERVER_NETWORK_ACCESS.md#5-deployment).
  Not yet run as a Windows service [U].

## Desktop

```bash
dotnet publish src/SapLens.Desktop -c Release -o <out>/desktop   # win-x64, self-contained, single file: set in the project
```

The package is `SapLens.exe` (plus `.pdb` files that can be deleted; the release scripts move them to `symbols\desktop`). No `frontend` or `wwwroot` folder exists or is needed.
Arguments: `--data-dir <absolute path>` (default `%LOCALAPPDATA%\SAP Lens Desktop\data`) and `--self-check` (start, probe, log, exit
without a window: exit code 0 ready, 2 start or readiness failure, 1 another instance running).

Lifecycle as implemented (`Program.cs`, `MainWindow.cs`) [C]:

1. Single instance per Windows session (named mutex).
2. Private data directory `%LOCALAPPDATA%\SAP Lens Desktop\data`, separate from v1 (`%LOCALAPPDATA%\SAP Lens`, never used). A folder of the earlier
   prototype builds, `%LOCALAPPDATA%\SAP Lens 2 Prototype`, is kept in place and used as long as `SAP Lens Desktop` does not exist; nothing is moved
   or renamed (`DesktopLocation`). Single-instance mutex `Local\SapLensDotnetDesktop`, or `Local\SapLens2Prototype` with the earlier folder.
3. Core starts in-process on `127.0.0.1:0`; a fresh 256-bit token per run.
4. The window is created only after `StartupProbe` confirmed `/health/ready` = 200 and the UI at `/` (30 s limit); otherwise the host is
   stopped, a message with the reason and the log path is shown, exit code 2.
4a. Log file `%LOCALAPPDATA%\SAP Lens Desktop\logs\desktop-YYYYMMDD.log` (startup, readiness, WebView2 version, navigation and
   browser-process failures, shutdown). The token is never logged (tested).
5. WebView2 profile in `%LOCALAPPDATA%\SAP Lens Desktop\webview2`; DevTools and default context menus off; navigation confined to the
   loopback origin; new windows blocked.
6. The token is added to `/api` requests in `WebResourceRequested` by the host. Page script never sees it, which also removes the v1
   finding F1 (capability passed through the first page load).
7. Navigation failures (`NavigationCompleted` not successful or HTTP status other than 200) and WebView2 browser-process exits are logged
   and shown with the log path.
8. Closing the window stops the host gracefully (job handed back, connections closed, 15 s limit) before the process exits; WebView2
   child processes end with the control.

Prerequisites: Microsoft Edge WebView2 Runtime (present on supported Windows 10/11; missing runtime shows a message). No Python and no
system-wide .NET.

## Packaging assessment

| Criterion | Windows Desktop | Windows Server | Linux Server |
| --- | --- | --- | --- |
| Build complexity | One `dotnet publish`; cross-compiles from Linux. Low. | Same. Low. | Same. Low. |
| Runtime dependencies | WebView2 Runtime; ICU from Windows 10 1903 or later | ICU from Windows Server 2019 or later | glibc and ICU (`libicu`, required) |
| Size | 154 MB single exe (UI embedded) | 115 MB, 356 files | 114 MB, 353 files |
| Startup reliability | Not measured on Windows [U]. Single-file extracts native libraries to a temp folder on first run unless `IncludeNativeLibrariesForSelfExtract` is avoided; a one-dir layout avoids extraction entirely | Not measured [U] | Cold start to ready 1.3 to 1.8 s, warm 1.2 to 1.4 s [M] |
| Install / upgrade | Copy or MSIX/MSI (not built); data directory and schema migrations are independent of the binary, with a protected migration backup | Same; service registration via `UseWindowsService` + `sc.exe`/installer | Package + systemd unit |
| Logging | Console not visible in a WinExe; needs a file sink | Event Log or file sink | journald via stdout |
| AV / App Control | **Unsigned binaries face the same App Control enforcement v1 and the Go experiment hit.** .NET does not change this. Signing all shipped PE files and an IT publisher rule remain mandatory. Single-file reduces the number of PE files to sign but self-extraction of native libraries can trigger AV heuristics; one-dir is the safer default under App Control | Same | n/a |
| Signing | One exe (single-file) or every PE (one-dir) with Authenticode | Every PE | Optional (package signing) |
| Runtime lifecycle | Self-contained: the runtime is patched only by shipping a new build. .NET 10 LTS support ends November 2028; plan monthly servicing rebuilds | Same | Same |

## Backups, keys and SAP Lens 1 data

- Application backups need a host backup key outside the data directory: `SapLens.Api --backup-key create <file> --data-dir <dir>`, then
  `--backup-key export <file>` for the escrowed recovery copy, verified in Settings, Backups. Automatic backups stay off until it is verified.
- SAP Lens 1 data (a `.slbak`, `.tar.gz` or data directory) moves with `--migrate-v1`; the step-by-step Windows procedure is
  [V1_MIGRATION.md](../migration/V1_MIGRATION.md).

## Unicode and ICU (runtime requirement)

SAP Lens builds with `InvariantGlobalization=false`: Unicode normalization (NFKC, used for Employee Directory and Functional Group text) and IANA time
zones need ICU at runtime.

- **Windows:** Windows 10 1903, Windows Server 2019 and later include ICU (`icu.dll`); nothing to install.
- **Linux:** install the distribution's ICU package (`libicu` on Debian/Ubuntu, for example `libicu74`; `libicu` on RHEL-compatible systems).
- **Startup check:** the server and the Desktop stop with `startup refused` and an explanation when ICU is missing or `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT`
  is set, instead of running with different text handling. The startup log names the ICU version.

Case mapping does not depend on the installed ICU version: `str.casefold()`, `str.upper()` and `str.lower()` (full mappings, for example `ß` to `SS`) use
tables generated from Python 3.12 (Unicode 15.0.0) by `backend/tools/casefold_table.py`, so Norwegian and international names fold
exactly as in SAP Lens 1. All sorting is ordinal (code point order, as in SAP Lens 1), never culture-dependent.

## Native AOT (evaluation only, not built)

Not viable for this design today: EF Core does not support AOT for runtime model building and migrations, reflection-based
System.Text.Json would need source generators for every contract, and WinForms is not AOT-compatible. Expected benefit is smaller size and
faster cold start (the current cold start is already about 1.3 s). Revisit only for the Server if size or start time become requirements;
it would mean Dapper or hand-written SQL instead of EF Core.

## What has to happen on Windows before any GO

1. Run the Server package as a Windows service (start, stop, restart, crash recovery, reboot), with the data directory ACL.
2. Run the Desktop exe on a managed machine: WebView2 present/missing, first run, single instance, close during an import, App Control
   with a signed build.
3. Measure startup, memory and shutdown on Windows with the same harness.

## Windows verification

Assumes the .NET 10 SDK and Git on the VM, the repository at `C:\src\sap-lens`, and output under `C:\sap-lens` (outside the repository).
Commands are for an interactive prompt; in a `.bat` file double every `%` in the `curl -w` formats.

### A. Over SSH (CMD): build, tests, publish, headless Desktop self-check, Server

```bat
cd /d C:\src\sap-lens
git fetch origin experiment/dotnet-backend
git checkout experiment/dotnet-backend
git pull --ff-only
cd backend

dotnet build SapLens.slnx -c Release
dotnet test tests\SapLens.Tests -c Release --no-build --filter "Category!=Publish"
dotnet test tests\SapLens.Tests -c Release --no-build --filter "Category=Publish"

rmdir /s /q C:\sap-lens 2>NUL
dotnet publish src\SapLens.Desktop -c Release -o C:\sap-lens\desktop
dotnet publish src\SapLens.Api -c Release -r win-x64 --self-contained true -o C:\sap-lens\server
dir C:\sap-lens\desktop
if exist C:\sap-lens\desktop\frontend (echo UNEXPECTED frontend folder) else (echo OK no loose frontend)

REM Desktop without a window, from an unrelated working directory, with its own data directory
cd /d %TEMP%
start "" /wait C:\sap-lens\desktop\SapLens.exe --self-check --data-dir C:\sap-lens\desktop-check
echo self-check exit code %ERRORLEVEL%
dir C:\sap-lens\desktop-check
type "%LOCALAPPDATA%\SAP Lens Desktop\logs\self-check-*.log"

REM Server from an unrelated working directory; it generates its token file on first start
start "" /b C:\sap-lens\server\SapLens.Api.exe --data-dir C:\sap-lens\server-data --port 18790 > C:\sap-lens\server.log 2>&1
timeout /t 5 /nobreak >NUL
curl -s -o NUL -w "ready %{http_code}\n" http://127.0.0.1:18790/health/ready
curl -s http://127.0.0.1:18790/ | findstr /c:"prototype-ui-v1"
curl -s -o NUL -w "app.js %{http_code} %{content_type}\n" http://127.0.0.1:18790/app.js
curl -s -o NUL -w "app.css %{http_code} %{content_type}\n" http://127.0.0.1:18790/app.css
curl -s -o NUL -w "api without token %{http_code}\n" http://127.0.0.1:18790/api/v1/roles
set /p TOKEN=<C:\sap-lens\server-data\api-token
curl -s -H "X-SAP-Lens-Token: %TOKEN%" http://127.0.0.1:18790/api/v1/session
curl -s -H "X-SAP-Lens-Token: %TOKEN%" http://127.0.0.1:18790/api/v1/admin/integrity
set TOKEN=
dir C:\sap-lens\server-data
taskkill /im SapLens.Api.exe /f
tasklist /fi "imagename eq SapLens.Api.exe"
```

Expected: tests pass (the Linux-only publish test returns immediately on Windows); `self-check exit code 0`; `sap-lens-v2.sqlite3` in both
data directories; `ready 200`; the marker line printed; `app.js 200 text/javascript`; `app.css 200 text/css`; `api without token 401`;
session JSON with `"mode":"server"`; `"database_ok":true`. `taskkill /f` is a hard stop: graceful Windows shutdown is verified only once the
Server runs as a Windows service (not built).

### B. Interactive desktop session (PowerShell 5.1 or 7): window, WebView2, import, shutdown

```powershell
$csv = Join-Path $env:TEMP 'sap-lens-csv'; New-Item -ItemType Directory -Force $csv | Out-Null
$roles = @('FUNCTION_KEY;AGR_NAME;TEXT;CHILD_AGR;CHILD_AGR_TEXT;PARENT_AGR;Effective_Role;TCODE;TTEXT') +
  (0..29 | ForEach-Object { 'FI;ZC:FI:ROLE_{0:D4};Synthetic role {0};;;;;T{1:D3};Transaction {1}' -f $_, ($_ % 7) })
$users = @('USERNAME;ROLE_NAME;USER_GROUP;FIRST_NAME;LAST_NAME;EMAIL;USER_VALID_FROM;USER_VALID_TO;ROLE_VALID_FROM;ROLE_VALID_TO;USER_LOCKED;USER_TYPE') +
  (0..19 | ForEach-Object { 'USER{0:D4};ZC:FI:ROLE_{0:D4};GRP_FIN;First{0};Last{0};;;;;;;A' -f $_ })
Set-Content -Path (Join-Path $csv 'roles.csv') -Value $roles -Encoding UTF8
Set-Content -Path (Join-Path $csv 'users.csv') -Value $users -Encoding UTF8

Start-Process -FilePath 'C:\sap-lens\desktop\SapLens.exe' -WorkingDirectory $env:TEMP
# In the window: status line shows "<user> · desktop · No data imported yet"; Data tab: import roles.csv as Roles, then users.csv as Users;
# Role Lookup: search ZC:FI*; User Access: search USER; Compare Users: USER0001 and USER0002 with validity "all". Then close the window.

$app = Join-Path $env:LOCALAPPDATA 'SAP Lens Desktop'
Get-ChildItem (Join-Path $app 'data')
Get-ChildItem (Join-Path $app 'logs') | Sort-Object LastWriteTime | Select-Object -Last 1 | Get-Content -Tail 40
# After closing the window, both must return nothing:
Get-Process SapLens -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='msedgewebview2.exe'" | Where-Object { $_.CommandLine -like '*SAP Lens Desktop*' }
```

### Acceptance checklist (Windows)

| # | Check | Pass when | Status |
| --- | --- | --- | --- |
| 1 | Package completeness | `C:\sap-lens\desktop` holds `SapLens.exe` and no `frontend`/`wwwroot`; publish tests pass | Pending |
| 2 | Headless start | `--self-check` exit code 0 from `%TEMP%`; log says "Self-check passed" | Pending |
| 3 | Desktop launch | Window opens within a few seconds; one instance only (second start says already running) | Pending |
| 4 | WebView2 rendering | Prototype UI visible (header, tabs, status line), not a 404 or blank page | Pending |
| 5 | Local API connectivity | Status line shows the Windows user and `desktop`; imports and lookups return data; no sign-in prompt | Pending |
| 6 | SQLite initialization | `sap-lens-v2.sqlite3` (plus `-wal`/`-shm` while running) in the data directory | Pending |
| 7 | Clean shutdown | After closing: no `SapLens` process, no `msedgewebview2` with the prototype profile; log ends with "Desktop stopped" | Pending |
| 8 | Server package | Section A Server results as expected, from `%TEMP%` | Pending |

Windows Desktop acceptance is **not complete** until rows 1 to 8 pass on the VM with the fixed build.
