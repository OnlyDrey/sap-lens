# Migration tracking: SAP Lens 1 to SAP Lens

Decisions, evidence and progress of the migration from the Python/FastAPI implementation (archived outside the repository) to the .NET
backend in [`backend/`](../../backend). Current product documentation is in [docs](../README.md); these documents keep the history and the open items.

Evidence tags used in these documents: **[M]** measured on Linux x64 (4 vCPU, 15 GiB), **[C]** read from code, **[T]** proven by an automated
test, **[U]** not verified. Documents written before the promotion refer to `experiments/dotnet-backend`, which is now `backend/`, and to the
Python `backend/`, which was archived (last present at commit `604f21e`).

Windows service/directory preparation is a separate acceptance gate from the completed v1 data import. Follow
[migration preparation](../deployment/WINDOWS_DEPLOYMENT.md#preparing-the-migration) and
[Windows script validation](../deployment/WINDOWS_DEPLOYMENT.md#windows-script-validation); preserve existing migration evidence and do not
repeat an activated v1 import. A passing Pester run on another Windows workstation does not establish the VM's release, ACL or preflight state.

## Documents

| Document | Content |
| --- | --- |
| [MIGRATION_MATRIX.md](MIGRATION_MATRIX.md) | Migration completion matrix: every v1 area with its .NET implementation, status, parity, tests, dependencies, remaining work and MIG id (source of truth) |
| [FEATURE_PARITY.md](FEATURE_PARITY.md) | Phase 0 inventory: every UI area, v1 implementation, .NET status, gaps, complexity, tests |
| [ROUTE_AUDIT.md](ROUTE_AUDIT.md) | Generated route-by-route status of every API route the React UI references |
| [RELEASE_STATUS.md](RELEASE_STATUS.md) | Phase 3 to 6 status, release decision (NO-GO), remaining work, next commands |
| [UI_INTEGRATION.md](../architecture/UI_INTEGRATION.md) | The production React UI served by .NET: build, adapter, authentication, Windows VM commands |
| [PHASE1_DECISION.md](PHASE1_DECISION.md) | Recommendation (CONDITIONAL GO), evidence, blockers, open questions |
| [ARCHITECTURE_ASSESSMENT.md](ARCHITECTURE_ASSESSMENT.md) | What v1 is, read from source and tests; what a C# backend must preserve |
| [DEPENDENCY_MAPPING.md](DEPENDENCY_MAPPING.md) | Every Python runtime dependency classified: replace, redesign, or keep isolated |
| [TARGET_ARCHITECTURE.md](../architecture/TARGET_ARCHITECTURE.md) | Modular monolith, module boundaries, request and job flows |
| [DATABASE_DESIGN.md](../architecture/DATABASE_DESIGN.md) | SQLite schema, write coordination, immutability, migrations, backups |
| [FUNCTIONAL_EQUIVALENCE.md](FUNCTIONAL_EQUIVALENCE.md) | Python v1 versus .NET on identical synthetic data: 68/68 small, 68/68 large |
| [PERFORMANCE_BENCHMARK.md](PERFORMANCE_BENCHMARK.md) | Algorithm and service benchmarks, concurrency under import, memory, sizes |
| [DESKTOP_SERVER_DEPLOYMENT.md](../deployment/DESKTOP_SERVER_DEPLOYMENT.md) | Desktop (WebView2) and Server builds, run commands, packaging assessment |
| [SERVER_NETWORK_ACCESS.md](../deployment/SERVER_NETWORK_ACCESS.md) | Server configuration reference (every option, environment variable, default and refusal), trusted-LAN HTTPS, authentication review, firewall, Windows service and systemd deployment |
| [VERSIONING.md](../architecture/VERSIONING.md) | Product version (`2.0.0-alpha.N`, independent of v1), channel and build identity; where each appears; release policy |
| [WINDOWS_TEST_VM.md](../deployment/WINDOWS_TEST_VM.md) | Windows test VM runbook: native release build, test launcher (`scripts/start-server-test.ps1`), manual start, HTTPS and TLS checks, firewall, logs, restart, and the acceptance levels (build is not runtime acceptance) |
| [MIGRATION_STRATEGY.md](MIGRATION_STRATEGY.md) | How v1 data, decisions and evidence move, with rollback |
| [WINDOWS_DEPLOYMENT.md](../deployment/WINDOWS_DEPLOYMENT.md) | SSH-driven Windows test deployment (build, verify, back up, switch, verify, roll back, recover), `SapLens2` to `sap-lens` service migration, Desktop and Server installers, acceptance checklist |
| [BACKEND_PROMOTION.md](BACKEND_PROMOTION.md) | Promotion of the .NET backend to `backend/` and retirement of the Python backend: gates, what is prepared, what is blocked |
| [V1_MIGRATION.md](V1_MIGRATION.md) | Administrator procedure: SAP Lens 1 `.slbak` or data directory to SAP Lens (Windows PowerShell), verification and rollback |

