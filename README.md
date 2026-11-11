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
    <a href="docs/getting-started/QUICK_START.md">Quick Start</a>
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

SAP Lens is a local-first SAP investigation and access-review application. Browse
roles and transaction mappings, propose access packages, investigate user/release assignments, compare
users, enrich identities with optional Employee Directory data, record Account
Review decisions, and investigate and review potential Segregation of Duties
conflicts with frozen periods and DOCX/PDF reports. Role-derived transaction coverage is investigation evidence,
not proof of effective authorization or license consumption. No direct SAP connection
or third-party data-upload service is required.

## Get started

Choose [Quick Start](docs/getting-started/QUICK_START.md), then a deployment:

| Target | Interface | Primary guide |
| --- | --- | --- |
| Windows Desktop x64 | EXE / WebView2; portable or per-user installer | [Desktop](docs/deployment/WINDOWS_DESKTOP.md) |
| Windows Server Service x64 | Headless WinSW/SCM, browser | [Service](docs/deployment/WINDOWS_SERVICE.md) |
| Linux Docker amd64 | Offline image / Compose, browser | [Docker](docs/deployment/LINUX_DOCKER.md) |
| Linux Native/systemd x64 | Python 3.12, systemd or manual browser process | [Native](docs/deployment/LINUX_NATIVE.md) |

All targets share the application and CSV lifecycle. Linux client support is
browser-based; no standalone Linux GUI is supplied. Server deployments default to
loopback and require an explicit [security boundary](docs/deployment/SECURITY.md)
for remote access. Packaging support does not establish native production acceptance;
see the [validation matrix](docs/deployment/README.md#validation-status).

## How it works

A FastAPI backend and a React frontend run on one machine. Role, user, Employee Directory and SoD CSV files are imported as immutable, content-addressed
snapshots (Static sources once, Dynamic sources on every refresh); an optional, rebuildable SQLite store and fingerprints keep restarts and refreshes fast. Review
decisions are bound to the evidence they were made on and are rejected, never overwritten, when that evidence or the dataset changed. See
[Storage, revisions and consistency](docs/architecture/STORAGE_AND_REVISIONS.md).

## Development and release status

Build/package verification, runtime smoke and native host acceptance are separate
facts. Windows SCM evidence can supplement an older build manifest without
rewriting it; see [release verification](docs/deployment/RELEASES.md).
Individual server accounts/roles exist, but session expiration, optional TOTP and
complete multi-reviewer approval separation remain requirements gaps; see
[security boundaries](docs/deployment/SECURITY.md). No blanket production
certification is implied by a successful build.

## Security and operations

* The desktop application listens on `127.0.0.1` only; server mode defaults to loopback and needs an explicit [security boundary](docs/deployment/SECURITY.md) for remote access.
* Private CSVs, exports, logs and configuration never belong in Git or in build artifacts; the repository ships synthetic [examples](examples/README.md) only.
* Old data is cleaned up by approval-gated [retention](docs/operations/DATA_RETENTION.md); [backups](docs/deployment/BACKUP_RESTORE.md) are verified before use.
* Native Windows (SCM, WebView2, UNC) and real systemd acceptance are not established by the Linux validation; see the [validation matrix](docs/deployment/README.md#validation-status).

## Find your guide

- [Build packages](docs/BUILD.md): Actions selections, versions, local commands, prerequisites and outputs.
- [Features](docs/features/README.md): investigation, comparisons, review, [SoD](docs/features/SOD.md) and Saved Filters.
- [Data & CSV](docs/data/README.md): four independent sources, formats, replacement and persistence.
- [Configuration](docs/getting-started/CONFIGURATION.md): settings, storage and recovery.
- [Development & Testing](docs/development/README.md): source-mode execution without an EXE and validation.
- [Architecture](docs/architecture/README.md): runtime, storage and revisions, API, security and shared components.
- [Operations](docs/operations/README.md): data retention, backup and restore, recovery.
- [Scripts](scripts/README.md): which build, validation and maintenance scripts to run.
- [Synthetic examples](examples/README.md): safe linked test datasets, never automatically imported.
- [Privacy](docs/architecture/PRIVACY.md): unresolved accepted historical branding and repository boundaries.

[GitHub Releases](https://github.com/OnlyDrey/sap-lens/releases) holds release notes
and history. Actions artifacts are available only after successful approved builds
and have finite retention. Local builds never publish releases, tags or commits.

Local Windows build entry point (from the repository root):

```powershell
.\scripts\build.ps1 -Mode quick
.\scripts\build.ps1 -Mode build -Platform windows -Target desktop
```

Version resolution, prerequisites, optional service packaging and output paths are
in the [build guide](docs/BUILD.md#commands).

## Licensing

SAP Lens is proprietary software. All rights reserved; no open-source license is
granted. Use or distribution requires authorization from the applicable rights
holder. See [LICENSE.md](LICENSE.md). Third-party components retain their own licenses.
