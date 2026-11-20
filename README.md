<!-- LOGO -->
<h1>
<p align="center">
  <img src="assets/sap-lens.png" alt="Logo" width="200">
  <br>AuthLens
</h1>
  <p align="center">
    <b>SAP S/4HANA</b> · Role analysis and comparison tool for Company's internal SAP authorisation landscape.
    <br />
    <br />
    <a href="docs/README.md">Documentation</a>
    ·
    <a href="docs/README.md#quick-start">Quick Start</a>
    ·
    <a href="docs/deployment/README.md">Build &amp; Deployment</a>
    ·
    <a href="docs/features/README.md">Features</a>
    ·
    <a href="docs/development/README.md">Development</a>
    ·
    <a href="https://github.com/OnlyDrey/sap-lens/releases">GitHub Releases</a>
  </p>
</p>

---

AuthLens is a local-first SAP investigation and access-review application. Browse roles and transaction mappings, propose access packages,
investigate user/release assignments, compare users, enrich identities with optional Employee Directory data, record Account Review decisions,
and investigate and review potential Segregation of Duties conflicts with frozen periods and DOCX/PDF reports. Role-derived transaction coverage
is investigation evidence, not proof of effective authorization or license consumption. No direct SAP connection or third-party data-upload
service is required.

## Implementation

AuthLens was previously named SAP Lens; the repository keeps its name (`sap-lens`). The implementation is an ASP.NET Core (.NET 10) backend in [`backend/`](backend) serving the React/Vite
frontend in [`frontend/`](frontend), as a Windows service or console **Server** (browser access over HTTPS) and a WebView2 **Desktop** for one user.
Product version `2.0.0-alpha.1` (pre-release; [versioning](docs/architecture/VERSIONING.md)).

| Area | Status |
| --- | --- |
| UI and API | Every API route the React UI calls is served by .NET (145 of 145, [route audit](docs/migration/ROUTE_AUDIT.md)); parity per area in the [migration matrix](docs/migration/MIGRATION_MATRIX.md) |
| Data | SQLite system of record, immutable evidence and review history, encrypted backups ([database design](docs/architecture/DATABASE_DESIGN.md)) |
| SAP Lens data | A backup (`.slbak`) of a SAP Lens installation restores into a fresh AuthLens installation (`authlens.sqlite3`), also on another machine ([migration from SAP Lens](docs/deployment/WINDOWS_DEPLOYMENT.md#migrating-from-sap-lens)); tested on synthetic data |
| SAP Lens 1 data | Preview, verified migration and rollback of a v1 data directory or `.slbak` backup ([procedure](docs/migration/V1_MIGRATION.md)); tested on synthetic fixtures |
| Windows Server | The `AuthLens` Windows service under `C:\ProgramData\AuthLens`, behind a reverse proxy over HTTPS; install, update and restore with verified releases and rollback ([Windows deployment](docs/deployment/WINDOWS_DEPLOYMENT.md)) |
| Pending | Parts of the native Windows acceptance checklist, compiled and signed installers, deployment-specific functional acceptance of migrated data, native installer acceptance ([release status](docs/migration/RELEASE_STATUS.md)) |

AuthLens is not declared feature-complete or production-certified: see [release status](docs/migration/RELEASE_STATUS.md) and
[backend promotion](docs/migration/BACKEND_PROMOTION.md) for what is verified and what is not.

## Repository layout

| Path | Content |
| --- | --- |
| [`backend/`](backend) | AuthLens .NET solution (`src/`, `tests/`), build, release, installer and deployment scripts (`scripts/`, `installer/`), migration reference tools (`tools/`) |
| [`frontend/`](frontend) | React/Vite UI, shared by AuthLens and archived v1 |
| [`docs/`](docs/README.md) | Documentation (canonical for AuthLens) |
| [`scripts/`](scripts/README.md) | Repository-wide checks (documentation links, secrets, workflow contracts, frontend version and icon catalogue) |
| [`examples/`](examples/README.md), [`assets/`](assets) | Synthetic example data; product icon and logo |

## Quick commands

```bash
npm --prefix frontend ci && npm --prefix frontend run build
dotnet build backend/AuthLens.slnx -c Release
dotnet test backend/tests/AuthLens.Tests -c Release --no-build --filter "Category!=Publish"
backend/scripts/build-release.sh <output>                     # Linux; Windows: backend\scripts\build-release.ps1 -Output <folder>
```

Details: [development](docs/development/README.md), [deployment](docs/deployment/README.md).

## Security and operations

* The Server listens on loopback unless `--network` is given; network mode requires HTTPS, an explicit host allow-list and, behind a reverse
  proxy, an explicit trusted-proxy list ([network access and security](docs/deployment/SERVER_NETWORK_ACCESS.md)). The Desktop listens on loopback only.
* Private CSVs, exports, logs, configuration, certificates and deployment settings never belong in Git or in build artifacts; the repository ships
  synthetic [examples](examples/README.md) only.
* Backups are encrypted and verified; every deployment takes and verifies a backup before it stops the service.

## SAP Lens 1 (legacy)

The Python/FastAPI implementation is archived outside this repository (a separate archive; commit `604f21e` is the last one that contains it).
Its documentation stays in [`docs/legacy/v1/`](docs/legacy/v1/README.md) for reference. It receives no new features, nothing in this
repository depends on it, and installed v1 applications are not changed by the .NET tooling.

## Licensing

AuthLens is proprietary software. All rights reserved; no open-source license is
granted. Use or distribution requires authorization from the applicable rights
holder. See [LICENSE.md](LICENSE.md). Third-party components retain their own licenses.
