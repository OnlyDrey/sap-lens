# Development progress

Resume guide for a new session: read [AGENTS.md](../../AGENTS.md), this file, `git status` and `git log --oneline -15`; the repository state is authoritative, correct this file where it differs.
CI policy: GitHub Actions runs only on push to `main` after an explicitly approved merge; all validation is local; `work` pushes never trigger it.

**Last update:** 2026-11-05 (end of Phase F)

## Plan and status

| Phase | Scope | Status | Commit |
| --- | --- | --- | --- |
| Baseline and audit | Production path measured (`csv_lifecycle.load`), benchmark tool `scripts/benchmarks/data_benchmark.py` | Completed | `5a943c3` baseline, `dd55205` |
| Import anomaly gate | Suspicious versus invalid imports, confirmation, configurable threshold | Completed | `0db6989` |
| Step 1 | SQLite source store, schema ladder, verified pre-migration backup, signed derived cache | Completed | `7faf0e2` |
| Step 2 | Source fingerprints, unchanged fast path, staged activation | Completed | `0ed713c` |
| Staging ownership | Operation-scoped staging, orphan recovery | Completed | `9748044` |
| Step 3 | Assignment lifecycle, reappearing assignments need a new review | Completed | `6067e35` |
| Step 3 hardening | Identity evidence, fail-safe applicability, Data Health | Completed | `134d24b` |
| CI policy | CI only on push to `main` | Completed | `2451753` |
| Step 4 | Data retention (source), daily check, one-time approval | Completed | `8247da6` |
| Retention completion | Separate source and review retention, logical timestamps, journalled recoverable review cleanup | Completed | `70ae519` |
| A | Backup retention (automatic 90 days, migration and manual protected) | Completed | `2ab0b0d` |
| B | Employee Directory fingerprint, derived copy, shared SAP/AD matcher | Completed | `eccc0b4` |
| C | Backend/API performance (`/api/access/users`, dashboard, memory) | Completed | `21cc4f3` |
| D | Frontend/API cache consistency (`X-Data-Revision`, stale-response repeat, atomic review saves) | Completed | see Git log |
| E | Parallel browser test stabilization | Completed (findings in TESTING.md) | see Git log |
| F | Final validation: full backend, browser, benchmarks, report | Completed | see Git log |

## Local validation (latest)

* Backend full run before the retention work: 1430 tests (3 failures were the workflow tests edited mid-run; re-run OK). Targeted suites for every phase pass.
* Phase D: backend test_data_revision (15), account_review, application, server, workflows pass; unit tests 14; browser revision-consistency (3), dashboard-user-transactions, account-review-refinement, csv-lifecycle (41 total) pass; tsc and ruff clean. ESLint reports one pre-existing error (irregular whitespace in `tests/remediation-export.spec.ts`), unrelated.
* Phase E hygiene: runner handles SIGTERM/SIGHUP, test server exits when its parent is killed (verified with a real SIGKILL of Playwright: server and Chromium gone), regression tests in test_test_profiles (25 pass); recovery, catalogue and metadata specs pass together (40/40).
* Phase E: SoD browser feature passes with 2 and 3 processes (222/222); several workers on one server are not safe (shared global state).
* Phase F full backend regression: 1522 tests, 0 failed, 6 skipped (PyInstaller and PowerShell only), 79 s on 3 processes.
* Phase F full browser regression (2 isolated processes, 1 worker each): 872 of 872 passed in 1229 s, largest process 724 MB. The first run found two spec defects (global-navigation vs the import gate, sod-metadata position-based lookups), both fixed in tests, none in product code.
* Static: ruff, docs links, workflow contracts, Lucide catalogue, `git diff --check`, `pip check`, `npm audit --omit=dev` (0 vulnerabilities), tsc, unit tests (16) pass; ESLint 0 errors (115 existing warnings).

## Measured performance (192 000 assignment rows, synthetic, this container)

| Scenario | Original | Step 2 |
| --- | --- | --- |
| Import | 20.2 s, peak 1017 MB | 16.4 s, peak 836 MB |
| Dynamic start, unchanged | 27.8 s, peak 1164 MB | 2.2 s warm, peak 525 MB |
| Static start | 9.8 s, peak 730 MB | 2.1 s, peak 525 MB |
| Refresh, one source changed | 24.6 s, peak 1251 MB | 15.3 s, peak 1125 MB |

