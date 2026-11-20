# Release status and checkpoint (Phases 3 to 6)

## Windows continuation: current assessment (2026-11-20)

**NOT READY.** Implementation and final validation are in progress. This section supersedes older dated status claims below; those sections remain historical evidence.

The checkout safely fast-forwarded from 814c88d to the expected origin 50bed6d. Pre-existing edits were preserved in a retained stash, reconciled through the AuthLens renames, and useful import-policy/test fixes retained. Six obsolete untracked drafts/helpers are preserved byte-for-byte with a hash manifest in ignored test artifacts. No push, merge, workflow dispatch, product-version or visual-identity change is authorized or performed.

Implemented corrections: managed immutable CSV copies bound to dataset metadata and the existing encrypted backup engine; portable restore with verified local source paths and cleared historical host paths; per-job import checks and empty-import protection; stable Desktop/profile reviewer attribution; SAP revisions independent of SoD; safe shared download filename parsing and Windows workbook paths; isolated Desktop data/log/profile/mutex overrides. The Server installer refuses unsafe in-place updates before touching services/files. Installer-managed update/rollback remains incomplete, not certified.

| Check | Windows continuation result |
| --- | --- |
| Native solution build (Windows 11 Enterprise, .NET SDK 10.0.204) | Passed, zero warnings/errors |
| Complete .NET checkpoint | 470 total: 468 passed, 2 failed; startup deadline under concurrent fixtures and obsolete duplicate-file expectation. Corrected complete Startup/DataSources classes: 13 passed. Affected import/backup/review/Desktop/installer selection: 75 passed. Final native publish/portable-restore group: 22 passed, including Windows Server and Desktop executable checks |
| Pester 5.9.1 on Windows PowerShell 5.1 | 182 total: 171 passed, 0 failed, 11 skipped; zero failed containers. Nine Linux-only launcher cases, two elevated native restore cases |
| PowerShell 5.1 parser | 23 active scripts, zero errors; PowerShell 7 unavailable |
| Frontend unit/type/lint | 46 unit tests passed; type check passed; lint passed with 66 existing warnings, zero errors |
| Complete browser checkpoint | 865 total: 862 passed, 3 failed, 0 skipped (73.24 minutes), one worker, isolated loopback host/storage. All three are identified fixture defects. First complete six-spec correction run: 45 passed, 1 failed; directory persistence and confirmation race fixed. CSV source-count fixture depended on retained optional-source history; explicit source seeding fixed it. Final complete CSV spec: 8 passed. The formerly state-dependent CSV case also passed 3/3 repeated checks. All original browser failures have passing scoped verification; this is not a claimed clean single full run. |
| Repository checks | Docs: 100 files/zero failures; Python contracts 7/7; Node contracts 5/5; structure/workflow/Ruff/Lucide/whitespace pass; secret scan zero findings |
| Dependency audit | NuGet and production npm: zero reported vulnerabilities |
| Bash deployment harness | Syntax passed; execution refused with infrastructure exit 2 because PowerShell 7 is unavailable |
| Native release verification/installers | Pending release build; Inno Setup 6 compiler not installed |

Release gates still open: compiled installer fresh/update/rollback acceptance; elevated SCM registration/start/restart and privileged ACL restore; explicit reboot authorization; native WebView2 interactions/downloads; a supplied copy of a real private SAP Lens backup and its recovery key. This Windows 11 Enterprise workstation (build 26200) has no elevated token and no protected SAP Lens service registered; it is not the production VM acceptance result. No legacy service, installation, database, certificate, backup, key or junction was modified. A synthetic backup pass cannot replace real-data acceptance.

Local commits: 679897f (archive/product references), 33cdfb8 (Windows repository checks), 26ee870 (managed imports/portable restore/reviewer correctness); d9735eb (isolated native executable checks and safe installer refusal); 63fb450 (download parsing and deterministic browser fixtures); package/evidence checkpoint pending. No push has occurred. The historical per-file rename inventory describes the upstream checkpoint, not final Windows counts. License changes are exactly SAP Lens -> AuthLens product references; legal terms and ownership wording are unchanged. V1 documents moved intact to docs/archive/v1; required backup readers, migration IDs, golden fixtures and optional reference generators remain.


