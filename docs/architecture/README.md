# Architecture (AuthLens)

| Document | Content |
| --- | --- |
| [TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md) | Modular monolith: Domain, Persistence, Application, Api (Server host), Desktop, Documents; module boundaries, request and job flows |
| [DATABASE_DESIGN.md](DATABASE_DESIGN.md) | SQLite system of record: schema, invariants, connections and file handles, concurrency, migrations, backups and retention |
| [REPORTING_ARCHITECTURE.md](REPORTING_ARCHITECTURE.md) | DOCX/PDF/CSV reports rendered from frozen models |
| [UI_INTEGRATION.md](UI_INTEGRATION.md) | How the .NET host embeds and serves the production React build, compatibility API, authentication |
| [VERSIONING.md](VERSIONING.md) | Product version, channel, build identity and naming |
| [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md), [COMPONENTS.md](COMPONENTS.md), [APPEARANCE.md](APPEARANCE.md), [NAVIGATION.md](NAVIGATION.md) | Frontend design system, shared components, theming and navigation (shared by AuthLens and archived v1) |

Security boundary, TLS, host and origin checks, trusted proxies and authentication: [network access](../deployment/SERVER_NETWORK_ACCESS.md).
SAP Lens 1 architecture (FastAPI runtime, desktop host, storage and revisions, SoD modules): [legacy v1 architecture](../archive/v1/architecture/README.md).
