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

SAP Lens browses and compares SAP roles from local CSV exports. No SAP connection or cloud account is required. Organization settings and naming rules stay in per-user storage.

<a id="1"></a>
## Get started

Download **SAP-Lens-Windows-x64** from a successful **Build Windows application** GitHub Actions run. Extract and open **SAP-Lens.exe** on Windows 10/11 x64 with Microsoft Edge WebView2 Runtime installed. No Python, Node.js or terminal is needed. Closing the app stops its owned backend; a second launch activates the existing window.

In **Settings**, enter your organization/system details, then use **Data Source & Import** to choose a CSV. Detect columns, map fields and preview before applying. Try [synthetic examples](examples/README.md) first. This is a native desktop wrapper, not an offline PWA. Builds are unsigned; consult your organization's distribution policies.

<a id="2"></a>
## File settings

Settings includes organization, import profiles, SAP module appearance, classification, branding and diagnostics. Defaults are **Example Inc.**, **SAP S/4HANA**, **DEMO**, client **100**, and **Example System**. Use absolute local paths or authorized Windows UNC shares. A failed import retains the previous settings/data; cancel a stalled load to choose another file.

Nine canonical fields are supported: `FUNCTION_KEY`, `AGR_NAME`, `TEXT`, `CHILD_AGR`, `CHILD_AGR_TEXT`, `PARENT_AGR`, `Effective_Role`, `TCODE`, `TTEXT`. Only `AGR_NAME` is required. Existing seven-column exports remain supported. Mapping, encoding, delimiter and classification previews are read-only.

- [Configuration, backups and portable exports](docs/CONFIGURATION.md)
- [CSV mappings and relationship semantics](docs/CSV_IMPORT.md)
- [Legacy, Generic and Custom classification](docs/CLASSIFICATION.md)
- [Central SAP area registry](docs/MODULES.md)

<a id="3"></a>
## Build EXE

The [Windows workflow](.github/workflows/build-windows.yml) runs on pushes to `main`/`work`, `v*` tags, pull requests and manual dispatch. It tests, audits, packages a console-free EXE and smoke-tests its lifecycle. Download its artifact and SHA-256 checksum; artifacts expire after 14 days. A push alone does not establish a successful Windows build.

For a local build with Python 3.12, Node.js 22.12+ and PowerShell, run `build.bat`. Output: `backend/dist/SAP-Lens.exe`. User settings, CSVs, logos and logs are excluded. See [desktop packaging and Windows acceptance](docs/DESKTOP.md).

<a id="4"></a>
## Development

```sh
python -m venv .venv
# Activate .venv before continuing
python -m pip install -r backend/requirements-dev.txt
cd frontend
npm ci
npm run dev
```

Vite uses `127.0.0.1:18743` and proxies the backend at `18744`. Desktop mode automatically selects another port if necessary. For source-mode desktop use, install `backend/requirements-desktop.txt`, build the frontend and run `run.bat` on Windows.

```sh
# From the repository root, with .venv activated
python -m unittest discover -s backend/tests -v
python -m pip check
cd frontend
npm run build
npx playwright install chromium
npm run test:browser
```

<a id="5"></a>
## Security & architecture

The desktop API binds only to `127.0.0.1`, prefers port `18743`, allows the selected origin and requires a fresh launch capability. This is a local single-user application. A nonstandard port is not authentication.

- [Architecture and performance](docs/ARCHITECTURE.md)
- [API reference](docs/API_REFERENCE.md)
- [Security review](docs/SECURITY_REVIEW.md)
- [Privacy and historical exposure](docs/PRIVACY.md)
- [Validation results and outstanding Windows checks](docs/VALIDATION.md)
