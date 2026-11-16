# Release status and checkpoint (Phases 3 to 6)

Durable checkpoint for the next session. Evidence tags as in [README](README.md). Branch `experiment/dotnet-backend`; `work` and `main` are not
touched; CI runs only on pushes to `main` (`validate.yml`), so experiment pushes trigger nothing.

## Release decision: NO-GO (not a Release Candidate)

SAP Lens 2 on .NET is **not** a Release Candidate. The architecture, security boundary, packaging and the migrated areas are sound and tested, but
functional parity is far from complete: **51 of 144** API routes the React UI references are served ([ROUTE_AUDIT.md](ROUTE_AUDIT.md)); account
review, SoD governance, accounts and roles, Employee Directory, backups and reports are not migrated. A release without them would remove audit
functionality users rely on. Windows runtime acceptance has not been performed for the current build.

## Phase status

| Phase | Status | Evidence | What blocks exit |
| --- | --- | --- | --- |
| 3 Integration and stabilization | **In progress; exit criteria not met** | Route audit generated from code (no undocumented 501: every unmigrated route answers `501 not_migrated`, contract-tested); React UI verified against .NET in Chromium for sign-in, Data Sources import, Role Lookup, User Access, Compare Users [M]; Data Health findings equal Python v1 `calculations()` on the small synthetic set (11 of 11) [M]; Dashboard KPIs and distributions identical to Python v1 `overview()` on the 20 000-user set [M]; Saved Filters and Access Packages migrated with the v1 test cases ported [T]; v1 accounts, sessions and roles migrated (Accounts mode is the Server default), React activation, sign-in, User Management and viewer restrictions verified in Chromium [M]; Employee Directory on the versioned dataset pipeline [T][M]; Account Review on the hash-chained decision store with per-user attribution [T][M]; 160 automated tests [T] | 93 routes not migrated; browser tests exist only as ad-hoc scripts in `tools/` and scratch, not a suite |
| 4 Platform and distribution | **Partial** | Reproducible release build (`scripts/build-release.sh`, `.ps1`): React build, tests, self-contained Server win-x64 and linux-x64, Desktop win-x64, build identity stamped (`+<sha>`) and verified, `SHA256SUMS`, `manifest.json` [M on Linux]; Windows service and systemd hosting in code; install/upgrade commands documented | No Windows run of the current build; installer and upgrade/rollback scripts are documented commands, not tested tooling; Desktop installer not built |
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

SoD is 62 v1 routes over about 5 300 lines of Python (`sod_*.py`, `routers/sod*.py`); nothing of it is served yet beyond the analyzer the
equivalence harness covers. Exact order, each a validated commit:

1. **Source fidelity first.** `Sources.Read("sod")` keeps only the 10 core headers; v1 also stores the optional columns (`RISK_NAME`,
   `RISK_DESCRIPTION`, `RISK_IMPACT`, `BUSINESS_PROCESS` and the activity columns, see `RISK_METADATA` in `sod_import.py`) that feed
   `sod_metadata.lookup`. Keep them in the dataset records without changing the core content hash (verify against v1 `build_sod`).
2. **Catalogue store** (`sod_catalogue.py`): local risk and activity metadata with a revision, `observed_definition`/`reviewed_definition`
   fingerprints (`definition_version` = SHA-256 of `json.dumps(definition, sort_keys=True, ensure_ascii=False, separators=(',', ':'))`;
   must stay byte-identical so a migrated `sod-catalogue.json` keeps its review status), retained historical definitions from earlier SoD
   datasets (the .NET dataset history replaces v1's content-addressed snapshots). Routes: `catalogue`, `catalogue/{id}`, `catalogue/{id}` POST,
   `catalogue/bulk`, `catalogue/export`, `catalogue-activities` (list, detail, POST), `appearance`.
3. **Reference library** (`sod_reference.py`) and `metadata` (`sod_metadata.py` lookup and coverage indicators).
4. **Scope and analysis** (`sod_scope.py`, `routers/sod_analysis.py`): filters, evidence, export, on the existing `SodAnalyzer`.
5. **Decisions and reviews** (`sod_decisions.py`, `sod_reviews.py`) on the hash-chained review store (subject types per v1; never rewrite).
6. **Periods** (`sod_periods.py`): frozen snapshots, transitions, approval gates; then **governance** (`sod_governance.py`, 21 routes:
   acceptance, remediation, explorer, matrices) and **reports** (`sod_reports.py`, PDF/DOCX/CSV from the frozen model).

Data compatibility to keep in view: v1 `sod-catalogue.json`, SoD decision and period files must import with fingerprints preserved.

## Remaining work, in dependency order

1. Diagnostics and functional groups (read paths the shell calls). Dashboard, saved filters and Access Packages are done.
2. Per-user identity is done (Accounts mode). Remaining: Windows ACL check of `security/`, adoption procedure for an existing v1
   `accounts.sqlite3` tested on Windows.
3. Account Review follow-ups: position and manager change events between directory imports, functional-group classifications, Desktop reviewer profile.
4. User Access filters that depend on the Employee Directory (functional groups, managers); the directory itself is done.
5. SoD governance (53 routes): catalogue, reference library, decisions, periods, frozen snapshots, remediation, explorer, matrix.
6. Backups (encrypted portable), restore, retention approval; settings export/import/reset.
7. Reports (DOCX, PDF, CSV exports) from frozen models.
8. Then Phase 5 (v1 Playwright suite against .NET, security tests, performance) and Phase 6 (Windows and mobile acceptance).

## Next commands

```bash
git fetch origin && git checkout experiment/dotnet-backend && git pull --ff-only
cd experiments/dotnet-backend && dotnet build SapLens.slnx -c Release && dotnet test tests/SapLens.Tests -c Release --no-build
python -I tools/route_audit.py ../.. ../../docs/experiments/dotnet-backend/ROUTE_AUDIT.md     # regenerate parity after each step
scripts/build-release.sh /tmp/saplens-rc --skip-tests                                          # Linux; Windows: scripts\build-release.ps1 -Output C:\saplens2\release-next
```
