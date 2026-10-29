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
roles and transaction mappings, investigate user/release assignments, compare
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

## Find your guide

- [Build packages](docs/deployment/BUILD.md): Actions selections, versions, local commands, prerequisites and outputs.
- [Features](docs/features/README.md): investigation, comparisons, review, [SoD](docs/features/SOD.md) and Saved Filters.
- [Data & CSV](docs/data/README.md): four independent sources, formats, replacement and persistence.
- [Configuration](docs/getting-started/CONFIGURATION.md): settings, storage and recovery.
- [Development & Testing](docs/development/README.md): source-mode execution without an EXE and validation.
- [Architecture](docs/architecture/README.md): runtime, API, security and shared components.
- [Synthetic examples](examples/README.md): safe linked test datasets, never automatically imported.
- [Privacy](docs/architecture/PRIVACY.md): unresolved accepted historical branding and repository boundaries.

[GitHub Releases](https://github.com/OnlyDrey/sap-lens/releases) holds release notes
and history. Actions artifacts are available only after successful approved builds
and have finite retention. Local builds never publish releases, tags or commits.

## Licensing

SAP Lens is proprietary software. All rights reserved; no open-source license is
granted. Use or distribution requires authorization from the applicable rights
holder. See [LICENSE.md](LICENSE.md). Third-party components retain their own licenses.
