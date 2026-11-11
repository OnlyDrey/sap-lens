# Run SAP Lens from source (no EXE)

Use this guide to edit or run the application locally without PyInstaller or EXE
packaging. Choose browser development for fast UI/backend iteration, or the
Windows desktop entry point when testing WebView2 and native dialogs.

| Mode | Starts | Frontend | Terminal |
|---|---|---|---|
| `npm --prefix frontend run dev` | Vite and a reloadable Uvicorn backend | Development server with hot reload | Keep open; Ctrl+C stops both |
| `python backend/desktop.py` | Native Windows window and its managed backend | Previously compiled `frontend/dist` | Visible console for debugging |
| `.\.venv\Scripts\pythonw.exe backend\desktop.py` | Same native application | Previously compiled `frontend/dist` | No visible Python console |

None of these commands builds an EXE or uses GitHub Actions. The public build CLI Quick/test modes are validation commands, not application launchers.

## Prerequisites

- Git checkout of the intended branch.
- Python **3.12 x64**, with pip and venv.
- Node **24 LTS** recommended; Node **25** is accepted for compatibility but is
  upstream end-of-life. npm **10 or 11**.
- Windows PowerShell 5.1 or PowerShell 7 for the Windows commands below.
- **Only for the native Windows window:** desktop Python requirements, .NET
  Framework 4.6.2+ and Edge WebView2 Evergreen Runtime on Windows x64.

