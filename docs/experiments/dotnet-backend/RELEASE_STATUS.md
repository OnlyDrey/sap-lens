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
