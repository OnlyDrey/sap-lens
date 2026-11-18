# SAP Lens documentation

Canonical documentation of **SAP Lens** (the .NET backend in `backend/` with the React frontend in `frontend/`). SAP Lens 1 (Python/FastAPI)
is archived; its documentation is under [legacy/v1](legacy/v1/README.md).

| Topic | Guides |
| --- | --- |
| Current architecture | [Architecture overview](architecture/README.md): modules, database, reporting, UI integration, versioning, design system |
| Features and API | [Features](features/README.md), [data and CSV formats](data/README.md), the API the UI uses ([route audit](migration/ROUTE_AUDIT.md)), OpenAPI at `/openapi/v1.json` on a running server |
| Installation and deployment | [Deployment overview](deployment/README.md), [Desktop and Server packages](deployment/DESKTOP_SERVER_DEPLOYMENT.md), [installers](deployment/WINDOWS_DEPLOYMENT.md#installers) |
| Windows service operation | [Windows deployment and service](deployment/WINDOWS_DEPLOYMENT.md), [Windows test VM runbook](deployment/WINDOWS_TEST_VM.md) |
| TLS and reverse proxy | [Network access, TLS and reverse proxy](deployment/SERVER_NETWORK_ACCESS.md), [firewall](deployment/SERVER_NETWORK_ACCESS.md#6-firewall-one-trusted-subnet-one-port-nothing-automatic) |
| Security | [Security boundary and authentication](deployment/SERVER_NETWORK_ACCESS.md), [privacy and secrets](deployment/WINDOWS_DEPLOYMENT.md#privacy-and-secrets) |
| Backup and recovery | [Backup and recovery guide](operations/BACKUP_AND_RECOVERY.md) (archives, recovery key, automatic backups, retention, restore, upgrade confirmation), [storage design](architecture/DATABASE_DESIGN.md#backups-and-retention), [deployment rollback and recovery](deployment/WINDOWS_DEPLOYMENT.md#deployment-sequence), [SAP Lens 1 data migration](migration/V1_MIGRATION.md) |
| Development and testing | [Development](development/README.md) |
| Migration tracking | [Migration index](migration/README.md), [release status](migration/RELEASE_STATUS.md), [promotion and remaining gates](migration/BACKEND_PROMOTION.md) |
| Validation tracker | [Functional areas and manual validation](validation/README.md) |
| Legacy v1 | [SAP Lens 1 documentation](legacy/v1/README.md) |

## Quick start

1. Build: `cd backend && dotnet build SapLens.slnx -c Release` after `cd frontend && npm ci && npm run build` ([development](development/README.md)).
2. Release folder with the Server and Desktop executables: `backend/scripts/build-release.ps1` on Windows or `backend/scripts/build-release.sh`
   on Linux ([packages](deployment/DESKTOP_SERVER_DEPLOYMENT.md)).
3. Run the Server on one machine (`SapLens.Api.exe --data-dir <folder>`, loopback) or, for a network, follow
   [network access](deployment/SERVER_NETWORK_ACCESS.md) and [Windows deployment](deployment/WINDOWS_DEPLOYMENT.md).
4. Import data as described in [data and CSV formats](data/README.md); synthetic examples are in [`examples/`](../examples/README.md).

The feature and data guides describe product behaviour shared by SAP Lens and archived SAP Lens 1 (the same React UI and API contract). Where they link
implementation internals, those links point into the v1 archive; the .NET implementation is described in [architecture](architecture/README.md)
and its parity with v1 in the [migration matrix](migration/MIGRATION_MATRIX.md).

Private CSVs, configuration, exports, certificates and screenshots never belong in Git or build artifacts. Release history is GitHub Releases;
there is no CHANGELOG.md.
