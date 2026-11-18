# Backend promotion: .NET to `backend/`, Python retirement

Decision record for moving `experiments/dotnet-backend` to `backend/` and retiring the Python backend. Status on 2026-11-17: **blocked; prepared,
not performed.** Nothing was moved or removed. The Python backend, its tests, CI and the v1 installer are unchanged and still the production path.

## Gates

The move is irreversible in practice: it replaces the code that CI validates and the v1 installer ships. Every gate must pass first.

| # | Gate | Status | Evidence or blocker |
| --- | --- | --- | --- |
| 1 | Functional parity of every UI route | Passed on Linux | [ROUTE_AUDIT.md](ROUTE_AUDIT.md), [MIGRATION_MATRIX.md](MIGRATION_MATRIX.md); full .NET suite |
| 2 | v1 data migration (`.slbak` and data directory) | Passed on synthetic fixtures | [V1_MIGRATION.md](V1_MIGRATION.md); `V1DataMigrationTests`. **A rehearsal on a real (private) v1 installation has not run** |
| 3 | Native Windows acceptance: Server service, Desktop, installers, deployment | **Pending** | [WINDOWS_DEPLOYMENT.md](../deployment/WINDOWS_DEPLOYMENT.md#acceptance-checklist-windows-pending), [WINDOWS_TEST_VM.md](../deployment/WINDOWS_TEST_VM.md). Nothing ran on Windows from this environment |
| 4 | CI validates the .NET backend | **Blocked by policy** | `validate.yml` runs only on `main`, builds and tests the Python `backend/`. Changing it needs explicit owner authorization (AGENTS.md, CI policy) |
| 5 | Release path | **Blocked** | The v1 installer (`deploy/windows/desktop-installer.iss`, `scripts/build-desktop-installer.ps1`) packages the Python app; the .NET installers are new and uncompiled |
| 6 | Owner decision: the .NET Desktop replaces v1, or installs beside it | **Open** | The .NET installers use their own AppIds and folders (beside v1). Replacing v1 needs one identity and an upgrade path that runs the v1 migration |
| 7 | Merge into `work`/`main` | Not requested | Requires an approved pull request |

## Dependencies on the Python `backend/` today

| Consumer | Dependency | Change at promotion |
| --- | --- | --- |
| `.github/workflows/validate.yml`, `scripts/run-tests.py`, `scripts/test-map.json` | Python install, `ruff check backend`, `unittest` in `backend/tests` | Replace with `dotnet build`/`dotnet test` (authorized CI change) |
| `experiments/dotnet-backend/scripts/build-release.ps1`, `build-release.sh` | `backend/resources/product-version.json` (v1's version, recorded as `ui_source_version` only) | Read the UI version from `frontend/package.json` instead |
| `scripts/product-version.mjs`, `frontend/package.json` | Mirrors v1's product version | Mirror `product-version.json` of the .NET backend |
| `experiments/dotnet-backend/tools/python_reference.py`, `route_audit.py` | Runs or reads v1 Python code for equivalence and the route audit | Keep in a frozen v1 reference (tag or archive) before removal |
| `backend/tests/test_repository_privacy.py`, `.gitignore` | Name `experiments/dotnet-backend` | Update paths |
| v1 installer and launcher (`deploy/windows`, `scripts/build_system`) | Package `backend/` | Retire with v1, after gate 6 |
| Migration fixtures (`tests/SapLens.Tests/Fixtures/v1-data`, `Fixtures/backups`) | Written by the real v1 code | Keep; they are the evidence for the v1 import and must not be regenerated without v1 |

## Prepared (done, reversible)

- The deployment scripts locate the .NET project under `experiments/dotnet-backend` or `backend` (`Get-SL2ProjectRoot`; the SSH bootstrap
  archives whichever the locked commit has), so the move does not break deployments of earlier or later commits.
- Product branding, executable names, service name and installer identities are final ([VERSIONING.md](../architecture/VERSIONING.md)) and independent of the folder.
- Build, release and installer scripts resolve paths relative to their own location; only the two lines above that read v1's version file change.

## Promotion procedure (after every gate passes and the owner authorizes it)

1. Tag the last Python-backend commit (`v1-final` or as the owner names it) and archive `backend/` with its tests: the v1 reference stays reproducible.
2. In one pull request to `work`: `git rm -r backend` (Python), `git mv experiments/dotnet-backend backend`, update the dependency rows above,
   `docs/experiments/dotnet-backend` to `docs/backend`, and the CI workflow and its contract (`scripts/check-workflows.py`, `backend/tests/test_workflows.py`
   moves to a .NET test).
3. Validate: full .NET suite from a clean clone, frontend checks, `check-docs.py`, release build on Linux and Windows, installers on Windows,
   deployment acceptance, and a v1 migration rehearsal on a copy of real data.
4. Merge only with explicit approval; release only with explicit authorization.

Rollback before merge: close the pull request. After merge: revert the merge commit; the tag from step 1 restores the Python backend.