### Employee Directory (100 000 employees, 20 000 SAP users, this container, fresh process per scenario)

| Scenario | Before (`2ab0b0d`) | After |
| --- | --- | --- |
| Start, unchanged files (warm) | 8.0 s, peak 703 MB | 1.7 s, peak 460 MB |
| Static start (warm) | 8.3 s | 1.7 s |
| Refresh, only users changed | 8.9 s | 3.7 s |
| Refresh, only the directory changed | 6.6 s | 7.1 s single run (see Phase F repeat below: median 5.1 s, no regression) |
| Import | 12.3 s | 9.6 s (not attributed: the first import does the same work) |
| Identity mapping of every SAP user, first call / repeat | 0.5 s each call | about 0.6 s first (about 10 to 15 % overhead), 0.04 s repeat |

Component timings at 100 000 rows: parse 2.4 s, comparison 3.5 s, snapshot restore 1.8 s (derived copy: 0.8 s).

### Backend and API (192 000 assignment rows, 16 000 users)

| Measurement | Before | After |
| --- | --- | --- |
| `/api/access/users?limit=50` (median of 5) | 631 ms | 203 ms |
| `/api/dashboard` | 734 ms | 151 ms |
| Refresh, users changed (time / peak) | 15.3 s / 1164 MB | 11.2 s / 1071 MB |

Matcher lifetime verified by test: repeated refreshes keep only the current (SAP dataset, directory) pair; replaced datasets and directories are collected.

## Known limitations and risks

* Resident memory ~525 MB, of which ~185 MB raw source records retained; changed-source refresh peaks above 1.1 GB (Phase C).
* First start after a change derives the model once (~4 s).
* Native Windows, WebView2 and systemd paths are not validated here.

## Final-validation requirements added by the user

* Verify and document how the automatic-backup count limit (`keep`) and the 90-day policy interact: 90 days is a maximum, not a guaranteed minimum. The Settings UI must state both mechanisms and the cleanup preview must say which rule makes each backup eligible. (Pending, scheduled with Phase F unless an integrity issue appears earlier.)

* Phase C checks: (1) the shared SAP/AD matcher must not retain obsolete datasets or grow without bound after repeated refreshes (test with weak references); (2) repeat the changed-directory refresh benchmark in Phase F to decide whether 6.6 s to 7.1 s is noise or a regression; (3) profile before optimizing `/api/access/users`, Dashboard and changed-source refresh memory; (4) keep API contracts, filtering semantics, SoD behavior and review integrity.

* Phase D priorities: data correctness over request count; expose/track the active source revision in source-dependent responses; invalidate caches only for the revision that changed; stale in-flight responses must not replace newer data; filters, sorting, pagination and selection stay consistent after refresh; multi-user correctness; review submissions validated server-side against the current source/review revision; no polling or broad invalidation where a targeted revision mechanism exists; keep API contracts.

## Decisions requiring user approval

None open.

## Next actions

Phase D: frontend and API cache consistency (revision-aware), then E (parallel browser tests), F (final validation; includes the backup count-versus-90-day requirement and the repeat of the changed-directory refresh benchmark).


## Phase F: changed-directory refresh repeat (5 alternating runs each, identical data)

Dataset: 100 000 employees, 20 000 SAP users, 400 roles, 10 assignments per user; fresh process per scenario; before = backend of `2ab0b0d`, after = current backend; machine otherwise idle.

| Scenario | Before median [range] | After median [range] | Change |
| --- | --- | --- | --- |
| Refresh, only the directory changed | 6.61 s [5.95 to 6.95] | 5.08 s [4.29 to 5.49] | -23 % |
| Refresh, only users changed | 21.5 s [21.3 to 22.1] | 12.9 s [12.1 to 13.4] | -40 % |
| Start, unchanged files (warm) | 8.13 s [7.69 to 8.78] | 3.23 s [3.03 to 3.36] | -60 % |
| Import | 20.7 s [19.6 to 21.3] | 19.4 s [18.6 to 19.6] | -6 % |

The ranges for the changed-directory refresh do not overlap and the "before" median reproduces the earlier 6.6 s, so the earlier 7.1 s was a single noisy run, not a regression. A second dataset (16 000 users, 16 000 employees) shows the same direction (1.19 s to 0.54 s). Peak memory for that scenario: 1045 MB before, 1015 MB after.