Durable checkpoint for the next session. Evidence tags as in [README](README.md). Branch `experiment/dotnet-backend`; `work` and `main` are not
touched; CI runs only on pushes to `main` (`validate.yml`), so experiment pushes trigger nothing.

## Post-migration infrastructure checkpoint (2026-11-18)

.NET is now the default browser/dev host, active frontend version metadata uses
`backend/product-version.json` and CI definitions are .NET-first/main-only. An optional Docker deployment was added in this round and
**removed on 2026-11-18** (no supported use case; its image build was never verified). This is infrastructure stabilization, not production
certification. Pester acquisition is blocked by PowerShell Gallery access.
Native Windows service/Desktop/installers and real-data migration remain separate
acceptance gates. Consolidated local evidence is recorded below after validation.
The earlier dated tables below remain historical evidence.

## Release decision: NO-GO (not a Release Candidate), updated 2026-11-17

AuthLens (.NET, `2.0.0-alpha.1`) is **not** a Release Candidate. Functional migration is complete on Linux: **145 of 145** API routes the React UI
references are served ([ROUTE_AUDIT.md](ROUTE_AUDIT.md)), the v1 data migration passes on synthetic fixtures, and branding, deployment tooling and
installers exist. What blocks a release candidate:

1. Native Windows acceptance of the Server service, Desktop, installers and SSH deployment
   ([WINDOWS_DEPLOYMENT.md](../deployment/WINDOWS_DEPLOYMENT.md#acceptance-checklist-windows-pending)); nothing ran on Windows from this environment.
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
| Two reference tools hard-coded the build container's checkout path | Low | `backend/tools/sod_catalogue_reference.py`, `sod_fingerprints_reference.py` | Fixed (relative path, `SAP_LENS_V1_BACKEND` override) |
| `.gitignore` did not cover TLS material, secret files, SQLite databases or machine-specific configuration | Low (preventive) | `.gitignore` | Fixed; covered by `test_repository_privacy` |

No credential or certificate rotation is needed: no secret was exposed. Rewriting history to remove the environment values is **not**
recommended (they are not secrets; a rewrite would force-push a shared branch and invalidate every clone and commit reference); it would need
explicit approval. Release folders are scanned by the build scripts (`check-secrets.py --path`) before they are shared.

## Phase status

| Phase | Status | Evidence | What blocks exit |
| --- | --- | --- | --- |
| 3 Integration and stabilization | **In progress; exit criteria not met** | Route audit generated from code (no undocumented 501: every unmigrated route answers `501 not_migrated`, contract-tested); React UI verified against .NET in Chromium for sign-in, Data Sources import, Role Lookup, User Access, Compare Users [M]; Data Health findings equal Python v1 `calculations()` on the small synthetic set (11 of 11) [M]; Dashboard KPIs and distributions identical to Python v1 `overview()` on the 20 000-user set [M]; Saved Filters and Access Packages migrated with the v1 test cases ported [T]; v1 accounts, sessions and roles migrated (Accounts mode is the Server default), React activation, sign-in, User Management and viewer restrictions verified in Chromium [M]; Employee Directory on the versioned dataset pipeline [T][M]; Account Review on the hash-chained decision store with per-user attribution [T][M]; SoD source metadata and risk catalogue with Python-identical fingerprints and catalogue output [T][M]; SoD reference workbook upload and analysis findings equal to Python v1 on golden fixtures [T]; configuration export/import/reset, reviewer profile, User Access selection/export, Release Roles, diagnostics and legacy compare with Python v1 golden fixtures [T]; 300 automated tests [T]; remaining work in [MIGRATION_BACKLOG.md](MIGRATION_BACKLOG.md); release build embeds the current frontend build incrementally and tests the solution it built (build-integration tests) [T] | 68 routes not migrated (and the sub-routes listed in MIGRATION_BACKLOG.md); browser tests exist only as ad-hoc scripts in `tools/` and scratch, not a suite |
| 4 Platform and distribution | **Partial** | Reproducible release build (`scripts/build-release.sh`, `.ps1`): React build, tests, self-contained single-file Server win-x64 (`AuthLens.Api.exe` + `e_sqlite3.dll`) and linux-x64, single-file Desktop win-x64, in a versioned release folder (`server/`, `desktop/`, `symbols/`, `build-manifest.json` with every artifact's SHA-256, `README.txt`, `SHA256SUMS`, `verify-release.ps1`), build identity stamped (`+<sha>`) and verified [M on Linux; single-file layout not yet built on Windows]; Windows service and systemd hosting in code; install/upgrade commands documented | Windows release build validated natively at `ea09de2` (Windows 11 Pro, .NET SDK 10.0.404, Node.js 24.22.3): 238 tests passed, React build, Server win-x64 (117 MB) and Desktop win-x64 (151 MB) published, script exit 0 (output `C:\saplens2\builds\release-ea09de2a849c-20261116-135041`) [M on Windows]. Earlier Windows failures ("user interface is incomplete") came from the separator-sensitive, stale-prone embedded-files manifest, replaced by explicit `AuthLensUi/<path>` resources (see [UI_INTEGRATION.md](../architecture/UI_INTEGRATION.md#how-it-works)). Not yet done on Windows: Server and Desktop startup, HTTPS, application workflows (runtime acceptance); installer and upgrade/rollback scripts are documented commands, not tested tooling; Desktop installer not built |
| 5 Full regression and hardening | **Not started as a phase** | Existing suites: equivalence 68/68 small and large (domain), benchmarks, security and TLS tests, multi-process SQLite tests [T][M] | Depends on Phase 3 parity; the v1 Playwright suite cannot pass until the UI's areas are migrated |
| 6 Release Candidate and acceptance | **Not started** | Windows acceptance commands and checklists exist ([UI_INTEGRATION.md](../architecture/UI_INTEGRATION.md), [SERVER_NETWORK_ACCESS.md](../deployment/SERVER_NETWORK_ACCESS.md), [DESKTOP_SERVER_DEPLOYMENT.md](../deployment/DESKTOP_SERVER_DEPLOYMENT.md)) | No RC exists (see decision); no Windows or mobile acceptance run |

## Validation at the end of the functional migration sprint (2026-11-16)

| Check | Result |
| --- | --- |
| .NET suite (`dotnet test tests/AuthLens.Tests -c Release`) | 160/160, two consecutive full runs [T] |
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
lookup, reference status/reset/template). Golden fixtures in `tests/AuthLens.Tests/Fixtures/sod` are produced by `tools/sod_fingerprints_reference.py`
and `tools/sod_catalogue_reference.py` from Python v1.

Next, in order, each a validated commit:

1. Done: reference workbook upload (`SodReferenceWorkbook`, golden fixtures from `tools/sod_reference_fixtures.py`; known difference: a value
   that fails the field rules is refused with a .NET message instead of Pydantic's text). The v1 file migration is done: `AuthLens.Cli import-v1-sod --data DIR --catalogue sod-catalogue.json [--reference sod-reference.json]` validates
   against the v1 storage contract, writes both documents in one transaction and never overwrites existing .NET annotations.
2. **Scope and analysis**: `routers/sod_analysis.py` is done (golden fixtures from `tools/sod_analysis_reference.py`). Next: `sod_scope.py` with
   `context`, `filter-options` and `overview`; the React SoD workspace loads these first, so the Explorer and Overview screens can only be
   browser-checked after them (the analysis routes are verified at API level).
3. **Decisions and reviews** (`sod_decisions.py`, `sod_reviews.py`) on the hash-chained review store (subject types per v1; never rewrite).
4. **Periods** (`sod_periods.py`): frozen snapshots, transitions, approval gates; then **governance** (`sod_governance.py`, 21 routes: acceptance,
   remediation, explorer, matrices) and **reports** (`sod_reports.py`, PDF/DOCX/CSV from the frozen model).

## Remaining work, in dependency order

1. Windows acceptance checklist ([WINDOWS_DEPLOYMENT.md](../deployment/WINDOWS_DEPLOYMENT.md#acceptance-checklist-windows-pending)), including the
   AuthLens scenarios (fresh install, restore of a SAP Lens backup, earlier services untouched). The service-to-service migration
   (`SapLens2` to `sap-lens`) and its preflight were removed on 2026-11-20: SAP Lens data reaches AuthLens only through a fresh installation plus
   [restore](../deployment/WINDOWS_DEPLOYMENT.md#migrating-from-sap-lens), so the VM preflight blockers of 2026-11-19 no longer gate it.
   Restore, legacy-archive compatibility and fail-safe database handling are tested on Linux only.
2. Installer compilation and acceptance on Windows (`scripts/build-installers.ps1`); code signing as an authorized release step.
3. v1 migration rehearsal on a copy of real data.
4. Owner decision on Desktop identity (beside v1 or replacing it), then the promotion in [BACKEND_PROMOTION.md](BACKEND_PROMOTION.md).
5. Browser regression against the .NET server. Complete run on 2026-11-20 (Linux, one worker, 36 min): **836 passed, 17 failed** of 853
   (2026-11-18: 532 passed, 327 failed). The specs now set source files through Data Sources activation ([browser tests](../development/README.md#browser-tests)),
   and the run found two application defects, both fixed: `/api/access/*` ignored a disabled User–Role Mapping, and every source activation
   left Settings with phantom unsaved changes. Two of the 17 were test defects, fixed and re-run afterwards (`desktop` app information,
   `ui-polish-actions` locator). Remaining 15, classified and open:
   - **.NET behaviour differences:** `sod-integration` (a SoD-only refresh advances the SAP part of `data_revision`), `csv-lifecycle` (3:
     refresh result counts, and the Employee Directory import check holds a 48 % drop the spec expects to pass).
   - **Missing functionality:** `functional-groups-members` (confirmation attribution shows the seeding actor, not the acting reviewer).
   - **Not yet investigated:** `navigation-modules` (6: first-run data-source alert text, two focus checks, two timeouts), `sod-metadata` (timeout),
     `startup-recovery` (session-token replacement navigation count).

## Next commands

```bash
git fetch origin && git checkout experiment/dotnet-backend && git pull --ff-only
cd backend && dotnet build AuthLens.slnx -c Release && dotnet test tests/AuthLens.Tests -c Release --no-build
python -I tools/route_audit.py .. ../docs/migration/ROUTE_AUDIT.md     # regenerate parity after each step
scripts/build-release.sh /tmp/authlens-rc --skip-tests                                          # Linux; Windows: scripts\build-release.ps1 -Output C:\AuthLens-Build\builds
```

## Infrastructure stabilization evidence (2026-11-18)

Starting source: `6fa0c7f0b1b9fbeb3727cec5b9597d33469665a3` on
`experiment/dotnet-backend`. Product version remains `2.0.0-alpha.1`.

| Phase | Implementation and validation | Commit/checkpoint |
| --- | --- | --- |
| A — Playwright/dev | .NET is default; disposable Desktop-capability host, owned child cleanup, occupied ports fail closed. Python-runtime specs were removed with SAP Lens 1 (2026-11-18); two active reference-generator specs still need optional Python. No claim of complete browser parity | `2d5741f` |
| B — Versioning | Frontend manifests, generated identity and release UI metadata use `backend/product-version.json`; v1 metadata unchanged | `45579d6` |
| C — Docker (removed 2026-11-18: no supported use, image never built) | Multi-stage Node 24/.NET 10, non-root app user, persistent volume, mandatory TLS/private bind, exact-host readiness and loopback-only published port. Compose/shell/contracts pass; actual image build blocked at MCR redirected layer download (403) | `03f7e10`, **partial validation** |
| D — CI | One pinned/read-only main-push workflow, .NET Linux/Windows, frontend, focused browser, Docker; no dispatch/PR/schedule/deploy/publisher. Historical workflows archived; actionlint and trigger tests pass | `6e7b7ba` |
| E — Scripts | SDK selection, canonical paths, no-reuse browser compiler settings, fail-fast missing SDK, isolated fake deployment remote. Historical root fallback retained only for older-commit compatibility | `3f1e6c0` |
| F — Windows | Host/TLS/proxy/installer/location contracts, PowerShell syntax and fake SSH orchestration pass on Linux; exact native follow-up commands recorded. Existing service/release/data/key paths unchanged | `faea923` |
| G — Docs/verification | Current guides, agent instructions, migration gates and security checks aligned; evidence below. No merge, version bump, release or workflow execution | This checkpoint |

Validation performed:

- SDK 10.0.404 solution build: **0 warnings, 0 errors**. SDK and Linux PowerShell
  7.7.0 were downloaded into temporary storage and checked against official hashes.
- Initial focused .NET group: **23 passed, 1 failed** (outdated frontend=v1 version
  assertion). The contract now requires the canonical v2 frontend version and keeps
  the v1 resource distinct. Corrected version/startup/TLS/proxy/installer/Desktop
  group: **25 passed, 0 failed/skipped**.
- Consolidated non-publish/non-build .NET selection: **411 passed, 1 failed, 0 skipped**
  (412 total). The failure compared a November 17 golden `as_of` value with the
  November 18 live context. Initial historical-date recheck showed `/context`
  deliberately ignores `as_of`; final test explicitly asserts its current-day
  contract (including midnight boundary), while historical query comparisons use
  the fixture evaluation date. Final complete affected class: **2 passed**. No
  production SoD rule or response assertion was removed. The broad selection was
  not rerun; this is not reported as a clean single-run full regression.
- Embedded-UI incremental build contract passed in the initial focused group;
  its expensive rebuilds were reused rather than repeated in the consolidated run.
  Publish/package acceptance (`Category=Publish`) was intentionally not executed.
- Frontend typecheck and production build passed; **41 unit tests passed**. ESLint:
  **0 errors, 114 existing warnings** (threshold 115).
- Final .NET Playwright selection: **12 passed, 0 failed/skipped**, one worker,
  system Chromium (`PLAYWRIGHT_EXECUTABLE_PATH=/usr/bin/chromium`), private port
  18856. Component interactions, focus and light/dark at 375/1280px, host identity,
  unauthenticated rejection, CSV activation and Role Lookup. No complete browser
  regression was requested/executed. Owned host exited and its port was released.
- Repository tests: **5 Node tests** (version, source commit, missing SDK cleanup,
  invalid ports); **8 Python infrastructure contracts** (CI triggers/permissions,
  Docker boundaries, structure, incomplete/vulnerable advisory reports).
- PowerShell parsing: **10 scripts, 0 errors**, Linux PowerShell 7 only. Fake SSH
  deployment tests: **18/18 passed**, disposable local clones, no remote operations.
  Pester 5.7.1 acquisition failed because the managed proxy blocks PowerShell
  Gallery; Pester was **not executed**. No native PowerShell 5.1 result is claimed.
- NuGet advisory report (9 projects) and production npm audit: **0 vulnerabilities**.
  The audit parser separately rejects incomplete/error reports. Tracked secret
  scan: **0 findings**. Icon catalogue: **1,447 icons verified**. Docs: **99 Markdown
  files, 0 broken links**. Workflow YAML/contracts, actionlint, Bash syntax and
  whitespace checks passed. No runtime dependency or product version was changed; PyYAML 6.0.3 is a new development-only workflow-check dependency.
- No GitHub Actions were dispatched. API inspection showed **0 workflow runs** for
  pushed commit `45579d6`; final push verification is recorded by the delivery report.

External follow-up:

1. (Obsolete: Docker support was removed on 2026-11-18.) Allow the official MCR layer host `centralus.data.mcr.microsoft.com` in the
   managed network, then run the exact image build.
   Registry manifest access works; layer access returns 403. Image/runtime acceptance
   remains unverified, and no production container was deployed.
2. Obtain pinned Pester from an approved source and run the commands in
   [Windows verification](../deployment/WINDOWS_DEPLOYMENT.md#post-promotion-infrastructure-verification).
3. Run native Windows service/Desktop/installer, ACL/firewall and recovery checks
   on disposable data. Preserve the real installation and all release/backup/key
   directories. Rehearse real-data v1 migration separately before release approval.

Private production hosts, keys, configuration and data are not included in this
record. `main`, local historical `work`, and remote `work-v1` were preserved.
