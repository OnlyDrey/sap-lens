# Run SAP Lens from source (no EXE)

Use this guide to edit or run the application locally without PyInstaller or EXE
packaging. Choose browser development for fast UI/backend iteration, or the
Windows desktop entry point when testing WebView2 and native dialogs.

| Mode | Starts | Frontend | Terminal |
|---|---|---|---|
| `npm --prefix frontend run dev` | Vite and a reloadable Uvicorn backend | Development server with hot reload | Keep open; Ctrl+C stops both |
| `python backend/desktop.py` | Native Windows window and its managed backend | Previously compiled `frontend/dist` | Visible console for debugging |
| `.\.venv\Scripts\pythonw.exe backend\desktop.py` | Same native application | Previously compiled `frontend/dist` | No visible Python console |

None of these commands builds an EXE or uses GitHub Actions. Quick/Validate modes
in `build-local.ps1` are validation commands, not application launchers.

## Prerequisites

- Git checkout of the intended branch.
- Python **3.12 x64**, with pip and venv.
- Node **24 LTS** recommended; Node **25** is accepted for compatibility but is
  upstream end-of-life. npm **10 or 11**.
- Windows PowerShell 5.1 or PowerShell 7 for the Windows commands below.
- **Only for the native Windows window:** desktop Python requirements, .NET
  Framework 4.6.2+ and Edge WebView2 Evergreen Runtime on Windows x64.

See [prerequisite installation](../deployment/BUILD.md#2-install-and-check-prerequisites)
for installers, version checks, missing npm/PATH diagnostics and process-scoped
execution-policy options. Browser development does not need WebView2, PyInstaller
or the Windows packaging dependencies.

## 1. One-time setup

Open PowerShell in the repository root, where `backend`, `frontend` and `scripts`
are located. Quote paths containing spaces. These commands use a development venv,
separate from the packaging toolchain's `backend/build/python-env`.

```powershell
Set-Location 'C:\Projects\sap-lens'
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements-dev.txt
npm --prefix frontend ci
```

The example directory must be replaced with your actual checkout location.
Activation makes `python` in npm's backend subprocess refer to this venv. Verify:

```powershell
python -c "import sys; print(sys.executable)"
node --version
npm --version
```

The Python path should end in this checkout's `.venv\Scripts\python.exe`. If script
activation is blocked, review the trusted-source execution-policy instructions in
the prerequisite guide; company Group Policy may require IT approval.

On Linux/macOS, the equivalent activation is `source .venv/bin/activate` after
`python3.12 -m venv .venv`. Browser development is available there; the documented
Windows/WebView2 desktop path is not a cross-platform native validation claim.

## 2. Browser development

In the same terminal with `.venv` activated, from the repository root:

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

On subsequent sessions, activate `.venv` again and run the same dev command.
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
To distribute a verified standalone binary, use [local Windows builds](../deployment/BUILD.md).

## 5. Checks from the repository root

Use [Testing](TESTING.md) for the canonical check commands. Keep the development
venv active and stop the native app before browser tests. The browser fixture
serves production assets with synthetic data on its isolated port 18745; do not
start that server manually or point tests at real settings. Packaging-only tests
may require optional build dependencies; inspect skips rather than counting them
as passes. Windows Validate mode and its receipt are documented in [Build](../deployment/BUILD.md#windows-only-development-modes).
There is no separate frontend lint task; type/build/browser checks are the existing suite.

## 6. Troubleshooting

| Symptom | Action |
|---|---|
| `npm` not recognized | Install Node 24 x64 with npm and PATH enabled, then reopen PowerShell; see prerequisite diagnostics |
| `No module named uvicorn` | Activate the correct `.venv` and install `backend/requirements-dev.txt` |
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