See [prerequisite installation](#windows-build-toolchain)
for installers, version checks, missing npm/PATH diagnostics and process-scoped
execution-policy options. Browser development does not need WebView2, PyInstaller
or the Windows packaging dependencies.

## 1. One-time setup

Open PowerShell in the repository root. Nothing needs activating, no `PATH` change and no
execution-policy change; other Python versions (3.13, 3.14, 3.15 as the default) may stay installed.

```powershell
.\scripts\build.ps1 -Mode prerequisites            # setup: create .venv, install pinned dependencies, npm ci
.\scripts\build.ps1 -Mode prerequisites -CheckOnly # report only, changes nothing (add -Json for machine output)
.\scripts\build.ps1 -Mode prerequisites -Repair    # rename a broken or wrong-version .venv aside and recreate it
```

Linux/macOS: `python3.12 scripts/build.py prerequisites [--check-only|--repair] [--json]`.

- **Interpreter:** exactly Python 3.12 x64 with `venv`, found in this order: `SAP_LENS_PYTHON`, the
  running interpreter, `py -3.12`, registered installations, `python3.12`, then a bare `python` only if it
  really is 3.12. Every candidate is probed; the default `python` is never trusted by name.
- **`.venv`:** created automatically with that interpreter. An existing environment is reused only if its
  interpreter starts, is 3.12 x64 and `pyvenv.cfg` exists. A broken or wrong-version one is reported and
  left untouched; `-Repair` renames it to `.venv.broken-<timestamp>` (never deletes) and recreates it.
- **Dependencies:** `backend/requirements-dev.txt` (runtime, tests, ruff) and, for packaging targets,
  `backend/requirements-build.txt`; installed only when a pin is missing or differs, so a second run
  changes nothing. Frontend: `npm ci` only when `node_modules` is missing or older than `package-lock.json`.
- **Statuses and exit codes:** Ready, Warning, Missing, Incompatible, Repair required; exit `0` usable,
  `3` a required component needs action. Warnings (for example Node 25, a non-LTS release) never fail.
- **Offline or restricted network:** check mode needs no network. Setup fails clearly if the package index
  is unreachable (certificate problems: trust the corporate CA in the OS store; checks are never disabled)
  and leaves the environment reported as not ready, never as ready. Prepared environments keep working offline.
- **Target-aware:** `-Target service` also needs .NET Framework `csc.exe`, `-Platform docker` needs Docker;
  backend tests, frontend builds and Linux builds need no Windows tooling. `build`/`package` run the same
  check first and stop before any build step if a required tool is missing.
- **CI:** non-interactive and deterministic; CI keeps using `actions/setup-python` and Node 24, and the
  commands never prompt when stdin is redirected or `GITHUB_ACTIONS=true`.
- **Dependency audit:** `npm audit` (network) is separate from prerequisites. Currently production reports
  0 findings; the 10 moderate findings are the dev-only ESLint/`minimatch` chain, and the only offered
  fix is a breaking ESLint 9 downgrade, so it is intentionally not applied (`npm audit fix --force` is never run).

`validate.py` and `run-tests.py` run their children with the same resolved interpreter: the current one when
it is 3.12 x64, otherwise the ready `.venv`, otherwise they stop and name the command above.

## 2. Browser development

From the repository root:

```powershell
npm --prefix frontend run dev
```

Open **http://127.0.0.1:18743**. The command runs both services through the existing
`concurrently --kill-others` script:

- Vite binds to `127.0.0.1:18743` with a strict port and hot-reloads frontend edits.
- Uvicorn binds to `127.0.0.1:18744` with backend reload enabled.
- Vite proxies `/api` and `/health` to the backend on port 18744.

Do not open the backend port as the development UI, and do not bind either service
to a LAN address. Port 18743 is fixed in this mode: it does not automatically
switch ports when busy. Stop another owned SAP Lens instance or diagnose the
conflict rather than changing origins or killing unrelated processes.

Keep the terminal open. **Ctrl+C** stops both services. Closing it interrupts the
development app; this mode is not an independent desktop installation. A frontend
production build is not required for `npm run dev`.

On later sessions run the same dev command.
Reinstall Python requirements or run `npm ci` when the respective dependency
files change. `npm ci` replaces `node_modules`; do not run it while Vite is active.

## 3. Settings and CSV data

Use **Settings → Data Source & Import** for the two CSV paths. No SAP credentials,
direct SAP connection or real export is required merely to start the UI. Without
configured files, the app shows its normal configuration/empty-data state.

Source runs use the same per-user settings location as the app unless overridden.
To keep experiments separate from your usual settings, set an **absolute** test
configuration path before starting either mode:

```powershell
$env:SAP_LENS_CONFIG_DIR = Join-Path (Get-Location).Path 'local-config\development'
```

`local-config/` is Git-ignored. This creates a separate settings location, not a copy
of existing settings. An explicitly configured CSV source, including a bootstrap
`DATA_CSV_PATH` environment value or `backend/.env`, may still be read. Check such
inputs before experiments and use synthetic or approved local data.

After stopping the services, remove this session override if no longer wanted:

```powershell
Remove-Item Env:SAP_LENS_CONFIG_DIR -ErrorAction SilentlyContinue
```

Never commit imported CSVs, settings or credentials. See [configuration](../getting-started/CONFIGURATION.md)
and [CSV formats](../data/CSV_SCHEMAS.md) for source and persistence behavior.

## 4. Native Windows window without packaging

Stop the browser development services first. From the repository root with the
same development venv active:

```powershell
python -m pip install -r backend/requirements-desktop.txt
npm --prefix frontend run build
python backend/desktop.py
```

This launches the existing pywebview/WebView2 desktop entry point directly. It
loads the production frontend from `frontend/dist`, starts its backend inside the
application process and shuts it down when the window closes. Its preferred
loopback port is 18743, with a securely reserved fallback if occupied. Single-instance
and session/origin protections remain enabled.

The native window does **not** consume Vite's hot-reloaded frontend. After UI
changes, close the app, rerun `npm --prefix frontend run build` and relaunch it.
Use the console launch first to diagnose missing dependencies or startup errors.
For the same source application without a visible Python console:

```powershell
.\.venv\Scripts\pythonw.exe backend\desktop.py
```

Desktop logs are in the active settings directory (`sap-lens.log`), normally
`%LOCALAPPDATA%\SAP Lens\` on Windows. Configuration remains outside the source
bundle. If an earlier packaged instance is running, single-instance behavior may
activate it instead; close it before evaluating changed source code.

No EXE, ZIP, release reservation or package manifest is generated by this route.
To distribute a verified standalone binary, use [local Windows builds](../BUILD.md).

## 5. Checks from the repository root

Use [Testing](TESTING.md) for the canonical check commands. Keep the development
venv active and stop the native app before browser tests. The browser fixture
serves production assets with synthetic data on its isolated port 18745; do not
start that server manually or point tests at real settings. Packaging-only tests
may require optional build dependencies; inspect skips rather than counting them
as passes. Windows Validate mode and its receipt are documented in [Build](../BUILD.md#commands).
There is no separate frontend lint task; type/build/browser checks are the existing suite.

## 6. Troubleshooting

| Symptom | Action |
|---|---|
| `npm` not recognized | Install Node 24 x64 with npm and PATH enabled, then reopen PowerShell; see prerequisite diagnostics |
| `No module named uvicorn` or tests run under the wrong Python | `.\scripts\build.ps1 -Mode prerequisites -CheckOnly`, then run setup (or `-Repair`) |
| `ModuleNotFoundError` when starting backend | Use `npm --prefix frontend run dev` from the root, or the existing npm backend script; it supplies the correct working directory |
| Port 18743 busy | Stop your other development/native SAP Lens instance; Vite uses a strict port and will not silently change it |
| Local service unavailable in browser | Check both terminal processes are running and visit `/health` through the Vite origin |
| Changes not visible in native app | Stop the app, rebuild `frontend/dist` and launch again; check single-instance activation of an old process |
| Native window cannot start | Check Windows desktop requirements, WebView2 and the active settings log |
| Browser tests cannot find assets/browser | Build production assets and install the lockfile-matched Chromium headless shell |
| Unexpected previous settings | Inspect `SAP_LENS_CONFIG_DIR` and bootstrap overrides; do not delete user settings as a troubleshooting shortcut |

The source-mode instructions have been checked against package scripts, Vite
proxy configuration and the desktop entry point. Browser development can be
verified on Linux; native Windows execution must be tested on Windows.


## Windows build toolchain

The prerequisite matrix, diagnostics and build commands are in the [build guide](../BUILD.md#prerequisites); this section is the step-by-step installation walkthrough.

### Supported build machine

Use Windows x64 and a **64-bit** PowerShell session. ARM and 32-bit shells are
rejected. The script accepts Windows PowerShell 5.1 or PowerShell 7. Install tools
through your organization's approved software process; the script needs no admin
privileges and does not change execution policy.

| Tool | Required version | Purpose |
|---|---|---|
| Git for Windows | Available on `PATH` | Source identity and clean-checkout checks |
| Python | **3.12 x64**, with `venv` and pip | Backend, tests, packaging and verification |
| Node.js | **24 LTS (recommended) or 25** | Frontend tools and browser tests |
| npm | **10 or 11** | Lockfile-based dependency installation |
| PowerShell | **5.1 or 7**, x64 | Build orchestration |
| Edge WebView2 | Evergreen Runtime | Actual desktop startup/smoke testing |

### Install each prerequisite

Use your company's software portal first if this is a managed PC. Installer
permissions depend on your organization; **running the build** does not require
administrator rights. Review installer prompts rather than disabling controls.

1. **Git for Windows:** install from [git-scm.com](https://git-scm.com/downloads/win).
   Enable Git on the command line so `git.exe` is available on `PATH`. If Windows
   Package Manager is permitted, the equivalent package is:

   ```powershell
   winget install --id Git.Git --exact
   ```

2. **Python 3.12 x64:** obtain a Python 3.12 Windows installer from the
   [official Python Windows downloads](https://www.python.org/downloads/windows/)
   or your approved software portal. Include pip, the Python launcher (`py`) and
   `venv`; enable the installer's PATH option where available. Do not substitute
   Python 3.13/3.14 merely because it is newer. With permitted winget access:

   ```powershell
   winget install --id Python.Python.3.12 --exact
   ```

3. **Node.js x64 and npm:** prefer a **24.x** Windows x64 `.msi` from the
   [official Node.js 24 archive](https://nodejs.org/download/release/latest-v24.x/).
   Keep **npm package manager** and **Add to PATH** enabled in the installer.
   Installing Node.js this way installs npm too; do not install npm separately
   to repair a missing Node installation. Avoid blindly choosing “latest LTS”
   if it points to an unvalidated major version. Node 25 is also accepted; use
   the [official Node.js 25 archive](https://nodejs.org/download/release/latest-v25.x/)
   if you already standardize on that version. Node 25 is an odd-numbered,
   non-LTS release; Node 24 remains the recommended build/CI baseline.
   Node 25 reached upstream end of life on **2026-06-01**, so compatibility
   acceptance does not mean it receives security maintenance. Prefer Node 24
   for maintained tooling.

   For an approved winget-based installation, first inspect available versions:

   ```powershell
   winget show --id OpenJS.NodeJS.LTS --exact --versions
   ```

   If it lists a 24.x version, substitute that exact value below; the angle-bracket
   placeholder is not a runnable version string:

   ```text
   winget install --id OpenJS.NodeJS.LTS --exact --version <available-24.x.y-version>
   ```

   Use the MSI or your software portal if winget no longer offers that version.
   The local build accepts npm major 10 or 11. Check the installed npm version;
   do not upgrade globally to a new major just because npm prints an update notice.

4. **PowerShell:** Windows PowerShell 5.1 is normally already installed on Windows.
   Use its x64 edition, not Windows PowerShell (x86). PowerShell 7 is optional;
   install from [Microsoft's PowerShell installation guide](https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-windows)
   or, when permitted:

   ```powershell
   winget install --id Microsoft.PowerShell --exact
   ```

   `powershell.exe` starts Windows PowerShell; `pwsh` starts PowerShell 7. Either
   supported x64 shell can run `scripts/build.ps1`.

5. **Microsoft Edge WebView2 Evergreen Runtime:** install the x64 Evergreen
   Runtime from [Microsoft](https://developer.microsoft.com/microsoft-edge/webview2/),
   even if you use a different browser. The Edge browser's presence alone is not
   the acceptance check for the runtime. An approved winget installation is:

   ```powershell
   winget install --id Microsoft.EdgeWebView2Runtime --exact
   ```

   The desktop also needs .NET Framework 4.6.2 or later, normally supplied by
   supported Windows 10/11 installations. Ask IT to enable it if missing; Python's
   pinned desktop dependencies are installed by the build, not manually.

`winget` itself is supplied by Microsoft's App Installer on supported Windows
systems. If `winget` is unavailable or blocked, use the official installers or
software portal; the SAP Lens build does not require winget.

**Close PowerShell and open a new window after installing tools.** Existing
windows keep the old PATH. You do not need to reboot simply to refresh a shell's
PATH in the usual case.

### Verify tools before running a build

Open a new PowerShell window after installing tools. Check:

```powershell
$PSVersionTable.PSVersion
$env:PROCESSOR_ARCHITECTURE  # Expected: AMD64
git --version
py -3.12 --version          # Expected: Python 3.12.x
py -3.12 -c "import struct; print(struct.calcsize('P') * 8)"  # Expected: 64
node --version             # Expected: v24.x.x or v25.x.x
npm --version              # Expected: 10.x.x or 11.x.x
```

The script first tries `py -3.12`. If unavailable, it tries `python` on `PATH` and
checks that it is Python 3.12 x64. If using that fallback, replace `py -3.12` with
`python` in the diagnostic commands above.

Install the [official WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)
if absent, or ask IT to provide it. Run builds from an interactive Windows desktop
for the GUI smoke test.

### Fix “npm is not recognized” / PATH problems

First test both tools in the new PowerShell window:

```powershell
node --version
npm --version
Get-Command node -ErrorAction SilentlyContinue
Get-Command npm -ErrorAction SilentlyContinue
where.exe node
where.exe npm
```

- If **both are missing**, install Node.js 24 or 25 x64 with npm and PATH enabled.
- If **node works but npm is missing**, repair the Node.js installation and enable
  its npm component. Avoid downloading an unrelated npm executable.
- If the installer completed but **this window still cannot find them**, reopen
  PowerShell. A standard system-wide installation usually lives in
  `C:\Program Files\nodejs`, but a managed/per-user installation can differ.
- If multiple installations are listed, use the approved version manager or
  installer to select Node 24 or 25. Do not delete unrelated installations blindly.

To diagnose a standard installation without changing global PATH:

```powershell
$nodeDirectory = Join-Path $env:ProgramFiles 'nodejs'
Test-Path (Join-Path $nodeDirectory 'node.exe')
Test-Path (Join-Path $nodeDirectory 'npm.cmd')
# Run only if both files above exist and this is your trusted Node 24/25 installation:
& (Join-Path $nodeDirectory 'node.exe') --version
& (Join-Path $nodeDirectory 'npm.cmd') --version
$env:Path = $nodeDirectory + ';' + $env:Path
node --version
npm --version
```

The PATH change above affects this session only. Repair the installer/PATH setting
through your approved process for a persistent fix. If `npm.ps1` is found but
blocked as unsigned, that is an execution-policy error, not a missing npm package;
use the trusted-source process-scoped policy instructions below where permitted.

Do not solve a missing npm command by manually skipping the Frontend stage.
The compiled frontend is required in the Windows package.

### Supported range versus minimum version

The local wrapper and frontend manifest accept **`>=24 <26`**: Node 24 and 25.
CI continues to use Node 24. According to the
[official Node.js release schedule](https://github.com/nodejs/Release/blob/main/schedule.json),
Node 25 ended support on 2026-06-01; Node 24 is supported until 2028-04-30.
The installed Vite and Playwright engine ranges
include Node 25, so their declared requirements do not require rejecting it.
Changing Node versions invalidates a Package validation receipt; run Validate
again before Package.

Compatibility checks on Linux passed with Node **24.19.0** and **25.9.0**:
lockfile installation, type checking and production builds on both versions;
all **71 browser tests** on Node 25; and PowerShell version-gate regression tests.
Native Windows packaging with Node 25 has not been executed in this environment.

A bare `>=24` would also accept Node 26 and all future majors without testing
them. Those are not enabled automatically. npm remains restricted to major 10
or 11; npm's own major version is independent of the selected Node major.

### Network access

Quick is offline after the host tools are installed. Build/Validate need access to Python/npm registries, vulnerability databases,
Playwright's browser downloads and GitHub's actionlint release assets. Warm caches
reduce downloads but **do not make the full build offline**: security audits still
query current vulnerability data. GitHub authentication is not needed by the build
script; cloning a private repository may require your existing Git credentials.

Preserve approved proxy and CA configuration. Do not disable certificate checks
or skip audits to work around a corporate network error.

### Corporate script policy

A signature/policy failure occurs before a blocked script starts; it is not a
Python/npm build failure. Inspect policy without changing it:

```powershell
Get-ExecutionPolicy -List
```

Use the organization's approved checkout, signing process and execution policy.
AllSigned/Restricted/AppLocker/WDAC can block the root bootstrapper or its internal
helpers. Ask IT to approve/sign the reviewed scripts; do not disable protections,
change machine policy, blanket-unblock scripts or add execution-policy bypasses.
An approved Python invocation can show the CLI/help and perform non-PowerShell
checks, but does not bypass restrictions on Windows packaging helpers.

Build modes, versioning, receipt reuse and outputs are documented only in the
[canonical build guide](../BUILD.md#commands).

### Restricted-network build prerequisites

Resolve selected build tools once with the public prerequisites mode before
starting packaging. The shared managed-tool engine verifies pinned artifacts,
reuses persistent caches and supports approved internal mirrors; Python/Node
system installation remains separately consented. See the authoritative
[prerequisite and proxy guide](../BUILD.md#centralized-prerequisites-and-restricted-networks).
Quick/read-only inspection does not download tools; offline mode applies only
to managed tools, not pip/npm or security-audit network calls.
