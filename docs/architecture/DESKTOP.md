# Windows Desktop 1.2

## Runtime scope

For prerequisites, installation, upgrades and recovery use [Windows Desktop](../deployment/WINDOWS_DESKTOP.md).
For local/Actions commands use [Build](../BUILD.md). This document owns
WebView2, listener, native-bridge and shutdown internals, plus native QA boundaries.
The legacy portable ZIP and the multi-platform installer bundle are distinct
formats; their exact contents are specified by their canonical packagers.

A one-file EXE contains Python, API, compiled frontend and product resources. It
extracts to a temporary directory at launch. A second launch activates the current
window; Windows can restrict foreground focus. Closing the window owns shutdown.

The backend is a daemon thread inside the application process, not a separate child process. Its listener is reserved before startup and bound exclusively to `127.0.0.1`. Port `18743` is preferred; if another process owns it, the app reserves a new OS-selected port without contacting or killing that process. Each launch generates a new capability for API requests. WebView2 receives it in a URL fragment, which is removed and retained in session storage. The native file-picker bridge requires the same capability.

While the desktop process is running, a modern browser on the same PC can open `http://127.0.0.1:18743/` or `http://localhost:18743/` (substitute the selected port if the preferred port was occupied). Both use the same backend, configuration and datasets; no service or second backend is started. Browser exports use downloads rather than native dialogs. The desktop remains the owner: closing it stops browser access too.

A top-level, non-cross-site navigation to the owned root document receives a fresh CSP-nonced, non-cacheable capability handoff into that origin’s session storage. Missing Fetch Metadata, cross-site navigation, frames and resource requests never receive the capability. API reads and writes still require it; exact Host/port, loopback peer and the two explicit origins are enforced. Reload obtains the current launch capability after restarting the application. This is a local process trust boundary, not multi-user authentication; use the separate authenticated headless server for network hosting. Linux HTTP/browser checks do not establish native Windows/WebView2 acceptance.

Shutdown requests graceful Uvicorn termination, bounds the wait, closes the owned socket and releases the Windows instance handle. CSV reads use daemon threads and cancellation checks before committing data/settings. A stalled network share cannot leave an orphan backend process. Only resources owned by this application are shut down.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| WebView2 prerequisite message | Install/enable the Evergreen runtime from Microsoft or contact IT; no service has been started |
| Missing/invalid CSV | Choose an accessible CSV and preview its mapping, encoding and delimiter in Settings |
| Share unavailable | Cancel the pending load and choose an accessible source; the app can close safely if the filesystem stalls |
| Port `18743` occupied | No action is normally needed; the desktop automatically chooses another controlled loopback port |
| Another instance already starting | Wait for its window or switch to it on the taskbar |
| Other startup failure | Use the displayed code and **Log location**, then **Retry startup** when offered. If shutdown is incomplete, close the process fully before restarting; see recovery below. |
| Source-mode development | Activate `.venv`, install desktop requirements and build the frontend, then run `.\.venv\Scripts\pythonw.exe backend\desktop.py` from the repository root |

Settings are stored per user, independently of the EXE. Logs omit source paths, data and launch capabilities. A normal exit removes `runtime.json`. Forced OS termination may leave this non-secret diagnostic file; the next owned launch replaces it. No service worker caches SAP responses.

## Packaging verification boundary

`scripts/build-windows.ps1` remains the canonical one-file PyInstaller compiler.
Deployment packaging wraps its verified portable payload with the per-user Setup
and manifest; it does not implement a second desktop application build. UPX stays
disabled. [CI](../development/CI.md) owns workflow orchestration and
[Build](../BUILD.md) owns user commands.

The packaged smoke test uses isolated synthetic settings and checks PE resources,
GUI subsystem, instance identity, readiness, origin/capability enforcement, visible
window, duplicate/repeated launches, port fallback and owned listener cleanup.
Definitions are not proof of a new successful Windows run.

## Remaining real Windows checks

