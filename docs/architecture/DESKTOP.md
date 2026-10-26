# Windows Desktop 1.2

## Runtime scope

For prerequisites, installation, upgrades and recovery use [Windows Desktop](../deployment/WINDOWS_DESKTOP.md).
For local/Actions commands use [Build](../deployment/BUILD.md). This document owns
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
| Other startup failure | Close and reopen; inspect `%LOCALAPPDATA%/SAP Lens/sap-lens.log` for the failed stage/category and check profile permissions |
| Source-mode development | Activate `.venv`, install desktop requirements and build the frontend, then run `.\.venv\Scripts\pythonw.exe backend\desktop.py` from the repository root |

Settings are stored per user, independently of the EXE. Logs omit source paths, data and launch capabilities. A normal exit removes `runtime.json`. Forced OS termination may leave this non-secret diagnostic file; the next owned launch replaces it. No service worker caches SAP responses.

## Packaging verification boundary

`scripts/build-windows.ps1` remains the canonical one-file PyInstaller compiler.
Deployment packaging wraps its verified portable payload with the per-user Setup
and manifest; it does not implement a second desktop application build. UPX stays
disabled. [CI](../development/CI.md) owns workflow orchestration and
[Build](../deployment/BUILD.md) owns user commands.

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

See [validation record](../archive/validation/VALIDATION.md) for measured local results versus pending Windows results.

The settings UI also supports native logo selection, portable configuration Save dialogs and opening the per-user configuration folder. Saved organization/theme/profile/logo settings survive upgrades; user assets are never bundled into later builds. Test these dialogs and persistence on actual Windows alongside the CSV picker. Unexpected owned-server death is reported and closes the window; a failed service is not left behind a seemingly working interface.

Version 1.2 introduces a responsive branded startup document, full-window settings, organization-first header and persistent theme colors. See [workspace and themes](APPEARANCE.md). The changed 1.2 launcher and canonical build passed automated Windows GUI/lifecycle/package validation in [run 39469463871](https://github.com/OnlyDrey/sap-lens/actions/runs/39469463871); target-PC/native interaction checks remain pending.

## Requirement ownership

`backend/requirements.txt` contains application/API dependencies. `requirements-desktop.txt` adds the native WebView runtime, `requirements-dev.txt` adds backend tests, and `requirements-build.txt` adds PyInstaller and pinned build pip to desktop runtime dependencies. `scripts/requirements-audit.txt` pins audit tooling for the separate host interpreter. The canonical build script installs build and test requirements into its isolated environment; normal source-mode desktop execution needs only desktop requirements. Node 24 LTS is recommended; the build toolchain accepts Node 24 or 25. User configuration is not a developer/build input.

The canonical build also creates the SHA-256 manifest and runs `scripts/verify-windows-package.py` before delivery. The verifier checks the PE GUI subsystem, checksum, required bundled assets and absence of known private configuration/CSV/log entries. The GitHub workflow uploads the same verified output; it does not maintain a second checksum implementation.


Role Lookup, User Access, Release Roles and legacy configuration compatibility are documented in [User Access](../features/USER_ACCESS.md). See [UI refinement](../archive/validation/UI_REFINEMENT.md) for data-source navigation, filter availability and area-color behavior.

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
