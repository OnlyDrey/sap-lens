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
    <a href="docs/README.md">Documentation</a>
    ·
    <a href="docs/DEPLOYMENT.md">Installation &amp; deployment</a>
    ·
    <a href="docs/DEPLOYMENT_PACKAGES.md">Build packages</a>
    ·
    <a href="https://github.com/OnlyDrey/sap-lens/releases">GitHub Releases</a>
  </p>
</p>



---

SAP Lens is a local-first SAP investigation and access-review application. Browse
roles and transaction mappings, investigate user assignments and release roles,
compare users, enrich identities with an optional Employee Directory, and record
Account Review decisions. Role-derived transaction coverage is evidence for
investigation, not proof of effective SAP authorization or license consumption.
No direct SAP connection or third-party data-upload service is required.

<a id="1"></a>
## Get started

Choose the deployment appropriate for your environment:

| Target | Interface | Installation guide |
| --- | --- | --- |
| Windows Desktop x64 | Native WebView2 window; portable EXE or installer | [Windows Desktop](docs/INSTALLATION_WINDOWS_DESKTOP.md) |
| Windows Server Service x64 | Hosted browser application; WinSW/SCM | [Windows Server](docs/DEPLOYMENT_WINDOWS_SERVER.md) |
| Linux Docker amd64 | Hosted browser application; offline image and Compose | [Docker](docs/DEPLOYMENT_LINUX_DOCKER.md) |
| Linux Native/systemd x64 | Python 3.12 server; systemd or manual browser client | [Linux Native](docs/DEPLOYMENT_LINUX_NATIVE.md) |

All modes share the backend, frontend, CSV lifecycle and business logic. There is
no separate Linux desktop executable. Hosted clients use a modern browser; remote
access requires an explicit authenticated HTTPS boundary. See [deployment and
security](docs/DEPLOYMENT.md) before exposing real data.

Packaging definitions are implemented; that does not certify every native target.
Docker and Linux user-mode integration have been exercised locally. Current
Windows installer/service, real systemd, reboot/recovery and UNC acceptance remain
pending. See [current lifecycle validation](docs/INSTALLATION_LIFECYCLE_VALIDATION.md)
and [build validation](docs/LOCAL_BUILD_VALIDATION.md). Artifacts exist only after a
successful build; no future release or download is implied by these guides.

<a id="2"></a>
## Data sources and settings

Configure Role Catalogue, User–Role Mapping and optional Employee Directory under
Settings → Data Sources. Column mappings/import presets are source-specific.
Static imports retain snapshots; Dynamic sources refresh configured server-side
paths. Replacement is complete and validated before publication; failures retain
the previous valid dataset. Missing optional CSVs do not prevent core use.

SAP areas come from recognized CSV module evidence. The former configurable
classification UI is removed; legacy settings are preserved inactive. Module
colors/icons and existing import mappings remain supported.

- [CSV schemas and import](docs/CSV_IMPORT.md)
- [CSV lifecycle and persistence](docs/CSV_DATA_LIFECYCLE.md)
- [User/release investigation](docs/ACCESS_INVESTIGATION.md)
- [Settings and storage](docs/CONFIGURATION.md)
- [Synthetic examples](examples/README.md)

<a id="3"></a>
## Build packages

Use the manual [Build Deployment Packages workflow](.github/workflows/build-deployments.yml)
for one target or All. Build-only is the default; publication requires a separate
explicit choice and successful verification of every selected target. The legacy
[Build Windows Application workflow](.github/workflows/build-windows.yml) retains
its existing portable-desktop release behavior. Neither starts on ordinary pushes.
GitHub Releases holds release notes/history; Actions artifacts have finite retention.

Local cross-platform entry points use the same canonical packaging scripts:

```sh
./build.sh --platform docker --version 0.1.0-beta.1
./build.sh --platform linux-native --version 0.1.0
```

```powershell
.\build.ps1 -Platform desktop -Version 0.1.0-beta.1
.\scripts\build-local.ps1 -Mode Quick
```

Read [local deployment builds](docs/LOCAL_DEPLOYMENT_BUILDS.md) for prerequisites,
native/remote builder requirements, caches, outputs and validation. Read the
[local Windows guide](docs/LOCAL_WINDOWS_BUILD.md) for Quick/Validate/Build/Package,
execution-policy and prerequisite troubleshooting. Local builds never create tags,
releases or remote commits. Builds remain unsigned.

<a id="4"></a>
## Development

Use Python 3.12 x64 and Node 24 LTS (recommended) or Node 25, with the locked npm
dependencies. From the repository root in Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements-dev.txt
npm --prefix frontend ci
$env:SAP_LENS_CONFIG_DIR = Join-Path (Get-Location).Path 'local-config\development'
npm --prefix frontend run dev
```

Open `http://127.0.0.1:18743`; Vite proxies the backend on `18744`. Ctrl+C stops
both development processes. An EXE, production build and WebView2 are unnecessary
for browser development. See [development](docs/DEVELOPMENT.md) for Linux commands,
source-mode Windows desktop startup and regression tests.

<a id="5"></a>
## Security and maintenance

Desktop binds only to loopback and uses a fresh session capability. Server mode
uses separate storage, validates hosts/origins and requires explicit access
protection for non-local exposure. No automatic telemetry or cloud data service is
introduced. Browser uploads go to the operator's SAP Lens server, not a third-party
service. Private CSVs, snapshots, settings and branding stay outside Git/artifacts.

- [Security boundaries](docs/DEPLOYMENT_SECURITY.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Privacy and unresolved historical branding](docs/PRIVACY.md)
- [CI responsibilities and temporary skipping](docs/CI_ARCHITECTURE.md)
- [Documentation index](docs/README.md)

## Licensing

SAP Lens is proprietary software. All rights reserved; no open-source license is
granted. Use or distribution requires authorization from the applicable rights
holder. See [LICENSE.md](LICENSE.md). Third-party components retain their own licenses.