Linux tests mock the native GUI, registry and mutex APIs; they do not establish Windows acceptance. Even after a successful Windows CI run, validate these user interactions on a clean target PC:

- Explorer launch, application/taskbar icon and no console; normal Windows focus behavior on duplicate launch.
- Real **Browse** dialog: selection, cancel, non-ASCII/spaced paths and permitted UNC shares.
- Local settings persistence across EXE upgrades and reboot; disconnected/slow shares and shutdown during loading.
- Missing-runtime message on a PC without WebView2; organizational signing, SmartScreen, endpoint and filesystem policies.
- Visual layout, comparison interactions, theme toggle and keyboard behavior in WebView2.

See [validation tracker](../validation/README.md) for measured local results versus pending Windows results.

The settings UI also supports native logo selection, portable configuration Save dialogs and opening the per-user configuration folder. Saved organization/theme/profile/logo settings survive upgrades; user assets are never bundled into later builds. Test these dialogs and persistence on actual Windows alongside the CSV picker. Unexpected owned-server death is reported and closes the window; a failed service is not left behind a seemingly working interface.

Version 1.2 introduces a responsive branded startup document, full-window settings, organization-first header and persistent theme colors. See [workspace and themes](APPEARANCE.md). The changed 1.2 launcher and canonical build passed automated Windows GUI/lifecycle/package validation in [run 39469463871](https://github.com/OnlyDrey/sap-lens/actions/runs/39469463871); target-PC/native interaction checks remain pending.

## Requirement ownership

`backend/requirements.txt` contains application/API dependencies. `requirements-desktop.txt` adds the native WebView runtime, `requirements-dev.txt` adds backend tests, and `requirements-build.txt` adds PyInstaller and pinned build pip to desktop runtime dependencies. `scripts/requirements-audit.txt` pins audit tooling for the separate host interpreter. The canonical build script installs build and test requirements into its isolated environment; normal source-mode desktop execution needs only desktop requirements. Node 24 LTS is recommended; the build toolchain accepts Node 24 or 25. User configuration is not a developer/build input.

The canonical build also creates the SHA-256 manifest and runs `scripts/verify-windows-package.py` before delivery. The verifier checks the PE GUI subsystem, checksum, required bundled assets and absence of known private configuration/CSV/log entries. The GitHub workflow uploads the same verified output; it does not maintain a second checksum implementation.


Role Lookup, User Access, Release Roles and legacy configuration compatibility are documented in [User Access](../features/USER_ACCESS.md). See [Filters](../features/FILTERS.md) for filter availability and [Navigation patterns](NAVIGATION.md) for data-source navigation.

## Download integrity and execution failures

Use an entirely successful manual Windows workflow run, then download
**SAP-Lens-Windows-x64**, extract the GitHub ZIP into a writable folder and keep the
EXE and manifest together. No nested ZIP, Python/Node installer, user settings or
CSV export belongs in this artifact. The workflow's upload/download round trip
compares the final artifact to the already verified executable before declaring
success. A failed run may still show an artifact; do not distribute that output.

In PowerShell, from the extracted folder, verify the exact executable bytes:

```powershell
$expected = (Get-Content -Raw ./SAP-Lens.exe.sha256).Trim()
$actual = (Get-FileHash ./SAP-Lens.exe -Algorithm SHA256).Hash.ToLowerInvariant()
if ($expected -cne "$actual  SAP-Lens.exe") { throw 'Checksum mismatch. Do not launch this file.' }
```

Compare the EXE digest with the successful Actions report as well. The GitHub
artifact ZIP digest covers the ZIP, not the extracted EXE, so these two hashes
normally differ. A matching checksum detects corruption/byte mismatch; an unsigned
file and its accompanying manifest do not authenticate a legal publisher.
[Signing readiness](../deployment/CODE_SIGNING.md) describes a future signed release;
current builds remain unsigned.

A browser download failure happens before SAP Lens runs. Record the workflow/commit,
artifact name, expected size/hash, browser error and endpoint-security event without
sharing temporary signed download URLs. Check network/proxy permissions and ask IT
to review the specific file and policy event. A corrupt or incomplete ZIP is an
integrity/download issue: obtain a complete trusted download and recheck hashes.
Do not disable antivirus, SmartScreen, browser protections or organizational policy.

If extraction and checksum verification succeed but launching fails, record the
Windows version, WebView2 availability, displayed error and sanitized application
log. Check profile permissions and endpoint quarantine events with IT. Missing
WebView2 has an explicit prerequisite message; CSV or network-share failures are
handled through Settings. Signing may help establish publisher identity but does
not guarantee downloads, SmartScreen reputation or permission to execute.

## Candidate native desktop QA

The global-navigation candidate requires a **newly packaged** EXE on real Windows.
Linux Chromium and mocked native APIs are useful regressions, not WebView2 or UNC
acceptance. Until this checklist is completed, native release readiness is pending.

After explicit approval, push the reviewed candidate and run one manual
**Build Windows Application**, mode `build`, base version `0.1.0`, packaging
benchmark/cold cache false. This creates a development artifact only: no tag or
GitHub Release. Record commit/run/artifact ID, displayed/full and numeric version,
EXE/ZIP SHA-256, PE/privacy/roundtrip results and first/relaunch/port-conflict smoke
results. Download that exact verified artifact onto a supported Windows x64 PC.
Do not use an older beta EXE to sign off the new UI.

Prepare a disposable synthetic dataset outside the checkout (PowerShell):

```powershell
$qaPath = Join-Path $env:TEMP ('sap-lens-qa-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $qaPath | Out-Null
$csvRows = [System.Collections.Generic.List[string]]::new()
$csvRows.Add('USERNAME,ROLE_NAME,USER_GROUP,USER_VALID_FROM,USER_VALID_TO,ROLE_VALID_FROM,ROLE_VALID_TO,USER_LOCKED')
0..124 | ForEach-Object {
    $qaUser = 'DEMO_{0:D3}' -f $_
    $qaRole = 'ZO:MM:M:PR_REL_ST_G{0:D3}_N6:ALL' -f $_
    $csvRows.Add("$qaUser,$qaRole,GROUP_QA,20000101,99991231,20000101,99991231,0")
    $csvRows.Add("$qaUser,ZC:DEMO:BUSINESS,GROUP_QA,20000101,99991231,20000101,99991231,0")
}
$csvRows | Set-Content -LiteralPath (Join-Path $qaPath 'users.csv') -Encoding utf8
@('FUNCTION_KEY,AGR_NAME,CHILD_AGR,TCODE', 'MM,ZC:DEMO:*,ZS:DEMO,ME23N') |
    Set-Content -LiteralPath (Join-Path $qaPath 'roles.csv') -Encoding utf8
```

Run with isolated QA settings; preserve the tester's existing settings/data.
Record Windows/WebView2 versions, DPI and window dimensions, and pass/fail evidence
for each row. All rows below remain pending until performed on the target PC.

| Area | Native acceptance |
| --- | --- |
| Startup/lifecycle | Explorer launch has no terminal; actual WebView2 window, single instance, clean close/restart and no orphaned listener/process |
| Navbar/routes | All three destinations, active state and Settings work at 1280/800 widths; visited search/sort/page state survives navigation |
| Breadcrumbs | User/release/role details return to the true originating view and restore useful keyboard focus |
| Global Previous/Next | With GROUP_QA, cross users 50→51→50 and release records 100→101; verify global totals of 125, ascending/descending and first/last boundaries |
| Refresh/removal | Remove a QA record from a copy of the CSV, refresh, and verify missing-record explanation, disabled traversal and a valid origin page |
| Combobox | Mouse and Arrow Up/Down/Enter/Escape/Tab; selected value retained on reopen, clear/All, empty search, long options scroll and outside-click close |
| Popup placement | Both themes, normal/narrow window and 100%/150% DPI; anchored panel remains in view and is not clipped by settings/table scrolling |
| Native file picker | Browse selects each independent source, cancel retains its path, spaced/non-ASCII filenames work; no unintended source replacement |
| Import tabs | Draft paths/presets/mappings stay separate; auto detection/preview/retry, invalid file errors and advanced options remain usable |
| Actual UNC | Copy only these synthetic files to an approved readable SMB share; browse/type its UNC paths and load both. Test missing/denied/disconnected share; previous settings/data must remain intact on failure |
| Persistence/themes | Restart the exact EXE; saved sources, formats, module preferences and theme survive, with no console or service dependency on a terminal |

Use an actually available, approved SMB share; a mocked picker or a string such as
`\\DEMO-SERVER\exports\users.csv` is not evidence of network access. No credentials,
production exports or personal user data are required. Record only sanitized
screenshots/results. A CI smoke pass establishes its explicit lifecycle assertions;
it does not establish mouse/keyboard/native-dialog/SMB acceptance in this table.

### Navigation handoff and Back/Forward validation

The desktop starter now uses `window.location.replace(...)` after backend identity
and readiness verification, replacing the temporary startup document rather than
adding it behind the application. The capability remains in the launch fragment
and is removed by the existing frontend session handling; it is never logged.
Browser-rendered startup/handoff tests exercise the actual authored startup HTML.
The Python lifecycle tests mock only the GUI boundary and verify the replacement
script, owned server shutdown and session checks.

The frontend maintains meaningful application history without full page reloads.
A boundary entry represents the first actual app view, not the startup screen.
Back at that boundary returns forward to the first view; all ordinary internal
Back/Forward traversal stays enabled. The boundary is established once per app
entry and survives reload without accumulating entries. This also prevents the
first mouse Back from falling into an empty initial WebView document. Connection
failures retain the current application with a retry banner; CSV loading is
contextual and does not reinitialize the desktop service.

Native Windows acceptance remains pending: verify mouse XButton1/XButton2 and
Alt+Left/Right through lists, details, Settings, comparison and the first app view;
confirm no bootstrap flash, new backend instance, unexpected page reload or
history loop. Also verify native CSV/logo dialogs, real permitted UNC reads,
WebView2 popup positioning and packaged first launch/restart/port-conflict smoke
tests. Linux Chromium and Python GUI mocks are not native WebView2 validation.
No Windows artifact or remote workflow was built for this local UI task.

## Windows tray host

`windows_tray.py` isolates the optional native notification-area adapter and desktop
background policy. It uses standard-library ctypes with explicit pointer-sized
Win32 signatures, a dedicated hidden message window/thread, the existing product
ICO, double-click/menu handling and Explorer recreation. No dependency was added.
The controller does not create servers; it reuses ManagedBackend, WindowsInstance,
StorageLease, the selected origin and authenticated refresh. Session shutdown is
allowed through the existing WinForms host's CloseReason event instead of being
vetoed by ordinary hide-on-close policy. Native behavior remains acceptance-pending.

Config `desktop` defaults all flags off. Its native apply context is isolated to
Windows Desktop; a coroutine lock serializes desktop settings transactions while
CSV validation awaits. Registry/icon changes roll back if the revision/save or CSV
publication fails, including loaders that retain old data without raising. Portable
configuration exports reset desktop preferences and imports preserve local values.
No startup entry is silently registered merely by reading an imported preference.

The existing capability-guarded bridge adds runtime status and a frontend-readiness
handshake. Tray Settings requests remain pending until the React event listener is
ready; no timeout or page reload loses investigation context. Root/API host, origin,
CSP, session capability, loopback binding and selected-port rules remain unchanged.
See the [desktop guide](../deployment/WINDOWS_DESKTOP.md#optional-system-tray-operation)
for user options, startup cleanup and native acceptance criteria.

## Startup investigation (2026-11-04)

The launch path is `desktop.run` → exclusive storage lease → stopped-store
backup/restore recovery → reserved socket → trusted startup HTML → `create_app`
→ owned Uvicorn thread → ASGI lifespan → HTTP identity check → compiled frontend.
Configuration uses versioned JSON recovery/migration. There is no database
connection/migration stage in this launch path; individual persistent stores are
opened by their existing services. Backup/restore recovery must finish under the
lease before any scheduler or data writer starts. CSV restoration is background
work and must not be confused with failure of the HTTP service.

Confirmed gaps at the investigation baseline (`be6e6c6`): one failed HTTP probe
aborts startup; the generic failure hides its stage/exception; file logging starts
after storage recovery; no controlled retry exists. The Windows intermittent
trigger has not been reproduced or established from a user runtime log.

The launcher serves existing `frontend/dist`; it never invokes Node, Vite or a
frontend build. Vite `PLUGIN_TIMINGS` measures the separate build command and is
not evidence of desktop runtime startup latency. No build dependencies or timing
constants were changed during this investigation.

## Readiness, diagnostics and controlled recovery

Readiness requires Uvicorn's ASGI initialization to complete **and** a successful
HTTP `/health` response with `app=sap-lens`, the current attempt's instance identity
and a recognized status. A TCP connection alone is insufficient. The launcher
uses its reserved `127.0.0.1` listener, bypasses network proxies for that loopback
probe and refuses redirects. It never probes, kills or attaches to an unrelated
listener on the preferred port. An occupied preferred port falls back to an
OS-assigned port.

Each HTTP attempt is bounded to 0.5 seconds, with at most 0.1 seconds between
failed probes. Worker termination is checked during polling. The initialization /
readiness budget remains **15 seconds** by default; administrators can explicitly
set `SAP_LENS_DESKTOP_STARTUP_TIMEOUT` to a number from 1 through 180 seconds for a
measured slow machine. Invalid values fail with `INVALID_STARTUP_TIMEOUT`.
This setting does not alter server deployments or the separate WebView loading
budget, and cannot forcibly interrupt blocked OS filesystem calls.

Configuration and stopped-store recovery remain correctness prerequisites.
The scheduler starts once per app lifespan and is cancelled, together with the
initial data-load task, on shutdown or lifespan failure. Background CSV loading
may return `loading` or `needs_configuration`; neither means that the local HTTP
service crashed. The normal frontend shows source progress/errors afterward.
There is no separate SQL initialization/migration stage in this runtime.

Startup logs are written to `config_dir()/sap-lens.log` (2 MB rotation, two
backups), before backup/restore recovery. Normally this is
`%LOCALAPPDATA%/SAP Lens` on Windows and the configured per-user application data
folder on Linux; `SAP_LENS_CONFIG_DIR` selects the supported override. The native
**Log location** action reveals the actual configured location on request. File
logging failure is handled without crashing an otherwise usable runtime; check
permissions if no current log can be written.

Records include UTC timestamp, attempt ID, elapsed milliseconds, stage, host/port,
PID and worker outcome. The backend shares the desktop PID: it is a thread, not a
child process. Traceback records retain exception types and source file/line/
function locations only, excluding exception values, source lines, locals,
capabilities and imported records. Worker outcome is not an OS child exit code.
A stale `runtime.json` is diagnostic only; ownership comes from the instance and
storage leases, never from trusting a saved PID or contacting its recorded port.

| Startup code | Meaning / recovery |
| --- | --- |
| `CONFIGURATION_FAILED` | Configuration could not initialize; inspect the sanitized trace and storage permissions, then retry. |
| `APPLICATION_INIT_FAILED` | An application/loader/scheduler constructor failed; inspect the stage and trace. |
| `BACKEND_EXITED` | The owned worker stopped before or during readiness; inspect initialization events. |
| `INITIALIZATION_TIMEOUT` | ASGI startup exceeded its deadline; investigate initialization before extending the budget. |
| `READINESS_TIMEOUT` | No valid HTTP readiness response arrived within the budget. |
| `UNEXPECTED_SERVICE` | Wrong/malformed response or redirect; no other service is accepted. |
| `ASSETS_MISSING` | Compiled frontend directory is missing; rebuild or reinstall the package. |
| `WINDOW_TIMEOUT` | The startup document did not load; verify WebView2. |

On a recoverable failure, **Retry startup** requests a real native restart attempt;
it does not reload React. The same supervising thread first stops the owned
backend and closes its listener. Only after confirmed shutdown can it reserve a
fresh listener and identity and create one replacement app/scheduler. Duplicate
retry clicks are rejected. Storage recovery is not rerun against live stores.
If a backend thread cannot stop, retry is unavailable: fully exit SAP Lens (tray
**Exit SAP Lens**, rather than just hiding the window) before relaunching. No
remote server-restart endpoint or process-wide termination command was added.

Targeted Linux HTTP and fault-injection tests establish these contracts. They do
**not** establish that the reported intermittent Windows/WebView2 failure is
resolved. Repeated source-mode and packaged EXE launches on the affected Windows
machine, including recovery and explicit tray exit, remain required. Retain the
new attempt diagnostics if the failure recurs. Vite timing findings remain
separate from this runtime validation.

## Session lifecycle and recovery states

One shared state (`frontend/src/lib/sessionState.ts`, written only by the API client, read through `useSession`) tracks the local session:
`connecting` (before the first answer), `connected`, `disconnected` (the service is unreachable; reads retry with the existing bounded
query retries and the notice offers **Retry connection**), `manual` (the backend rejected the capability as `stale_session`),
`reconnecting` and `failed`. A stale session is never cleared by a later success: only an explicit **Reconnect session** (a reload
through the guarded root document) leaves `manual`. While the session is `manual`, `reconnecting` or `failed`, the client refuses
every `/api` request locally, so a stale page cannot produce a request storm and no write is sent, queued or replayed.

Presentation: one compact `SessionNotice` at application level (title, one sentence, the action that works for the state,
expandable **Technical details** with state, category, failure count and time; never the capability). Pages show a compact
contextual empty state ("Unable to load user details") through `QueryState` and `ErrorState` and do not repeat the message,
the record-navigation note or the reconnect action. If open dialogs or forms hold typed text, Reconnect first asks for
confirmation because the reload discards it; nothing is saved or resubmitted automatically, and stale-revision checks are unchanged.

Cause: a desktop launch generates one capability per process and hands it over only through the guarded root document, so the warning
can only appear when a page holds a capability that does not match the running backend (an old window or tab after a restart, or a
second instance). A normal launch must not show it; if it does, record the Technical details and the startup log (Settings → Health &
Diagnostics) and report them.

## Open browser tabs after a restart

The API capability is per launch; an old tab retains its previous capability until
it navigates through the trusted root document. A rejected desktop capability now
returns a safe `stale_session` classification, distinct from unreachable service,
server sign-in (401), and permission/origin failures (403). The shared notice offers
**Reconnect session** rather than claiming the backend is unavailable.

Recovery is explicit: it reloads the same configured origin's root, retaining the
hash route and existing safe view/filter history. It never fetches a capability
through an unguarded API, switches host/port, loosens CORS, or replays a failed
write. Unsaved form input may be lost, as the recovery notice explains. A temporary
outage can use the existing bounded read/retry controls instead. Changed lazy
assets show an explicit reload fallback; no automatic reload loop is introduced.

Supported path-style entry points (`/dashboard`, `/role-lookup`, `/user-access`,
`/release-roles`, `/sod` and their nested paths) redirect to the existing hash
router. API, asset and unknown root paths retain their normal handlers/404s.
Host/port, peer, Origin and document handoff checks still apply. `localhost` and
`127.0.0.1` work only as explicitly permitted by the owned desktop listener;
server authentication and configured trusted origins remain independent.
