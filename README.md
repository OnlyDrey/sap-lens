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
    <a href="#2">File settings</a>
    ·
    <a href="#3">Build EXE</a>
    ·
    <a href="#4">Development</a>
    ·
    <a href="#5">Security & architecture</a>
  </p>
</p>


---

SAP Lens browses and compares SAP composite roles from a CSV export. Search by role or T-code, filter by module, inspect single roles, and compare two to five composites. Data stays on your computer; no SAP connection or cloud account is required.

<a id="1"></a>
## Get started

1. Open the repository's **Actions → Build Windows application** workflow. Choose **Run workflow**, or open a successful run for the development branch (`work`) or `main`.
2. Download **SAP-Lens-Windows-x64** from its artifacts and extract it.
3. Open **SAP-Lens.exe** on Windows 10/11 x64 with Microsoft Edge WebView2 Runtime installed.
4. On first launch, choose your CSV with **Browse for CSV…** (or enter its full path) in **Settings**, then choose **Save and load CSV**.

The EXE opens a desktop window with no terminal. It includes the frontend, Python runtime and local API. You do not need Node.js or Python on the destination PC. Keep the app window open while using SAP Lens; closing it stops its backend. Relaunching restores the saved CSV location. A second launch brings the existing window forward.

This is a native WebView desktop wrapper, not an offline PWA: the window owns the server, so there is no terminal to keep alive. No role data is stored in a browser offline cache. The build is unsigned; your organization's Windows policies may require signing before distribution.

<a id="2"></a>
## File settings

Open **Settings → Browse for CSV…** to choose another file or enter its full path, for example `C:/SAP/exports/sap_roles.csv` or `//server/share/sap_roles.csv`. Windows network-share permissions use your signed-in account. On Linux, mount the share and enter its local path.

Required CSV headers (UTF-8, comma-separated; BOM accepted):

```csv
FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT
FI,DEMO:FI,Synthetic finance role,DEMO:READ,Synthetic single role,DEMO_DISPLAY,Synthetic transaction
```

The app validates the CSV before saving its location and replacing the cache. An invalid or inaccessible file keeps the previous loaded data. If a share is unavailable at launch, Settings remains available so you can correct the path. **Refresh Data** reloads the current file, including the T-code search index.

Settings and rotating logs are under `%LOCALAPPDATA%/SAP Lens/` on Windows. CSV contents are not copied there. Advanced bootstrap variables and development overrides are described in [configuration](docs/CONFIGURATION.md).

<a id="3"></a>
## Build the Windows EXE

The [GitHub Actions workflow](.github/workflows/build-windows.yml) builds on Windows for pushes to `main` and `work`, `v*` tags, pull requests and manual runs. It installs dependencies, checks types, builds the frontend, runs backend and production-browser tests, packages a console-free EXE, and smoke-tests its API and window lifecycle before uploading the EXE with SAP Lens icon/version metadata and SHA-256 checksum. Artifacts expire after 14 days; the workflow does not publish a GitHub Release.

To build locally with Python 3.12, Node.js 22.12+ and PowerShell:

```powershell
.\build.bat
```

Output: `backend/dist/SAP-Lens.exe`. Run the built EXE directly, or use `run.bat`. Build inputs do not include your CSV, `.env`, per-user settings or logs. See [desktop packaging](docs/DESKTOP.md) for prerequisites, troubleshooting and the Windows validation checklist.

<a id="4"></a>
## Development

Python 3.12 and Node.js 22.12+ are recommended. From the repository root:

```sh
python -m venv .venv
# Activate: .venv/Scripts/Activate.ps1 on Windows; source .venv/bin/activate on Linux
python -m pip install -r backend/requirements-dev.txt
cd frontend
npm ci
npm run dev
```

The development UI uses port `18743`, proxies API requests to `127.0.0.1:18744`, and uses the same Settings screen as the EXE. Activate the Python environment before running `npm run dev`. Start development first if running both; a desktop launch automatically selects another port when `18743` is occupied.

For production-style web testing, run `npm run build` in `frontend`, then from `backend`:

```sh
python -m uvicorn main:app --host 127.0.0.1 --port 18743
```

This source-mode command uses a terminal. Desktop users use the EXE. For source-mode desktop testing on Windows, install `backend/requirements-desktop.txt` into `.venv`, build the frontend, then use `run.bat`.

Validation from the repository root:

```sh
python -m unittest discover -s backend/tests -v
python -m pip check
cd frontend
npm run build
npx playwright install chromium
npm run test:browser
```

<a id="5"></a>
## Security & architecture

SAP Lens is a local, single-user application. The packaged API binds exclusively to `127.0.0.1`, prefers port `18743`, and reserves another available port on conflict. CORS allows only the actual desktop origin; API calls require a fresh per-launch session capability. It is not a multi-user or LAN service, and a nonstandard port is not an authentication mechanism.

- [Architecture and performance](docs/ARCHITECTURE.md)
- [API reference](docs/API_REFERENCE.md)
- [Security review and remaining limitations](docs/SECURITY_REVIEW.md)
- [Configuration and data handling](docs/CONFIGURATION.md)

Internal tool — Company. For SAP authorisation questions, refer to your SAP Role Owner matrix.
