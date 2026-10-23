<!-- LOGO -->
<h1>
<p align="center">
  <img src="assets/sap-lens.png" alt="Logo" width="200">
  <br>SAP Lens
</h1>
  <p align="center">
    <b>SAP S/4HANA</b> · Role analysis and comparison tool for Company's internal SAP authorisation landscape.
    <br />
    <br />
    <a href="#1">Get started</a>
    ·
    <a href="docs/LOCAL_WINDOWS_BUILD.md">Local Windows build</a>
    ·
    <a href="docs/CSV_IMPORT.md">CSV import</a>
    ·
    <a href="docs/CONFIGURATION.md">Settings</a>
    ·
    <a href="#4">Development</a>
    ·
    <a href="#5">Security & architecture</a>
  </p>
</p>


---

SAP Lens browses and compares SAP roles from local CSV exports. No SAP connection or cloud account is required. Organization settings and naming rules stay in per-user storage.

<a id="1"></a>
## Get started

Download **SAP-Lens-Windows-x64** from a successful **Build Windows application** GitHub Actions run. Extract and open **SAP-Lens.exe** on Windows 10/11 x64 with Microsoft Edge WebView2 Runtime installed. No Python, Node.js or terminal is needed. Closing the app stops its owned backend; a second launch activates the existing window.

In **Settings**, enter your organization/system details, then use **Data Source & Import** to choose a CSV. Detect columns, map fields and preview before applying. Try [synthetic examples](examples/README.md) first. This is a native desktop wrapper, not an offline PWA. Builds are unsigned; consult your organization's distribution policies.

<a id="2"></a>
## File settings

Settings includes organization, import profiles, SAP module appearance, classification, branding and diagnostics. Defaults are **Example Inc.**, **SAP S/4HANA**, **DEMO**, client **100**, and **Example System**. Use absolute local paths or authorized Windows UNC shares. A failed import retains the previous settings/data; cancel a stalled load to choose another file.

Nine canonical fields are supported: `FUNCTION_KEY`, `AGR_NAME`, `TEXT`, `CHILD_AGR`, `CHILD_AGR_TEXT`, `PARENT_AGR`, `Effective_Role`, `TCODE`, `TTEXT`. Only `AGR_NAME` is required. Existing seven-column exports remain supported. Mapping, encoding, delimiter and classification previews are read-only.

- [Full-window settings, startup and theme colors](docs/UX_AND_THEMES.md)
- [Configuration, backups and portable exports](docs/CONFIGURATION.md)
- [CSV mappings and relationship semantics](docs/CSV_IMPORT.md)
- [Legacy, Generic and Custom classification](docs/CLASSIFICATION.md)
- [Central SAP area registry](docs/MODULES.md)

<a id="3"></a>
## Build EXE

Start the [Windows workflow](.github/workflows/build-windows.yml) manually through **Actions → Build Windows application → Run workflow** and select the desired branch. It does not run automatically on commits, tags or pull requests. It tests, audits, packages a console-free EXE and smoke-tests its lifecycle. Download its artifact and SHA-256 checksum; artifacts expire after 14 days. The separate [Fast Validation workflow](.github/workflows/validate.yml) runs backend/repository checks and frontend type checks on pushes and pull requests. Full Validation adds browser tests, production frontend compilation and security audits for pull requests targeting main. See [CI architecture and temporary skipping](docs/CI_ARCHITECTURE.md) for details.

For local Windows builds without Actions credits, follow the [step-by-step local build guide](docs/LOCAL_WINDOWS_BUILD.md). It includes prerequisites, execution-policy troubleshooting, all four modes, output locations and checksum checks. From the repository root, run:

```powershell
.\scripts\build-local.ps1 -Mode Quick
.\scripts\build-local.ps1 -Mode Build -Version 0.1.0
```

Quick checks development inputs; Build creates the verified EXE and ZIP under `dist/local/`. See the guide for Validate, Package and beta-version commands. User settings, CSVs, logos and logs are excluded from the distribution.

<a id="4"></a>
## Development

Run directly from source without building an EXE. Use Python 3.12 x64 and Node 24
LTS (recommended) or 25 with npm 10/11. See the [development guide](docs/DEVELOPMENT.md)
for prerequisites, execution-policy troubleshooting, isolated settings and the
native Windows source-mode alternative.

From the repository root in **Windows PowerShell**:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements-dev.txt
npm --prefix frontend ci
$env:SAP_LENS_CONFIG_DIR = Join-Path (Get-Location).Path 'local-config\development'
npm --prefix frontend run dev
```

This example uses separate, Git-ignored development settings.
Open **http://127.0.0.1:18743** in your browser. Keep that terminal open;
**Ctrl+C** stops both development services. Vite serves the frontend at `18743`
and proxies the backend at `18744`. No frontend production build, EXE, PyInstaller
or WebView2 is needed for browser development.

For the actual Windows app window without an EXE, install the desktop requirements,
compile the frontend and launch the source entry point. Run these from the
repository root in a terminal with `.venv` activated, after stopping `npm run dev`:

```powershell
python -m pip install -r backend/requirements-desktop.txt
npm --prefix frontend run build
python backend/desktop.py
```

This uses WebView2 and the managed loopback backend, with automatic port fallback.
See the guide for the console-free `pythonw.exe` alternative and test commands.
`build-local.ps1 -Mode Quick` and `-Mode Validate` perform checks; they do not launch
the application. [EXE packaging](docs/LOCAL_WINDOWS_BUILD.md) is a separate workflow.

<a id="5"></a>
## Security & architecture

The desktop API binds only to `127.0.0.1`, prefers port `18743`, allows the selected origin and requires a fresh launch capability. This is a local single-user application. A nonstandard port is not authentication.

- [Architecture and performance](docs/ARCHITECTURE.md)
- [API reference](docs/API_REFERENCE.md)
- [Security review](docs/SECURITY_REVIEW.md)
- [Privacy and historical exposure](docs/PRIVACY.md)
- [Repository cleanup inventory and maintenance decisions](docs/REPOSITORY_CLEANUP.md)
- [Validation results and outstanding Windows checks](docs/VALIDATION.md)
