# Release status and checkpoint (Phases 3 to 6)

Durable checkpoint for the next session. Evidence tags as in [README](README.md). Branch `experiment/dotnet-backend`; `work` and `main` are not
touched; CI runs only on pushes to `main` (`validate.yml`), so experiment pushes trigger nothing.

## Release decision: NO-GO (not a Release Candidate), updated 2026-11-17

SAP Lens (.NET, `2.0.0-alpha.1`) is **not** a Release Candidate. Functional migration is complete on Linux: **145 of 145** API routes the React UI
references are served ([ROUTE_AUDIT.md](ROUTE_AUDIT.md)), the v1 data migration passes on synthetic fixtures, and branding, deployment tooling and
installers exist. What blocks a release candidate:

1. Native Windows acceptance of the Server service, Desktop, installers and SSH deployment
   ([WINDOWS_DEPLOYMENT.md](WINDOWS_DEPLOYMENT.md#acceptance-checklist-windows-pending)); nothing ran on Windows from this environment.
2. A v1 migration rehearsal on a copy of real (private) v1 data ([V1_MIGRATION.md](V1_MIGRATION.md)).
3. The installers are uncompiled (Inno Setup runs on Windows only) and unsigned.
4. The promotion to `backend/`, Python retirement and CI change need the gates and authorizations in [BACKEND_PROMOTION.md](BACKEND_PROMOTION.md).

The phase table and validation sections below are the checkpoint of 2026-11-16 and are kept as history.

## Repository exposure audit (2026-11-16)

Scope: all 8 refs (local and `origin`: `experiment/dotnet-backend`, `experiment/go-python`, `main`, `work`), 661 commits, every added line;
tracked files at HEAD; untracked and ignored files of the working tree. Tool: `scripts/check-secrets.py` (and `--history`) plus targeted searches.

| Finding | Severity | Where | Status |
| --- | --- | --- | --- |
| No private key, certificate with key, PFX, real token, API key, connection-string password or credential file has ever been committed | None | All refs | Two `BEGIN ... PRIVATE KEY`/`CERTIFICATE` hits are synthetic test placeholders (`b'A'*100`) and PEM-parsing code; credential-like literals are labelled synthetic test passphrases |
| The private addresses and the public host name of one test environment appeared in documentation, the test launcher defaults, a release README template and tests | Low (infrastructure detail, not a secret: private RFC 1918 addresses and a public DNS name) | Commits `0c04b52`, `848afe0`, `5be1658`, `f407dc4`, `7fc13e7`, only on `experiment/dotnet-backend` (pushed to `origin`); never on `main` or `work` | Removed from HEAD (replaced with reserved examples; launcher values now come from a git-ignored local file). Still present in those historical commits |
| Two reference tools hard-coded the build container's checkout path | Low | `experiments/dotnet-backend/tools/sod_catalogue_reference.py`, `sod_fingerprints_reference.py` | Fixed (relative path, `SAP_LENS_V1_BACKEND` override) |
| `.gitignore` did not cover TLS material, secret files, SQLite databases or machine-specific configuration | Low (preventive) | `.gitignore` | Fixed; covered by `test_repository_privacy` |

No credential or certificate rotation is needed: no secret was exposed. Rewriting history to remove the environment values is **not**
recommended (they are not secrets; a rewrite would force-push a shared branch and invalidate every clone and commit reference); it would need
explicit approval. Release folders are scanned by the build scripts (`check-secrets.py --path`) before they are shared.

## Phase status

| Phase | Status | Evidence | What blocks exit |
| --- | --- | --- | --- |
| 3 Integration and stabilization | **In progress; exit criteria not met** | Route audit generated from code (no undocumented 501: every unmigrated route answers `501 not_migrated`, contract-tested); React UI verified against .NET in Chromium for sign-in, Data Sources import, Role Lookup, User Access, Compare Users [M]; Data Health findings equal Python v1 `calculations()` on the small synthetic set (11 of 11) [M]; Dashboard KPIs and distributions identical to Python v1 `overview()` on the 20 000-user set [M]; Saved Filters and Access Packages migrated with the v1 test cases ported [T]; v1 accounts, sessions and roles migrated (Accounts mode is the Server default), React activation, sign-in, User Management and viewer restrictions verified in Chromium [M]; Employee Directory on the versioned dataset pipeline [T][M]; Account Review on the hash-chained decision store with per-user attribution [T][M]; SoD source metadata and risk catalogue with Python-identical fingerprints and catalogue output [T][M]; SoD reference workbook upload and analysis findings equal to Python v1 on golden fixtures [T]; configuration export/import/reset, reviewer profile, User Access selection/export, Release Roles, diagnostics and legacy compare with Python v1 golden fixtures [T]; 300 automated tests [T]; remaining work in [MIGRATION_BACKLOG.md](MIGRATION_BACKLOG.md); release build embeds the current frontend build incrementally and tests the solution it built (build-integration tests) [T] | 68 routes not migrated (and the sub-routes listed in MIGRATION_BACKLOG.md); browser tests exist only as ad-hoc scripts in `tools/` and scratch, not a suite |
| 4 Platform and distribution | **Partial** | Reproducible release build (`scripts/build-release.sh`, `.ps1`): React build, tests, self-contained single-file Server win-x64 (`SapLens.Api.exe` + `e_sqlite3.dll`) and linux-x64, single-file Desktop win-x64, in a versioned release folder (`server/`, `desktop/`, `symbols/`, `build-manifest.json` with every artifact's SHA-256, `README.txt`, `SHA256SUMS`, `verify-release.ps1`), build identity stamped (`+<sha>`) and verified [M on Linux; single-file layout not yet built on Windows]; Windows service and systemd hosting in code; install/upgrade commands documented | Windows release build validated natively at `ea09de2` (Windows 11 Pro, .NET SDK 10.0.404, Node.js 24.22.3): 238 tests passed, React build, Server win-x64 (117 MB) and Desktop win-x64 (151 MB) published, script exit 0 (output `C:\saplens2\builds\release-ea09de2a849c-20261116-135041`) [M on Windows]. Earlier Windows failures ("user interface is incomplete") came from the separator-sensitive, stale-prone embedded-files manifest, replaced by explicit `SapLensUi/<path>` resources (see [UI_INTEGRATION.md](UI_INTEGRATION.md#how-it-works)). Not yet done on Windows: Server and Desktop startup, HTTPS, application workflows (runtime acceptance); installer and upgrade/rollback scripts are documented commands, not tested tooling; Desktop installer not built |
| 5 Full regression and hardening | **Not started as a phase** | Existing suites: equivalence 68/68 small and large (domain), benchmarks, security and TLS tests, multi-process SQLite tests [T][M] | Depends on Phase 3 parity; the v1 Playwright suite cannot pass until the UI's areas are migrated |
| 6 Release Candidate and acceptance | **Not started** | Windows acceptance commands and checklists exist ([UI_INTEGRATION.md](UI_INTEGRATION.md), [SERVER_NETWORK_ACCESS.md](SERVER_NETWORK_ACCESS.md), [DESKTOP_SERVER_DEPLOYMENT.md](DESKTOP_SERVER_DEPLOYMENT.md)) | No RC exists (see decision); no Windows or mobile acceptance run |

## Validation at the end of the functional migration sprint (2026-11-16)

| Check | Result |
| --- | --- |
| .NET suite (`dotnet test tests/SapLens.Tests -c Release`) | 160/160, two consecutive full runs [T] |
| Equivalence harness vs Python v1 | 68/68 small, 68/68 large [T] |
| EF migrations (`dotnet ef migrations has-pending-model-changes`) | No pending model changes [T] |
| Frontend unit tests, `tsc --noEmit`, production build | 41/41, clean, built [T] (no frontend code changed) |
| ESLint | 0 errors, 115 existing warnings (threshold 115) [T] |
| Browser smoke in Chromium, Accounts mode | Sign-in, Dashboard, Role Lookup, User Access, Account Review, Data Sources, Employee Directory, User Management; only expected 401 before sign-in and 501 for unmigrated `diagnostics` and `functional-groups/options` [M] |
| Docs link check | 0 failures [T] |

A test-isolation defect was found and fixed in this round: the Data Sources "one load at a time" gate was process-wide static state, so two hosts in
one test process refused each other's imports (409). It is now a per-host singleton; three repeated parallel runs passed after the fix, all three failed before.

## Checkpoint: SoD governance (next task)

Done: steps 1 and 2 (optional source columns with v1 content hash; risk and activity catalogue with byte-identical definition fingerprints, metadata
lookup, reference status/reset/template). Golden fixtures in `tests/SapLens.Tests/Fixtures/sod` are produced by `tools/sod_fingerprints_reference.py`
and `tools/sod_catalogue_reference.py` from Python v1.

Next, in order, each a validated commit:

1. Done: reference workbook upload (`SodReferenceWorkbook`, golden fixtures from `tools/sod_reference_fixtures.py`; known difference: a value
   that fails the field rules is refused with a .NET message instead of Pydantic's text). The v1 file migration is done: `SapLens.Cli import-v1-sod --data DIR --catalogue sod-catalogue.json [--reference sod-reference.json]` validates
   against the v1 storage contract, writes both documents in one transaction and never overwrites existing .NET annotations.
2. **Scope and analysis**: `routers/sod_analysis.py` is done (golden fixtures from `tools/sod_analysis_reference.py`). Next: `sod_scope.py` with
   `context`, `filter-options` and `overview`; the React SoD workspace loads these first, so the Explorer and Overview screens can only be
   browser-checked after them (the analysis routes are verified at API level).
3. **Decisions and reviews** (`sod_decisions.py`, `sod_reviews.py`) on the hash-chained review store (subject types per v1; never rewrite).
4. **Periods** (`sod_periods.py`): frozen snapshots, transitions, approval gates; then **governance** (`sod_governance.py`, 21 routes: acceptance,
   remediation, explorer, matrices) and **reports** (`sod_reports.py`, PDF/DOCX/CSV from the frozen model).

## Remaining work, in dependency order

1. Windows acceptance checklist ([WINDOWS_DEPLOYMENT.md](WINDOWS_DEPLOYMENT.md#acceptance-checklist-windows-pending)), including `SapLens2` to `SapLens` migration.
2. Installer compilation and acceptance on Windows (`scripts/build-installers.ps1`); code signing as an authorized release step.
3. v1 migration rehearsal on a copy of real data.
4. Owner decision on Desktop identity (beside v1 or replacing it), then the promotion in [BACKEND_PROMOTION.md](BACKEND_PROMOTION.md).
5. Browser regression of the v1 Playwright suite against the .NET server.

## Next commands

```bash
git fetch origin && git checkout experiment/dotnet-backend && git pull --ff-only
cd experiments/dotnet-backend && dotnet build SapLens.slnx -c Release && dotnet test tests/SapLens.Tests -c Release --no-build
python -I tools/route_audit.py ../.. ../../docs/experiments/dotnet-backend/ROUTE_AUDIT.md     # regenerate parity after each step
scripts/build-release.sh /tmp/saplens-rc --skip-tests                                          # Linux; Windows: scripts\build-release.ps1 -Output C:\saplens\builds
```