## Phase F: final measurements (192 000 assignment rows, 16 000 users, 16 000 employees, one run, this container)

| Scenario | Original baseline | Final |
| --- | --- | --- |
| Import | 20.2 s, peak 1017 MB | 14.8 s, peak 802 MB |
| Dynamic start, unchanged (cold / warm) | 27.8 s, peak 1164 MB | 5.5 s / 2.6 s, peak 607 / 524 MB |
| Static start (cold / warm) | 9.8 s, peak 730 MB | 2.7 s / 2.5 s, peak 542 / 524 MB |
| Refresh, one source changed (users) | 24.6 s, peak 1251 MB | 12.1 s, peak 1017 MB |
| Refresh, only the directory changed | see repeat above | 0.74 s, peak 607 MB |
| `/api/access/users` page / sorted / filtered | 631 ms | 162 / 165 / 39 ms |
| `/api/dashboard` | 734 ms | 128 ms |
| Resident memory after start | about 1.1 GB | 520 to 540 MB |
| Data directory after the run | not measured | 332 MB (snapshots 181 MB, SQLite store 135 MB) |

Review save and SoD evaluation timings are covered by the backend suite, not by this tool. Single-run figures; the repeat above shows the run-to-run spread is about 5 to 10 %.

## Platform limitations

Native Windows (process handling, WebView2, service control manager, UNC paths) and a real systemd boot/recovery are not testable in this Linux container; see [deployment validation status](../deployment/README.md#validation-status). Six backend tests skip here for that reason (PyInstaller, PowerShell).

## Final phase list and commits

A `2ab0b0d`, B `eccc0b4`, C `21cc4f3`, D `451874c` (+ `d8ca720`), E `f30bac4`, `f949d3c`, `3f4d931`, `ba1d4ca`, F `55376c6`, `563194a`, `9d82eaf` and the closing documentation commit. Earlier work: `5a943c3` to `70ae519`.


## Repository audit and cleanup (started)

| Phase | Scope | Status | Commit |
| --- | --- | --- | --- |
| 1 | Repository inventory and audit ([report](REPOSITORY_AUDIT.md)) | Completed | see Git log |
| 2 | Structure and cleanup, scripts consolidation (`scripts/build.ps1`, `maintenance/`, `benchmarks/`, `scripts/README.md`, lint ceiling) | Completed | see Git log |
| 3 | Build, test and workflow audit | Completed (no defect found; recorded in the audit report) | see Git log |
| 4 | Documentation architecture (inventory in the audit report) | Completed | see Git log |
| 5 | Documentation rewrite and consolidation | Completed | see Git log |
| 6 | Dependencies, configuration, security hygiene (no change needed) | Completed | see Git log |
| 7 | Final validation and audit report | Completed | see Git log |

Phase 1 result: no tracked generated files, secrets or removable scripts; one gate failure found (`npm run lint` exceeds its warning ceiling, red since the original baseline). Details and decisions in the audit report.

Phase 2 result: `build.ps1` moved to `scripts/build.ps1` (root no longer has a build entrypoint; the venv and `build.py` are resolved relative to the script, so any working directory works). `generate-examples.py`, `reference-template.py` and `validation_tracker.py` moved to `scripts/maintenance/`, `profile-sod.py` to `scripts/benchmarks/`; every reference (tests, docs, `test-map.json`, `check-powershell.ps1`) updated. All 54 scripts are classified in `scripts/README.md` and `docs/BUILD.md`; none is redundant or obsolete. The deployment and Windows packaging scripts stay where workflows, release tooling and bundles address them: they cannot be re-verified without a PowerShell host, and moving them would add nesting without removing duplication. The lint warning ceiling is now the measured 115 (the gate was red). Native Windows execution of `scripts/build.ps1` remains unverified.

Phases 3 to 5 result: workflows, Docker files and scripts reference only existing files; native calls in the PowerShell scripts are guarded (`$ErrorActionPreference = 'Stop'` plus `Assert-Success`/`Checked`/`$LASTEXITCODE`); CI triggers unchanged. Documentation: new [storage and revisions](../architecture/STORAGE_AND_REVISIONS.md), [data retention](../operations/DATA_RETENTION.md) and [performance](PERFORMANCE.md) documents (content moved out of `SYSTEM.md` and `IMPORT_AND_REFRESH.md`, which now point to them), operations index, version stamps removed from four headings, a dated incident log removed from `CI_CD.md`, README gained architecture and security/operations sections, documentation indexes updated.

Phase 7: backend regression 1522 passed (0 failed, 6 skipped), browser smoke 12/12, static checks green; see the final summary in the audit report.


## Scripts architecture, second pass

| Phase | Scope | Status | Commit |
| --- | --- | --- | --- |
| 1 | Call graph, disposition matrix, proposed architecture ([audit report](REPOSITORY_AUDIT.md#scripts-architecture-second-pass)) | Completed | see Git log |
| 2 | PowerShell consolidation | Partly done: `validate.ps1`/`validate.sh` removed. The rest needs approval and a Windows host | |
| 3 to 5 | Python orchestration, directory organization, consumer updates | Waiting for approval of the proposed architecture | |
| 6 | Validation | Linux-side validation done for the completed part | |
| 7 | Final report | After approval and the staged migration | |

Scripts consolidation, approved plan: stage 1 done (`build-windows.ps1` to `build_system/windows/stages.py`, opt-in, 20 contract tests). Windows validation checklist in BUILD.md. Original kept as default.

Stage 2 done: service manager, server bundle, desktop installer and deployment packaging ported (opt-in, 17 contract tests). Next: `build-local.ps1`.

Stage 3 done: `build-local.ps1` ported (`local.py`, opt-in). All six build scripts have Python ports; Windows validation checklist covers all. Next: directory organization (approved decision 2, now unblocked because PowerShell consolidation is blocked on Windows validation).


## Start-up session recovery

Verified cause and fix are documented in [Local session lifecycle and start-up recovery](../architecture/SECURITY.md#local-session-lifecycle-and-start-up-recovery). Implemented: `startupRecovery.ts` (classification, bounded back-off, once-per-minute automatic restore), new `StartupGate`
(Starting / Connecting / Restoring labels, one-action recovery screen, no "Reload trusted session"), automatic restore in `SessionNotice` when nothing would be lost, browser test server in desktop mode (`browser_access`), 21 unit tests, 13 new Playwright cases,
9 backend boundary tests. Windows validation steps are in the security document; native Windows behavior is unverified.


## User Directory and User Profile modernization (plan and status)

Audit result. Reused, not duplicated: `directory_filters`/`directory_selection` (`backend/routers/access.py`) drive the listing, counts, paging, sorting and the CSV export, so the exact username list is one more parameter of that function;
Functional Group storage, revisions, history and `classify` (`backend/functional_groups.py`); `MultiSelectFilter` (shared) for list filters; Saved Filters store the filter object; `InfoDisclosure` for secondary text.
Missing before this round: an exact-username filter, a whole-filter selection endpoint, a bulk assignment path (only one-user `PUT /api/functional-groups/users/{u}` existed), table layout with sticky columns, selection UI, profile layout.

| Step | Scope | Status |
| --- | --- | --- |
| A | Backend: `usernames` filter (`backend/username_filter.py`), feedback in `GET /api/access/users`, `GET /api/access/users-selection` | Done and tested (`test_username_filter`, 13 tests) |
| B | Backend: `POST /api/functional-groups/bulk/preview` and `/bulk` (one store write, per-user applied/unchanged/conflict/rejected, replacement confirmation, revision and dataset-staleness checks, operation id, history events, administrators only) | Done and tested (`test_bulk_group_assignment`, 16 tests) |
| C | Shared dropdown/multiselect: two-line role options, content-aware width, viewport-aware placement | Pending |
| D | User Directory table: scroll container, sticky selection and username columns, Full Name, column order, toolbar | Pending |
| E | Paste box for username lists, feedback, chips, Saved Filters, export | Pending |
| F | Selection model, bulk assignment dialog, results and retry of failures | Pending |
| G | User Profile redesign (2x2 sections, Directory Match under Account Status) | Pending |
| H | Browser tests, documentation, full regression | Pending |

Design decisions already taken: selection across pages is an explicit username list fetched from `users-selection` (it cannot widen when data or filters change; the data revision is sent with the assignment and a different publication is refused); a replacement of an existing group is a per-user conflict
until `replace_existing` is confirmed; partial outcomes are returned as `status: partial` with the failed users so only they are retried; Functional Groups remain local classifications and never touch SAP roles, authorizations, AD groups or imports.
