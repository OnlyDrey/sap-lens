# Backend promotion: .NET to `backend/`, Python archived

Decision record for making the .NET implementation the primary backend and archiving SAP Lens 1.

**Status on 2026-11-18: structural promotion performed on `experiment/dotnet-backend`; merge gates still open.** The owner asked for the promotion
after the SAP Lens 2 Server ran as a Windows service behind the reverse proxy. `experiments/dotnet-backend` moved to `backend/`, the Python backend,
desktop and v1 tooling moved to `legacy/v1/` (archived, not deleted), and the documentation moved to `docs/` (v1: `docs/legacy/v1`). Nothing of v1
was deleted. The pre-promotion layout is commit `604f21e`. `work`, `main`, the CI workflows and installed applications were not changed.

## What the promotion did

| Before | After |
| --- | --- |
| `experiments/dotnet-backend/` | `backend/` (solution, `src`, `tests`, `tools`, `scripts`, `installer`) |
| `backend/` (Python FastAPI and desktop) | `legacy/v1/backend/` |
| v1 build, packaging, test and maintenance scripts in `scripts/`, plus `check-workflows.py`, `sync-lucide-catalog.mjs`, `frontend-licenses.mjs` | `legacy/v1/scripts/` |
| `deploy/`, `Dockerfile`, `compose.yml`, `.dockerignore` | `legacy/v1/` |
| `docs/experiments/dotnet-backend/` | `docs/architecture`, `docs/deployment`, `docs/development`, `docs/migration` |
| v1 documentation in `docs/` | `docs/legacy/v1/` (features, data and validation stay: shared behaviour) |
| `scripts/` | Active repository-wide checks only: `check-docs.py`, `check-secrets.py`, `product-version.mjs` |

Kept working: the .NET build, tests, release, installer and deployment scripts (deployment finds the project under `backend/` and, for older
commits, `experiments/dotnet-backend`); the v1 runtime from source and the Playwright suite that uses it; the migration reference tools. A temporary
wrapper keeps the old operator path of `Deploy-SapLens.ps1`. Archived as is: v1 build/packaging tooling and v1 layout-contract tests
([legacy/v1](../../legacy/v1/README.md)).

## Gates

Gates for merging the promoted layout into `work` and `main` (the move itself is done on the branch and is reversible there).

| # | Gate | Status | Evidence or blocker |
| --- | --- | --- | --- |
| 1 | Functional parity of every UI route | Passed on Linux | [ROUTE_AUDIT.md](ROUTE_AUDIT.md), [MIGRATION_MATRIX.md](MIGRATION_MATRIX.md); full .NET suite |
| 2 | v1 data migration (`.slbak` and data directory) | Passed on synthetic fixtures | [V1_MIGRATION.md](V1_MIGRATION.md); `V1DataMigrationTests`. **A rehearsal on a real (private) v1 installation has not run** |
| 3 | Native Windows acceptance: Server service, Desktop, installers, deployment | **Pending** | [WINDOWS_DEPLOYMENT.md](../deployment/WINDOWS_DEPLOYMENT.md#acceptance-checklist-windows-pending), [WINDOWS_TEST_VM.md](../deployment/WINDOWS_TEST_VM.md). Nothing ran on Windows from this environment |
| 4 | CI validates the .NET backend | **Implemented, remote execution pending** | Owner-authorized .NET-first main-only workflow; local contracts and actionlint pass. No GitHub Actions run was requested or triggered |
| 5 | Release path | **Blocked** | The v1 installer (`legacy/v1/deploy/windows/desktop-installer.iss`) packages the Python app; the .NET installers are new and uncompiled |
| 6 | Owner decision: the .NET Desktop replaces v1, or installs beside it | **Open** | The .NET installers use their own AppIds and folders (beside v1). Replacing v1 needs one identity and an upgrade path that runs the v1 migration |
| 7 | Merge into `work`/`main` | Not requested | Requires an approved pull request, after gate 4 |

## Post-migration infrastructure update (2026-11-18)

The default browser/dev backend is .NET with disposable data. Frontend version and
release UI metadata now use `backend/product-version.json`. The main-only .NET CI
workflow and optional Docker definition replace the active v1 pipeline; original
workflow definitions remain archived. See [development](../development/README.md),
[CI](../development/CI.md) and [Docker](../deployment/DOCKER.md) for validation limits.

Remaining v1 dependencies are intentional: synthetic golden fixtures and their
optional Python reference generators, plus historical deployment/rollback lookup.
Four Python-runtime browser specs remain under `legacy/v1/frontend/tests` awaiting
.NET fixture adapters. Two active specs generate workbook/reference fixtures with
Python. Route parity is not a claim of complete browser parity. Historical gates
and migration decisions above are retained; no release approval is implied.

## Before merging

1. Remote validation of the new CI definition (only after an approved merge), and owner decision on Desktop identity (gate 6).
2. Validate: full .NET suite from a clean clone, frontend checks, `check-docs.py`, release build on Linux and Windows, installers on Windows,
   deployment acceptance, and a v1 migration rehearsal on a copy of real data.
3. Merge only with explicit approval; release only with explicit authorization.

Rollback before merge: discard the branch commits since `604f21e`. After merge: revert the merge; `604f21e` restores the pre-promotion layout.
