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
| C | Shared dropdown/multiselect: two-line role options (`optionDescription`), content-aware width (about 540 px, never wider than the viewport), accessible name and description | Done: `dropdown-layout.spec.ts` (6) and the 10 existing multiselect specs pass |
| D | User Directory table: scroll container, sticky selection and username columns, Full Name, column order, toolbar | Done (table, sticky columns, toolbar, selection checkboxes; bulk actions in F) |
| E | Paste box for username lists, feedback, chips, Saved Filters, export | Pending |
| F | Selection model, bulk assignment dialog, results and retry of failures | Pending |
| G | User Profile redesign (2x2 sections, Directory Match under Account Status) | Pending |
| H | Browser tests, documentation, full regression | Pending |

Design decisions already taken: selection across pages is an explicit username list fetched from `users-selection` (it cannot widen when data or filters change; the data revision is sent with the assignment and a different publication is refused); a replacement of an existing group is a per-user conflict
until `replace_existing` is confirmed; partial outcomes are returned as `status: partial` with the failed users so only they are retried; Functional Groups remain local classifications and never touch SAP roles, authorizations, AD groups or imports.

## Windows build stabilization (B01-B10)

| Item | Cause | Fix | Status |
|---|---|---|---|
| B08 | `$PSScriptRoot` is empty in functions extracted into scriptblocks | `Get-RepositoryRoot` with explicit/validated script directory; tests for root resolution | Fixed, Linux-tested; native 5.1 pending |
| B09 | Interpreter-protection check ran before the confirmation check; on Windows the test interpreter lives under a generated dir | Fixed validation order, each condition tested | Fixed |
| B04-B05 | Python urllib got HTTP 403 | Local archive, persistent cache, headers, proxy, actionable BLOCKED failure (exit 2) | Fixed |
| B01-B02 | Output ownership message lacked detail | Path, manifest metadata, suggested command; docs | Fixed |
| B03/B07/B10 | Prerequisite clarity | Documented in BUILD.md (existing checks kept) | Documented |
| B06 | Terse blocked message | Blocked rows carry error, log, hint; `prerequisite` class | Fixed |
| Skips | Two tests required `pwsh` only | Windows PowerShell 5.1 accepted | Fixed |

## B11: Browser smoke in the generated build workspace

| Item | Detail |
|---|---|
| Root cause | The workspace mirror excluded all of `backend/tests`, so specs reading `../backend/tests/fixtures/user-access.csv` pointed at a missing file and `POST /api/configuration` was refused (the path is validated) in `beforeEach`. |
| Fix | `frontend_workspace.mirror` copies only `backend/tests/fixtures` (data, links refused); specs use `backendFixture()` in `frontend/tests/support.ts`, resolved from the spec file location, with an error naming the searched path. `saveConfiguration()` reports HTTP status, a redacted body and the path existence. |
| Other affected specs | `investigation-ux`, `data-aware-ux`. `sod-metadata` and `application-backups` import Python test helpers from the repository root; they are not `@smoke` and run from the checkout only. |
| Validation | `test_build_diagnostics` (fixture resolution in checkout and workspace layout); 34 of 37 specs in the three affected files pass on Linux. Three `data-aware-ux` session-recovery tests (HTTP 401/403 messages, stale session) fail identically on the commit before this change and are tracked separately. Native Windows not validated. |

## User Profile redesign

One bordered container; header with name, email and the Directory match status at the far right (removed from SAP Identity); three equal columns (SAP Identity, Account Status, Organization) with vertical separators; full-width Functional Group section last with an `Assign group` button (users-round icon) and an `About Functional Groups` disclosure. Breakpoints: 3 columns above 1100 px, 2 columns (Organization full width) to 640 px, stacked below. Labels now read `SAP account` and `AD account`. Tests: `user-profile-layout.spec.ts` (equal columns, header match only, last/full-width Functional Group, icon, stacking at 375/800, light/dark, no overflow); affected specs updated.

## Bulk Functional Group assignment (User Directory)

- Selection: checkbox column keeps an explicit username set across pages; toolbar shows `N matching . M selected`, then, when users are selected, `Assign group` (primary, users-round), `Clear selection` (x, clears only the selection) and `Export CSV` (download), all the default button size.
- Dialog (`BulkAssignDialog`): searchable group list from the group catalogue (active groups only), preview via `POST /api/functional-groups/bulk/preview` (current assignments per group, missing users), explicit confirmation before replacing existing groups, reviewer required, submit disabled until valid and while pending, one operation id per attempt (a repeat is refused with 409).
- Persistence: `POST /api/functional-groups/bulk` writes all applied users in one store write with history events; per-user outcomes `applied`, `unchanged`, `conflicts` (changed since preview, replacement not confirmed) and `rejected` (not in the dataset). A result with any skipped user is `partial`, never full success; only failed users can be retried from the result view. A different data publication is refused (409).
- Sync: queries `access-users`, `access-user`, classification, group options and account review are invalidated; filters, sorting and pagination are untouched. The filter sidebar Clear button now uses the eraser icon and shares the compact control height with the close button.
- Tests: `bulk-group-assignment.spec.ts`, backend `test_bulk_group_assignment` (atomicity, replacement, stale, duplicate operation, failed write). Limitation: no "select all matching" action yet and no exact-username paste UI (phase E).

## Phase E, data-aware UX fixes and workspace audit

- **HTTP 401/403 (data-aware-ux):** the startup gate (added with startup recovery) replaced the service's reason with a generic text. A refusal now shows the service's own message (`Server access is not authorized.` or the permission text) before the generic guidance; session and unreachable-service states are unchanged.
- **Stale desktop session:** the test expected a manual *Reconnect session* click, but recovery is now automatic when nothing typed would be lost; the test asserts the automatic path (no replayed write, route and filters kept). The manual path stays covered by `session-recovery.spec.ts`.
- **Phase E:** exact username paste with feedback, Saved Filters integration, select all matching, selection cleared when the result set changes (`username-filter.spec.ts`, 24-name fixture including `KJØRGENSEN`).
- **Workspace audit:** `application-backups` needs only mirrored `backend/` code and works in the workspace. The two `sod-metadata` tests that import Python test modules are tagged `@repository-only`; the workspace full run uses `--grep-invert @repository-only`, and the regression profile runs them from the checkout. A unit test enforces the tag.

## Full regression round and Role Evidence review

- Browser regression (2 processes, 899 tests): 14 failures, all project-owned and fixed: Saved Filters rejected the new `usernames` field (allow-listed, 12,000 characters); pinned username cells hid row tooltips (raised while a tooltip or focus is inside); the 503 startup rule treated an application error (503 with a detail) as a starting service, which blocked Backup & Restore (now a real failure); one spec asserted the old profile Directory match location. The backend suite is run separately.
- Role Evidence: inline Investigate/Keep/Remove per assignment (`RoleEvidenceReview`, shared hook `useAssignmentQuickReview` extracted from the investigation panel). Tests: `sod-role-evidence-review.spec.ts`.

## Packaging separated from native SCM acceptance

- **Root cause:** `package-windows-deployment.ps1` ran `test-server-service.ps1` (a real SCM install/start/stop/backup/restore/uninstall) for every Service package, so an ordinary non-elevated `-Mode package` ended in `manage-server-service.ps1: Open an elevated PowerShell for SCM management` after the artifact had already been built.
- **Change:** the acceptance runs only with `-NativeAcceptance` (or on the CI runner); elevation is checked first in the packaging script and inside the acceptance script (exit 3, `ACCEPTANCE PREREQUISITE`); the manifest gains `native_acceptance`; blocked prerequisites are `blocked`, not `failed`; release verification requires a passed acceptance. `test-server-service.ps1` now also runs standalone (temp directory default, repository root).
- **Desktop lifecycle tests:** `test_unexpected_backend_exit_reports_error_and_closes_owned_window` and `test_retry_stops_old_backend_and_uses_fresh_owned_instance` used fixed 2 s/5 s waits for asynchronous uvicorn shutdown. They now wait on the actual conditions (stop and destroy) with a 20 s bound that only the failure path uses, and name the state on failure. Not reproduced on Linux (3 repeated passes); native Windows load behaviour is unverified.
- **Tests:** `test_windows_acceptance_split.py`, updated `test_windows_ports.py` golden sequences.

## Windows Desktop EXE smoke test (investigation, v1.0.0-beta.2)

Native Windows has not yet confirmed the final cause. What the code proves:

- **Product defect found (fixed):** the packaged Desktop runs the mandatory pre-migration backup, which on Windows calls a bare `powershell` (owner SID) and `icacls.exe`. The smoke test (correctly) launches the EXE with `PATH = System32;Windows`, and `powershell.exe` lives in `System32\WindowsPowerShell\v1.0`, so on that path the call cannot resolve (`FileNotFoundError`), which is consistent with the logged `storage_upgrade: backup_failed` (inferred from the code and the log line; the exception type was not logged, so this is not yet confirmed). The tools are now resolved to absolute paths under `%SystemRoot%\System32` (`maintenance.windows_tool`, `current_sid`), and a failed backup now logs its application-authored reason or the exception type with `errno`/`winerror` instead of the type alone. A hypothesis that the live `sap-lens.log` broke the backup was tested and rejected (the backup inventory already skips `*.log`); no change was made for it.
- **Harness defect found:** the application allows one instance per Windows session (`Local\SAPLensDesktop`, independent of `SAP_LENS_CONFIG_DIR`). Any running SAP Lens, for example the isolated manual launch (PIDs 25812/42540) or an installed copy, makes every smoke launch exit with code 0 and no runtime, which the script reported as `Packaged application exited before readiness`. The script now checks the guard before the first launch and between scenarios and reports it as a prerequisite (nothing is terminated).
- **Fixture:** the synthetic two-role CSV and `settings.json` were verified against the current import pipeline (Linux, app factory): `/health` returns `status=ok`, `cached_roles=2`. The fixture is not outdated.
- **Diagnostics:** `test-windows-exe.ps1` now classifies failures (`process_exited_before_readiness`, `runtime_record_missing`, `runtime_not_owned`, `http_unavailable`, `instance_id_mismatch`, `health_status_incorrect`, `cached_roles_incorrect`, `window_initialization_failed`, `readiness_timeout`, `prerequisite_existing_instance`) and prints scenario, executable, PIDs and parent/child tree, exit code, `runtime.json` presence, last health versus expected, last condition, elapsed time and the redacted log tail. Ownership checks, the 60 s timeout and readiness assertions are unchanged.
- **Still unverified on Windows:** whether the `PATH` backup failure or the single-instance guard (or both) caused the observed 60 s readiness timeouts. Re-run `scripts\test-windows-exe.ps1` after closing every SAP Lens window; the new report names the failing condition.

### Smoke diagnostics hotfix

`Format-Diagnostics` called `Join-Path $state.Directory 'runtime.json'`; the existing-instance preflight (and `instance_not_released`) throw before a scenario directory is assigned, so the state held an empty `Directory` and Windows PowerShell 5.1 raised a binding error that masked the real failure. Fixed with `Join-SafePath` (null for blank input, never an empty `Join-Path`), a guarded `Format-Diagnostics` wrapper (any reporter problem degrades to the plain `SMOKE FAILURE [class] detail`), and structural regression tests. Native Windows execution remains unverified.

## Functional Group section on User Details (compact, single membership)

Compact summary line: assigned group name in emphasis, classification badge, confirmation text, review and suggestion notes, a visible "business classification, does not change SAP access" line and the About disclosure. Confirmation text separates a missing date from a missing reviewer and never invents values (`lib/functionalGroupText.ts`, unit tests). Action labels: Assign group, Change group (confirmed), Assign / Confirm (assigned but not confirmed). This is the single-membership version; the multiple-membership extension is pending design decisions (see below).

## 24-hour time in Backup & Restore (and elsewhere)

The daily backup time is a fixed-format `HH:mm` text field (`TimeInput24`) instead of `<input type="time">`, which follows the browser locale and shows AM/PM. Backup & Restore timestamps (last recorded operation, archive preview, schedule, history), the Data Retention dates and the session notice use the shared `formatTimestamp`/`formatTime` (`dd.MM.yyyy HH:mm`, 24-hour, local zone); no `toLocaleString`/`toLocaleDateString` is left in rendered text except counts. Backend schedules and stored timestamps are unchanged. Tests: `tests/unit/time-format.test.ts` (00:00, 12:00, 14:30, 06:00, zone conversion and date change in Europe/Oslo, validation), `backup-time-format.spec.ts` (en-US locale, 24-hour control, invalid entry).

## Windows Service Manager: connection modes and registration diagnostics

- **Registration failure:** the generic `Invalid server configuration or TLS certificate/key.` hid the failing check. Backend configuration validation (`ServerSettings.from_env`) now raises `ConfigError` with the step and the underlying error, and `--check-server-config` prints it; the Service Manager already appended that text to its message. The exact failing step on the reporter's machine is not yet confirmed: the same configuration (`localhost,127.0.0.1`, listener `0.0.0.0`, port 18743, users authentication) validates on Linux with an OpenSSL certificate, and the Service Manager's DER/PEM key writer was reproduced byte-identically, so the remaining suspects are Windows-only (the .NET certificate/SAN output or the frozen runtime). The next registration attempt will name the step.
- **Modes:** HTTP, HTTPS self-signed (default), HTTPS existing certificate. HTTP carries no certificate, needs the acknowledgement beyond loopback (`SAP_LENS_ALLOW_HTTP`, account authentication only), URLs use the configured scheme, existing HTTPS installations open in an HTTPS mode.
- **Validation:** `test_server_connection_modes.py` (15 tests: SAN DNS/IPv4, wildcard listener, key mismatch, expired, missing files, invalid host, HTTP loopback/LAN/acknowledgement, certificate with HTTP, the check command output, static Service Manager contract). `ServiceManager.cs` could not be compiled here, and the Service Manager UI, service start/stop and PowerShell 5.1 behaviour are unverified on native Windows.

## Repeated PowerShell processes from SAP-Lens.exe

- **Root cause and caller chain:** the Windows branch of `maintenance.private_file()` ran `powershell -NoProfile -Command [Security.Principal.WindowsIdentity]::GetCurrent().User.Value` (then `icacls.exe`) on every call, and `application_backups.secure()` did the same per directory. `private_file` is called for each write of the backup/restore journal (`application_backups.write`), for the upload file (`routers/backups.upload`), for every member extracted by a restore (`maintenance.restore`, once per file), for the pre-migration backup, the storage-migration record and the desktop "save backup" temp file. A backup upload or restore therefore started one PowerShell (a console window from a GUI process) per file or state write, which matches 15 processes in 30 seconds. Nothing is polled; the multiplier is the per-file/per-write call.
- **Fix:** `backend/windows_identity.py` reads the SID in-process (`OpenThreadToken` falling back to `OpenProcessToken`, `GetTokenInformation(TokenUser)`, `ConvertSidToStringSid`) and applies the private DACL with `SetNamedSecurityInfoW` (protected DACL, user and SYSTEM full control, directories also to children), the same result as the former `icacls /inheritance:r /grant:r`. No subprocess remains in the backend (the earlier absolute-path helper `windows_tool` was removed with it). Identity is looked up on every call and never cached (impersonation and service accounts differ); failures raise `WindowsIdentityError` naming the API and Windows error, surfaced as `MaintenanceError`, never a substitute identity.
- **Tests:** `test_windows_identity.py` (13): SID format, thread-over-process token, service and desktop SIDs, no caching, handle release, explicit failures, exact SDDL, 200 repeated calls start no process, backup/restore path starts none, no backend module references PowerShell/icacls. Real Windows API behaviour (ctypes signatures, ACL result, impersonation) is not tested on Linux and needs a native Windows run: back up, upload and restore an archive with Process Monitor or the earlier trace and confirm no `powershell.exe` or `icacls.exe` child of `SAP-Lens.exe`, and check the resulting ACL with `icacls <file>`.

## Functional Groups: multiple memberships, suggestion rules, members and analysis UI

- Many-to-many users and groups (storage format 2, lossless migration, `.format1.bak`), membership endpoints, add-only bulk assignment, Department contains rules with compatibility mode, rule matches and assignment, member management, Access Analysis KPI tiles and drilldown, `Dialog` `footer={null}` to drop redundant Close.
- Validation (Linux, targeted): backend functional_groups 48, bulk 18, backups 37, account review 30; Playwright 22 across functional-groups, members, bulk, profile layout and username filter; tsc, ESLint (115 warnings, unchanged), ruff, docs check. Full regression pending; native Windows unverified.

## Prerequisites setup, check and repair

- **Root cause:** `.venv` creation and test runners used whichever interpreter started them (`sys.executable`, bare `python`), so a 3.15 default ran the backend regression with no `.venv`; there was no read-only check, no repair path and no target-aware preflight.
- **Change:** `build.ps1 -Mode prerequisites [-CheckOnly|-Repair|-Json]` (`build.py prerequisites`), `build_system/doctor.py` (report, repair by rename, preflight), 3.12 x64 discovery and venv inspection in `python_env.py`, engine re-exec under 3.12, `validate.py`/`run-tests.py` and `build-windows.ps1`/`build-desktop-installer.ps1` resolve 3.12 explicitly.
- **Validation (Linux):** `test_prerequisites.py` (isolated temp roots, mocked Windows paths), real temp-root setup twice (second run installs nothing). Native Windows (`py -3.12` with a 3.15 default, `.cmd` npm) remains unverified.

## Windows regression stabilization (cross-platform)

- **Root causes (native Windows run: 5 failures, 3 errors):** backup rollback tests matched `'/stage/data/'` against Windows paths (test); two symlink tests raised WinError 1314 without symlink privilege (now `links.symlink` skips explicitly, a coverage gap on unprivileged Windows); the interpreter probe test used a `sh` stub (test; the probe is now one line so `.cmd` stubs work); `check_secret_permissions` returned immediately on Windows, so the secret-file test could not fail (product gap: the DACL is now checked, fail closed); Functional Group reconfirmation dropped a change stamped in the same clock tick as the confirmation (`<=`, product defect on coarse clocks, now `<`); SoD reopened classification required `modified < created` for the prior period (now `<=`).
- **Verification:** the tie regression tests fail against the old code on Linux; the Windows ACL policy is verified with simulated DACLs. Native Windows re-run pending.
- **PowerShell 7.6.9** installed on Ubuntu 24.04 from Microsoft's apt repository; `test_powershell.py` (13 tests) and `check-powershell.ps1` pass; a real `prerequisites --repair` through pwsh preserved the broken environment and recreated it. PSScriptAnalyzer unavailable (gallery 403).
- **Playwright:** the 18 Windows failures did not reproduce on Linux: the 15 related specs (107 tests) pass with one worker and no retries. The Windows cause is unknown without the failing test names.

## Final cross-platform stabilization

- PowerShell 5.1: AST-based `check-powershell-compat.ps1` (no new dependency; wired into `check-powershell.ps1` and `test_powershell.py` with negative fixtures). Repository result: 0 errors, 9 warnings; static only.
- Windows secret ACLs: `--init-secret` now restricts the new file on Windows (deleted if that fails); `manage-server-service.ps1` refuses link/directory secret paths, `Upgrade` checks the installed configuration before changing files, and `-Action RepairSecret [-ConfirmSecretRepair]` repairs only the configured secret. A mask bug (READ_CONTROL/SYNCHRONIZE counted as access) was found and fixed by the new lifecycle tests.
- Backend regression on Python 3.12: 1,760 tests OK, 2 skipped. One intermediate failure (script inventory table missing the new script) was fixed and the whole suite rerun.
- Playwright: Windows failure details were not recoverable from the repository or logs; nothing was changed speculatively.

## Test architecture optimization (November 2026)

- **Audit (measured unless noted):** 1,760 backend tests in 109 modules; 909 browser tests in 111 specs, no Playwright projects, so every theme/viewport
  expansion lived inside specs: 62 generated groups, 295 executions, 31 of them (161 executions) without theme-dependent assertions; no pixel
  comparison exists (screenshots are review artifacts only). A passing Linux backend run printed 250 lines from 111 tests (release/packaging
  script output, expected `sap-lens` warnings, 2 ResourceWarnings).
- **Backend:** `run-tests.py` workers buffer output per test (shown only on failure), print a heartbeat, list ResourceWarnings and the slowest
  tests; `--verbose`, `--test NAME`, `--slowest N`, `--log FILE`. CSV preservation tests assert their warning with `assertLogs`. Two unclosed
  pipes fixed. `test_source_refresh` readers yield the GIL: 27-30 s to 0.4 s, plus a guard that a dead reader fails the test (it previously
  passed with crashed readers). `test_sod_reports.test_status_labels_*` (the interrupted Windows test) takes 0.8 s on Linux and has no
  blocking code; the Windows traceback only shows where Ctrl+C landed, so no hang is claimed or fixed.
- **Browser:** `tests/matrix.ts` (`layoutMatrix`, `THEMES`, `DEFAULT_THEME_ONLY`) for 25 theme-independent groups (909 to 857 executions;
  every width kept, dark kept once per screen); tags `@visual` (298), `@a11y` (79), `@workflow` (9), `@component` (10), `@smoke` (12) with npm
  scripts; Component Library previews for eight shared components and `component-library.spec.ts`.
- **Full regression (Linux, 4 vCPUs, 18 min 11 s wall):** backend 1,763 OK, 2 skipped (92 s, 3 processes); browser 867 OK, 0 skipped (971 s, 3
  processes, 2,811 process-seconds); build, docs, workflows, Lucide, ruff, ESLint (115 warnings), whitespace, `pip check`; unit 27 OK;
  PowerShell check 0 errors. Earlier reference (1 Nov, same runner type, different test set): 731 browser tests in 4,265 process-seconds.
  Backend log of a passing run: 40 lines, none of them test output.
- **Not verified:** native Windows (backend and browser), Windows PowerShell 5.1 execution; Node 24 (the sandbox has Node 22).

## Test suite consolidation and risk-based profiles (November 2026)

- **Audit (measured):** backend 1,763 tests in 109 modules, 234.6 s on one process (92 s on three); browser 867 executions, 625 unique
  scenarios, 2,811 process-seconds. No literal duplicates in either suite (AST and normalized-body comparison). Screenshots cost about
  31 s per run (1%). Nine Playwright tests exercised pure `src/lib` functions without a page; two others checked only the API.
- **Profiles:** `quick` (no browser, change-aware), `targeted` (import-graph selection), `regression` (curated, 1,431 backend + 123 browser
  tests), `full` (everything, release checks included). `fast`/`release` remain aliases; CI `changed` is unchanged; `validate.py` delegates.
  Coverage map fields (owner, criticality, platform) and a `profiles` block in `test-map.json`.
- **Moved:** 9 Playwright tests to `frontend/tests/unit` with one-to-one assertions; `saved-filter-migration.spec.ts` removed.
- **Fixed on the way:** Playwright imported and ran the `node:test` files (testMatch); `--log` missed stderr; parallel shard failures could
  print no error (now taken from the JSON report); nine one-shot `count()` reads raced rendering under load (one confirmed failure).
- **Measured (Linux, 4 vCPUs, 3 browser processes unless noted):** QUICK 11 to 50 s (old per-edit `fast`: 65 s, smoke only); TARGETED
  2 min 27 s (backend change) and 5 min 24 s (SoD frontend change); REGRESSION 4 min 42 s (the old `regression` was the complete suite,
  18 min 11 s); FULL 17 min 42 s, with one intermittent browser failure in each of three 3-process runs (different tests; one root-caused
  and fixed, two not reproducible alone or under a 3-process stress run); browser half with 1 process after the fix: 858/858, 26 min.
- **Open:** confirmation for removing two API-only browser tests with near-equivalent backend tests; 1600 px variants are only partly
  redundant (Diagnostics changes layout at 1400 px); native Windows unverified.

## Follow-up: integration tests, 3-process stability and SoD selection (November 2026)

- `revision-consistency` (API revision through `/api/refresh`) and the SoD export group-column check stay: tagged `@integration`,
  excluded from REGRESSION through `profiles.full_only_tags`, run by TARGETED and FULL.
- 3-process intermittents: `release-roles` read the clipboard before the asynchronous copy finished (reproduced 4 of 6 runs with CDP
  CPU throttling and random API latency; fixed by waiting for the application's announcement, 10 of 10 under the same load);
  `sod-reviews-r6` counted tiles before they rendered (fixed earlier). `session-recovery` and `investigation-filter-refinement`
  did not reproduce under x10 throttling and 1.5 s latency; no speculative change, and failures now print their error.
- SoD TARGETED: page-level selection through the import graph (`profiles.page_specs`); Periods change 2 min 6 s, bulk review 4 min 11 s,
  shared SoD files still all 31 specs.
- FULL, one uninterrupted run with 3 browser processes: backend 1,776 OK (2 skipped), browser 858 OK, all static, unit, audit and
  PowerShell checks OK, 18 min 11 s. Native Windows unverified.

## Windows test infrastructure and regression stabilization (November 2026)

- One interpreter: the test server and every spec subprocess use the runner's Python (`frontend/tests/python.ts`), never PATH's first
  `python` (the Windows FULL had spawned a global Python 3.15).
- Runner lifecycle: Windows-safe process-tree termination, handles closed before bounded cleanup retries, failed runs keep their
  artifacts in `build/test-artifacts/`, stage/heartbeat/shard output, exit codes 0 (pass), 1 (tests failed), 2 (infrastructure only).
- Root causes fixed: Capture sent `expected_revision` 0 while the period list was still loading (409, the created period never opened;
  application fix plus regression test); clipboard read-backs returned an earlier test's copy (specs now assert the page's recorded
  `writeText`); `page.unroute()` continued an in-flight request under an asynchronous handler ("Route is already handled!"; now
  `unrouteAll({ behavior: 'wait' })`). Each was reproduced before and verified after its fix.
- Verified on Linux with Chromium 1248: REGRESSION (3 processes) 1,566 passed, 2 skipped, 4 min 38 s; the 17 previously failing spec
  files 161 passed in 3 processes; FULL 2,645 passed, 0 failed, 2 skipped, 15 min 45 s; `pip-audit` clean. Native Windows unverified.

## Windows TARGETED follow-up: stale-row bulk selection (November 2026)

- Windows TARGETED (5 features, 3 processes): 664 passed, 1 failed (`sod-bulk-review` "a rejected request never reports success").
- Root cause, application: while a filter change loads, Access Explorer Assignments keeps the previous rows visible as placeholders and the
  page and row checkboxes stayed enabled. "Select all assignments on this page" then selected rows outside the new filter (reproduced on
  Linux with a delayed filtered response: 14 instead of 1, "Recommend removal for 14 assignments"). Selection is now disabled while rows
  are placeholders; a regression test holds the filtered response and checks that nothing stale can be selected.
- Slow SoD endpoints (Windows request log, single process, 24,942 requests): no 5xx and no unanswered requests. `GET /api/sod/periods`
  p50 14 ms, p95 2.4 s; `GET /api/sod/overview` p50 240 ms, p95 3.1 s; the slow cases follow data changes (new seeds, decisions).
  `GET /api/sod/filter-options` is the largest total (757 calls, 116 s). Performance, not faults; no further change without a profile.
- `WinError 10054` (3 per run): asyncio's Proactor transport logs a `ConnectionResetError` when it shuts down a socket the client already
  reset (pages closing, aborted requests). Every request in the log has a response, so these are expected client cancellations.


### Windows regression handover: report persistence follow-up

Resumed from synchronized `ef0c303`, preserving `935611b`, `3a79e41`,
`deb84da` and terminal colours from `0de47c2`. No current final FULL log or
JSON report was available in the accessible handover material; historical
FULL counts above are not evidence for this checkout. Native Windows
acceptance remains pending. No broad regression or CI dispatch was run.

A focused run passed all 18 SoD metadata tests, but its JSON report failed
because the requested parent directory did not exist. The runner printed a
successful result before raising `FileNotFoundError`. Reporting now creates
parent directories and handles destination I/O failures as infrastructure
failures (exit 2), preserving exit 1 when tests actually failed. Final status
is printed after report persistence. Three direct regression tests passed;
18 terminal/logging tests passed. Search-matching unit tests: 3 passed.
Focused ESLint: no errors, five existing warnings. Frontend production build
including TypeScript passed. Period deletion browser test: 1 passed on Linux
Chromium; two subsequent repeated-isolation executions also passed (2/2).
Generated logs/reports stay under ignored `build/` and are not committed.

Windows follow-up (PowerShell 5.1 or 7; stop if synchronization fails):

```powershell
git fetch origin
git switch work
git merge --ff-only origin/work
py -3.12 --version
node --version
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --spec sod-periods --grep "period deletion requires the typed name" --repeat-each=2 --browser-jobs 1 --log build/test-logs/windows-periods.log --report build/test-artifacts/windows-periods.json
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --base ef0c303 --browser-jobs 3 --log build/test-logs/windows-targeted.log --report build/test-artifacts/windows-targeted.json
```

Use the equals form `--repeat-each=2` with this runner: the separated numeric
value can be parsed as a feature name by argparse. TARGETED selects changes
against the explicit baseline; inspect with `--plan` first. The three browser
processes use the runner's separate ports and storage. These are follow-up
commands, not a claim that Windows or broad TARGETED validation has passed.


### Windows seven-spec follow-up: asynchronous completion assertions

The supplied `windows-verification.zip` was extracted outside the repository,
without changing the original evidence. Its latest seven-spec run reports
78 passed / 2 failed / 0 skipped, build and TypeScript passed. The archive
contains JSON, console/progress and server logs, but not the `trace.zip`,
error-context or screenshot files referenced by the JSON. Their absolute
Windows paths are not accessible here. Older `level1`, `level2` and broader
TARGETED results in the same archive are separate runs, not current evidence.

**Session Recovery:** the original assertion starts its five-second UI budget
as soon as Retry's click completes, before the asynchronous configuration read
has completed. It now waits for the successful GET configuration response,
then retains the original notice-count, navigation and URL assertions. No
notice is hidden and no timeout was increased. Individual Linux reproduction
passed before changes. A controlled late-request experiment did not establish
an application defect; no speculative session state-machine change was kept.
Classification: test synchronization gap corrected; the precise Windows
failure sequence remains unconfirmed without the original trace/native rerun.

**Bulk Keep:** the failure was the final Work Queue navigation assertion, after
all subject, assignment decision, history, queue API, coverage and remediation
assertions had succeeded. This rules out failure to seed or save that assignment
at the preceding API checks. The test now awaits the Work Queue response,
asserts the expected user exists in that response, then retains the exact UI
row assertion. The same check covers Keep, Remove and Investigate. No review
rule, filter default, cache or application code changed. Classification: test
synchronization gap corrected; Windows rendering/filter causality still needs
native confirmation. Existing regression tests were strengthened, not skipped.

Validation before the seven-spec checkpoint: both original tests passed
individually on Linux; corrected tests passed three times each (6/6); both full
specs passed (16/16); focused ESLint passed with no warnings/errors. No backend
or production frontend source changed, so prior build/type evidence was reused.
No FULL regression, package build or GitHub Actions dispatch was performed.

**Performance:** Windows logs show successful but slow reads across all three
servers, including `/health` (4730–5013 ms) and diagnostics (4211–5265 ms).
The health handler reads the cache snapshot without a SQLite query or lock;
those timings alone do not establish database contention or expensive SoD
calculation. Single-process Linux endpoint measurements during the 16-test run:
health 1 request, max 357 ms; diagnostics 28 requests, mean 16.5 / max 67 ms;
filter-options 368 requests, mean 24 / max 54 ms; selection 36 requests,
mean 14 / max 25 ms. Cross-OS numbers are not a controlled performance
comparison. CPU/thread-pool contention, startup and host scheduling remain
possible; no bottleneck was confirmed and no caching optimization was made.
The Windows reset traceback is in asyncio Proactor connection shutdown,
not an application route. No accompanying process termination or HTTP 500 is
shown; remaining tests continued. No unsafe suppression or transport workaround
was added. Its exact connection/request correlation is unavailable.

Windows follow-up (PowerShell 5.1/7, existing prepared `.venv`): preserve the
original files and use new output names. Run these progressively; stop at the
first failure. Keep the request log to compare one versus three processes.

```powershell
git fetch origin
git switch work
git merge --ff-only origin/work
$env:SAP_LENS_TEST_REQUEST_LOG = Join-Path $PWD 'build/windows-followup-requests.log'
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --spec session-recovery --spec sod-complete-bulk --grep "a temporary connection loss|complete bulk Keep reviews active non-conflict" --repeat-each=3 --browser-jobs 1 --log build/windows-followup-repeat.log --report build/windows-followup-repeat.json
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --spec session-recovery --spec sod-complete-bulk --browser-jobs 1 --log build/windows-followup-specs.log --report build/windows-followup-specs.json
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --spec session-recovery --spec ui-polish-actions --spec employee-directory --spec sod-complete-bulk --spec sod-metadata --spec investigation-ux --spec data-aware-ux --browser-jobs 3 --log build/windows-followup-seven.log --report build/windows-followup-seven.json
Remove-Item Env:SAP_LENS_TEST_REQUEST_LOG
```

Only after the seven-spec Windows group passes, proceed to the previously
selected TARGETED feature group if broader verification is desired. Native
Windows validation remains pending; Linux success does not close that gap.

Seven-spec Linux checkpoint completed: **80 passed, 0 failed, 0 skipped**,
188.5 seconds, three isolated Playwright processes. Both previously failing
cases passed in this group. All original assertions remain. Documentation
check: 62 Markdown files, zero broken internal links; `git diff --check` passed.
Three-process request measurements (combined independent server logs):

- `/health: n=4, mean=301.0 ms, max=447 ms`
- `/api/diagnostics: n=178, mean=25.2 ms, max=108 ms`
- `/api/sod/filter-options: n=464, mean=38.5 ms, max=138 ms`
- `/api/sod/explorer/access_list/selection: n=35, mean=22.5 ms, max=51 ms`

These are Linux observations, not a Windows benchmark or proof of native
resolution. Uploaded artifacts and generated results remain outside Git.


### Windows REGRESSION repair following the green 80-test verification

The supplied Windows verification-3 reports 80/80 passed. The subsequent
REGRESSION reports backend 1431 passed, 37 failed, 50 skipped; browser stages
executed no tests because CMD treated regex pipes as commands. Static checks
passed. Artifacts were inspected outside Git; original files were preserved.

- **Invocation:** launching `npm.cmd` lets Windows CMD interpret unquoted
  regex `|` operators. Browser stages now invoke the installed Playwright CLI
  through Node directly, with an argv list and no shell. Selection, reporters,
  isolated ports/storage and process cleanup are unchanged. The executable
  lifecycle-test double remains supported. A new argv round-trip test includes
  pipes, ampersands, spaces and parentheses and executes Node on either OS.
- **Maintenance isolation:** desktop maintenance checks both the global session
  mutex and the per-store lease. Separate temporary stores did not isolate the
  global Windows mutex across test workers or an open desktop application.
  Maintenance fixture families now select a UUID-scoped real Windows mutex.
  Production retains `Local\SAPLensDesktop` by default and every per-store
  lease check. No lock is bypassed. Tests cover default/custom kernel names and
  existing running-store refusal. Native Windows contention still needs rerun.
- **Console:** SafeConsole previously forced ASCII on every redirected Windows
  stream, even an explicitly UTF-8 stream. UTF-8 streams now preserve Unicode;
  legacy code-page streams retain ASCII fallback. Log/colour tests remain intact.
- **Position Changes:** a fixed-clock reproduction confirmed reliance on strict
  timestamp ordering. Windows can record a decision and the next change on the
  same clock tick; sorting tied events by hash also loses publication order.
  Stable timestamp sorting preserves append order. New Account Review decisions
  capture the exact position/manager change IDs they reviewed; later IDs reopen
  review even with equal timestamps. Old decisions keep their timestamp fallback.
  No old decisions/history are rewritten. Tests freeze both clocks and verify
  later-change reopening and expiry, plus reverse-hash equal-time ordering.

Focused Linux checks: 81 affected tests passed; 160 direct-dependent tests
passed, including runner, Account Review, position changes and desktop tests.
The stricter equal-clock case passed separately after freezing both clocks.
Ruff and whitespace checks passed. These counts overlap; they are not a unique
combined test total. Native Windows verification remains pending.

Windows PowerShell 5.1/7 follow-up, with the existing prepared `.venv`:

```powershell
git fetch origin
git switch work
git merge --ff-only origin/work
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --test test_test_profiles --test test_application_backups --test test_maintenance --test test_storage_migration --test test_position_changes --test test_account_review --test test_desktop --jobs 1 --log build/windows-repair-focused.log --report build/windows-repair-focused.json
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --test test_application_backups --test test_maintenance --test test_storage_migration --jobs 3 --log build/windows-repair-locks.log --report build/windows-repair-locks.json
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --spec session-recovery --grep "a clean start|a temporary connection loss" --browser-jobs 1 --log build/windows-repair-browser.log --report build/windows-repair-browser.json
```

Stop on any failure. After these pass, run the existing REGRESSION command with
new log/report names. No FULL, CI dispatch, main change or release is required.


The first local REGRESSION attempt exposed a source-contract dependency:
`tests/instance_name.py` parsed the literal CreateMutexW call. It now reads the
constructor's production default using AST, keeping the smoke-script match
assertion intact. Its 13 tests passed. That run was interrupted before browser
expansion and is not a passing REGRESSION result; its separate log is preserved.
The final run uses `windows-regression-repair-final.log` and the matching JSON.


After the focused Windows commands pass, the requested native checkpoint is:

```powershell
.\.venv\Scripts\python.exe scripts/run-tests.py regression --jobs 3 --browser-jobs 3 --log build/windows-repair-regression.log --report build/windows-repair-regression.json
```

The browser check includes a literal pipe expression to verify argument
transport. No CMD quoting workaround or shell retry is needed. Original
Windows artifacts stay outside Git and are not overwritten by these commands.


Final local Linux REGRESSION completed successfully in **7:52**: backend
**1472 passed**, critical browser **90 passed**, tagged browser **33 passed**;
aggregate **1595 passed, 0 failed, 0 skipped**. Whitespace, documentation,
workflow contracts, ownership map, Python/frontend lint, TypeScript and frontend
unit checks all passed. A non-blocking ResourceWarning was recorded at
`test_validation_entrypoint.py:60` for an unclosed text stream. No unrelated
cleanup was added. FULL, dependency audits, packaging and native Windows
acceptance were not executed. The PowerShell commands above remain required
before declaring the Windows failures resolved on their target platform.


### Native Windows follow-up: newline policy and history-transfer fixture

Two remaining native Windows failures were traced to test fixtures, not to
UTF-8 degradation or changed maintenance safety:

- `PlaywrightCommandTests.test_utf8_pipe_on_windows_preserves_unicode` built
  a UTF-8 TextIOWrapper with the default `newline=None`. Windows translated
  the written LF into CRLF; the Unicode bytes were already correct. This test
  calls SafeConsole directly, not a subprocess. It now explicitly exercises
  both LF and CRLF output policies on every host and compares the complete
  output bytes against the exact UTF-8 encoding, preserving the accents and
  arrow assertion. Production stream/subprocess handling is unchanged.
- `ReviewHistoryTransferTests` inherits `PeriodV2Case`, not `BackupTests`, so
  the isolation added to BackupTests never ran for it. Its desktop backup
  therefore used the production session mutex and could conflict with a running
  desktop application or another maintenance fixture. Its own setUp now installs
  the existing UUID-scoped real Windows mutex factory before parent setup.
  A regression test verifies this fixture calls that factory with a test name
  rather than the production name. The factory owns no persistent kernel
  handles; maintenance's existing finally blocks close acquired handles, and
  unittest cleanup restores the factory even on failure. Production mutex
  defaults, per-store leases and live-store refusal checks are unchanged.

Focused Linux checks: 3 tests passed (the Unicode case includes LF/CRLF
subtests), including the byte-for-byte approved review history transfer.
Focused Ruff and whitespace checks passed. Native Windows execution is still
required; Linux uses the POSIX store lease rather than Windows kernel locking.

Windows PowerShell 5.1/7, after synchronizing a clean `work` checkout:

```powershell
git fetch origin
git switch work
git merge --ff-only origin/work
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --test test_test_profiles.PlaywrightCommandTests.test_utf8_pipe_on_windows_preserves_unicode --test test_application_backups.ReviewHistoryTransferTests --jobs 1 --log build/windows-newline-history-focused.log --report build/windows-newline-history-focused.json
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --test test_application_backups --test test_maintenance --test test_storage_migration --test test_test_profiles.PlaywrightCommandTests --test test_test_profiles.TerminalOutputTests --test test_test_profiles.ColorOutputTests --jobs 1 --log build/windows-newline-history-dependent.log --report build/windows-newline-history-dependent.json
```

Stop at the first failure. These commands use new artifact names and do not
run FULL, browser regression or GitHub Actions. Explicit `--test` selections
are executed together in one backend process by the current runner.

Direct-dependent Linux validation completed: **84 passed, 0 failed, 0 skipped**.
Documentation links: 62 files, zero failures. No FULL, REGRESSION, production
build or browser suite was rerun for these test-only changes.


### Browser backup subprocess: Windows mutex isolation

Native Windows REGRESSION isolated the remaining failure to the browser test's
synthetic archive generator. Its separate Python interpreter called desktop
`maintenance.backup()` with the production session mutex. A unittest patch in
the parent process cannot cross that process boundary, so a real desktop or
another default-mutex helper could make `acquire()` return false. This is a
test-process isolation defect; production refusal to back up a live instance
remains intentional. The browser-helper audit found no other maintenance
backup/restore call sites under `frontend/tests`.

The UUID-scoped patch mechanism is now shared in
`scripts/testing/desktop_test_mutex.py`. Existing backend fixtures delegate to
it, retaining their cleanup and real Windows acquire/close semantics. The
browser invokes `scripts/testing/synthetic-backup.py`, which uses that same
mechanism inside the child interpreter and explicitly points configuration and
data storage at a fresh temporary synthetic store. The chosen interpreter and
other process environment are inherited as before. Each invocation generates
its own namespace; no environment option bypasses production locking.

The scripts/testing location is already mirrored into isolated frontend build
workspaces; importing a backend Python test module here would have broken that
layout. No build/packaging implementation change was needed. All original
browser assertions and backup semantics remain intact. The new backend test
runs the actual generator as a child; on native Windows it holds a production
mutex handle during that operation, including when another desktop already
owns that name. Maintenance still closes its own handles in existing finally
blocks. Production lock defaults, storage leases and safety gates are untouched.

Linux validation: original browser test passed before the change (the native
mutex branch is Windows-only); corrected individual test passed; complete
backup spec 9/9 passed; direct-dependent backup/maintenance/migration tests
65/65 passed; focused Ruff and ESLint passed. Native Windows execution of the
held-production-mutex branch and the three-browser-process scenario remains
required before claiming native resolution.

PowerShell 5.1/7 follow-up (prepared .venv; new artifact names):

```powershell
git fetch origin
git switch work
git merge --ff-only origin/work
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --test test_application_backups.BackupTests.test_browser_archive_subprocess_is_isolated_from_the_production_mutex --jobs 1 --log build/windows-backup-child-kernel.log --report build/windows-backup-child-kernel.json
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --spec application-backups --grep "Settings backup requires restart" --browser-jobs 1 --log build/windows-backup-child-focused.log --report build/windows-backup-child-focused.json
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --spec application-backups --browser-jobs 1 --log build/windows-backup-child-spec.log --report build/windows-backup-child-spec.json
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --test test_application_backups --test test_maintenance --test test_storage_migration --jobs 1 --log build/windows-backup-child-backend.log --report build/windows-backup-child-backend.json
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --spec application-backups --spec desktop --spec enterprise --browser-jobs 3 --log build/windows-backup-child-parallel.log --report build/windows-backup-child-parallel.json
```

Stop if a step fails. Only after these pass, run the existing REGRESSION command
with new log/report names. An existing desktop can remain running for the
focused child-generator test: its kernel handle is neither released nor
modified by the test. No FULL, packaging, release or GitHub Actions run is needed.


Final local Linux results: targeted three-process browser verification **15/15**
passed. The subsequent requested REGRESSION passed in **8:02**: backend
**1474/1474**, critical browser **90/90**, tagged browser **33/33**, including
the failing backup workflow. Aggregate **1597 passed, 0 failed, 0 skipped**.
All included static, lint, TypeScript, frontend unit, documentation and workflow
checks passed. The known non-blocking unclosed-stream ResourceWarning at
`test_validation_entrypoint.py:60` remains outside this fix. Native Windows
kernel contention and the same three-process native run remain unexecuted
here; no FULL, packaging, release or GitHub Actions workflow was run.


### Functional Group reconfirmation and Windows server-fixture teardown

The reported native run passed 1474 backend tests (50 skipped), 88/90 critical
browser tests and 33/33 tagged tests. The current workspace did not contain its
failure artifacts. The old synchronization warning deliberately omitted the
exception: its exact native category cannot be recovered from that text. Logs
and traces were requested; native failure correlation remains pending.

**Functional Group storage:** public read() opened the JSON file without the
RLock used by mutators. Windows read handles can prevent atomic os.replace,
so concurrent request reads and review synchronization could conflict within
the same backend even though the update itself is transactional. A new direct
lock-ownership regression failed against the old code and passed after read()
and write() were protected by the same reentrant lock, including handle close.
Existing load/modify/write mutation boundaries remain protected. No blanket
save retries or reconfirmation-rule change was introduced. This is a confirmed
storage synchronization gap; matching it to the original native exception
still requires the native diagnostic evidence.

Synchronization failures now record only operation, root exception category,
errno and winerror, including a wrapped I/O cause. Exception messages, paths,
identities and payloads are excluded. A simulated sharing violation verifies
that failed persistence changes neither classifications nor history, logs the
safe category, and a later successful synchronization flags the Department
change exactly once. The browser test now also asserts the classification API
requires review before keeping all its original UI reconfirmation assertions.

**Server cleanup:** the fixture previously sent SIGTERM to one spawned process,
waited only for exit, then immediately called rmSync. On Windows this does not
establish descendant termination (notably with a Python venv launcher), close
completion or file-handle release. The new test-only server-process helper
observes close from spawn time and terminates the owned Windows PID tree with
bounded taskkill /PID /T /F before waiting for close. POSIX uses an isolated
process group, graceful termination and bounded force escalation. No process
is selected by name. Windows directory deletion then uses Node's bounded
transient-error handling (five retries, 100 ms linear backoff, at most 1.5 s
added delay). Persistent EPERM still fails teardown and reports the retained
temporary directory. Neither the error nor a leftover directory is suppressed.
The original native EPERM handle owner cannot be proven without its artifacts;
no Defender/permission-policy cause is assumed.

Four node tests cover owned PID targeting, exit versus close ordering, already
closed children, termination errors, shutdown deadlines and deletion failure
propagation. The original server upload/metadata assertions are unchanged.
Linux focused evidence: both original scenarios passed individually before the
fixes; the lock regression reproduced the unprotected read; Functional Group
backend module 53/53 passed; direct-dependent modules 94/94 passed; cleanup
unit tests 4/4 passed. Complete browser specs passed independently (Functional
Groups 9/9, server-deployment 5/5). Three-process relevant browser selection
passed 7/7. Ruff passed; focused ESLint had no errors and one pre-existing any
warning in server-deployment.spec.ts. No unrelated files were removed or edited.

Native PowerShell 5.1/7 follow-up (prepared .venv; retain old artifacts):

```powershell
git fetch origin
git switch work
git merge --ff-only origin/work
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --test test_functional_groups --test test_position_changes --test test_account_review --jobs 1 --log build/windows-fg-storage.log --report build/windows-fg-storage.json
node --test frontend/tests/unit/server-process.test.ts
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --spec functional-groups --browser-jobs 1 --log build/windows-fg-spec.log --report build/windows-fg-spec.json
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --spec server-deployment --browser-jobs 1 --log build/windows-server-cleanup-spec.log --report build/windows-server-cleanup-spec.json
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --spec functional-groups --spec server-deployment --spec account-review-refinement --grep "Department|headless browser|browser uploads|review findings" --browser-jobs 3 --log build/windows-fg-cleanup-parallel.log --report build/windows-fg-cleanup-parallel.json
```

Stop at any failure and preserve the complete shard output/traces, including
any new organizational_sync category/errno/winerror. Only after these pass,
run the requested REGRESSION with fresh log/report names. Native kernel/file
locking and three-process Windows cleanup remain unexecuted here. FULL,
packaging, releases and GitHub Actions are excluded from this task.


Requested final local Linux REGRESSION passed in **6:08**: backend **1476/1476**,
critical browser **90/90**, tagged browser **33/33**; aggregate **1599 passed,
0 failed, 0 skipped**. Both affected critical workflows and fixture teardown
passed. All included static, documentation, workflow, lint, TypeScript and
frontend unit checks passed. These are Linux results, not proof of native
Windows file sharing or descendant termination. No FULL, packaging, release
or GitHub Actions workflow was executed. Original native exception correlation
and the PowerShell checks above remain outstanding.


### CI script inventory and Windows shared-build validation

Safely fast-forwarded a clean `work` from `002af1c` to the owner's merged
`origin/main` commit `fdc41bb`; no main branch checkout or modification was
performed. Existing implementation history and generated files were preserved.
The actual failed CI job (run 42900693579 / job 130125567334) was read without
dispatching anything. It failed only
`test_unified_build.ScriptInventoryTests.test_every_tracked_script_is_documented_in_the_build_guide`,
listing `testing/desktop_test_mutex.py` and `testing/synthetic-backup.py`.
The uploaded native `build.log` independently identifies the same test and
same omissions (lines 152–159): this confirms the Windows failure, rather than
assuming it from matching counts. Packaging was correctly blocked before any
desktop/service package attempt.

`docs/BUILD.md` now documents both internal test fixtures in its existing
inventory table. Verification covers all **70 tracked script files**, including
the existing build_system wildcard; omissions are zero. The inventory test was
not weakened or changed. The canonical public entrypoint remains
`scripts/build.ps1`; no root-level bootstrapper was created. A search of the
README, documentation and script index found no stale root `.\build.ps1`
command examples needing replacement.

Shared validation in `scripts/deployment/build-deployments.py` runs
`run-tests.py targeted deployment --backend` for normal builds, and the backend
REGRESSION profile only when full scope is explicitly selected. The normal
17-module selection includes the inventory test. Before the documentation fix,
its local reproduction matched **341 passed, 1 failed, 21 skipped**, with the
same inventory failure. After the fix it passed **343, 0 failed, 21 skipped**
(the added diagnostic regression test is included). The earlier green curated
REGRESSION did not replace these build/deployment tests, which are outside its
release/packaging selection.

A related reporting gap was corrected minimally: the final 20 output lines can
be entirely skip messages, hiding a failing test in the build summary. Build
StageFailure now separately extracts bounded, redacted unittest identities
from complete captured output, prints them and preserves `failed_tests` in the
manifest. Its detailed log path and existing output tail remain. A regression
test proves identity retention beyond 25 skip lines and duplicate normalization.
Existing shared-validation failure propagation and blocked desktop/service
manifest contracts pass; no validation gate was bypassed.

Windows PowerShell 5.1 **or** 7 satisfies the packaging prerequisite. PowerShell
7 is optional; its parser/bootstrapper checks remain explicitly skipped when
pwsh is absent. No dependency was installed or compatibility claimed from a
skip. Windows symlink privilege skips likewise do not alter link protections.
This host has no PowerShell executable, so only source/command contracts ran.
A direct Windows all-target build dry-run was correctly rejected on Linux
(exit 2, native runner/explicit remote builder required); no package was built.

Targeted local checks: unified build, diagnostic and workflow modules **99
passed / 1 skipped**; expanded Windows-stage/PowerShell/build contracts **136
passed / 18 skipped**; shared backend build selection **343 passed / 21 skipped**.
These scopes overlap. Documentation check passed for 62 Markdown files;
workflow contracts, focused Ruff and whitespace checks passed. Original CI
and Windows log files remain outside Git. No FULL, packaging, release or
GitHub Actions dispatch was performed.

Native PowerShell 5.1 retry sequence (prepared environment, clean checkout):

```powershell
git fetch origin
git switch work
git merge --ff-only origin/work
.\.venv\Scripts\python.exe scripts/run-tests.py targeted deployment --backend --log build/windows-build-gate.log --report build/windows-build-gate.json
powershell -NoProfile -File .\scripts\build.ps1 -Mode build -Platform windows -Target all -NonInteractive
```

Stop if backend validation fails and retain its named failing tests, build.log
and build-manifest.json. Native PowerShell execution, PyInstaller, service and
installer packaging still require Windows verification. The confirmed blocking
inventory defect is fixed; packaging is ready to retry, not claimed successful.


Final diagnostic validation also consumed the actual uploaded Windows build
log: one correctly deduplicated failing inventory-test identity is retained,
including unittest contexts that already contain the method name. The expanded
34-test build diagnostic module passed after adding that real-log format.
Final local REGRESSION passed in **6:19**: backend **1476/1476**, critical browser
**90/90**, tagged browser **33/33**, aggregate **1599 passed, 0 failed, 0 skipped**.
All included static, lint, TypeScript, unit, documentation and workflow checks
passed. The existing non-blocking ResourceWarning at
`test_validation_entrypoint.py:60` remains. The curated profile's zero skips do
not replace the separately reported unavailable PowerShell checks above.
Native Windows packaging and PowerShell execution remain unverified here.


### Windows Desktop EXE smoke: readiness versus configuration

Observed native smoke failure: first-launch health `needs_configuration`, with
an owned backend ready and WebView2 started, while the smoke expected `ok` and
two roles. Production `/health` deliberately reports `needs_configuration` for
no successfully loaded dataset or an unsuccessful initial load. `/health/ready`
is the independent process-readiness contract. Desktop supervision already
accepts known `loading`, `ok`, and `needs_configuration` application states
with strict app/instance identity and live-worker checks. Production health
and startup code were not changed to force an `ok` result.

The old smoke called a preconfigured synthetic installation `first-launch`
and required `ok`/2 universally. Its legacy CSV path fixture *does* load in
source mode: contrary to an initial hypothesis, Role Catalogue defaults to
Dynamic, not Static. The packaged import's exact failure cause cannot be
established without its application log (requested). The revised smoke does
not hide such a failure: a new explicit configured case still requires `ok`/2,
and reports `configuration_required` when that expectation is unmet.

The first-launch scenario is now truly unconfigured and requires exactly
`needs_configuration`/0. Configured, configured relaunch and port-conflict
scenarios require exactly `ok`/2 with an explicit schema-3 Dynamic synthetic
source. Relaunch reuses the configured installation. All successful scenarios
also require HTTP 200 `ready` from `/health/ready`; other states do not pass.
Diagnostics show scenario-specific expected configuration/count separately
from process readiness, and distinguish configuration-required from service
identity/startup failures. Readiness deadlines were not increased.

Fixture launches explicitly isolate CONFIG_DIR, DATA_DIR, desktop deployment
mode and DATA_CSV_PATH, restoring the caller's values afterward. The minimal
PATH requirement, runtime ownership, per-session mutex, loopback checks,
version validation, authentication/CORS checks and owned-process cleanup are
preserved. Fresh launch also retains duplicate-instance coverage.

Tests added cover real source-mode API states for fresh, loading, configured
legacy source and missing source; existing Desktop tests continue to reject
wrong app/instance, unknown states, exited workers and redirected probes.
Smoke contracts enforce exact scenario mapping, strict cached counts,
independent readiness, environment restoration and unknown-scenario rejection.
The initial new TestClient setup was corrected to use the required loopback
Host; no production Host boundary was weakened.

Targeted Linux results: direct health cases 2/2 passed; complete Desktop and
smoke-contract modules 59/59 passed; packaging/stage/startup contracts plus
health tests 63/63 passed; final smoke-isolation contracts 16/16 passed. Scopes
overlap. Ruff/whitespace checks passed. No PowerShell executable or native
Windows EXE is available here, so PowerShell parsing/execution and packaged
WebView2 acceptance remain pending; static contracts do not count as native
passes. No service packaging behavior changed.

Native follow-up after safely syncing `work`:

```powershell
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --test test_desktop --test test_desktop_smoke_script --test test_windows_stages --test test_windows_package --test test_startup_session --jobs 1 --log build/windows-exe-health-contract.log --report build/windows-exe-health-contract.json
powershell -NoProfile -File .\scripts\check-powershell.ps1
powershell -NoProfile -File .\scripts\test-windows-exe.ps1 -ExecutablePath .\backend\dist\SAP-Lens.exe
```

Use the actual built artifact path. If configured still fails, preserve its
full smoke diagnostic and application log: do not accept needs_configuration
for that case or claim its two-role import passed. The known fresh-install
contract is corrected; the original packaged seeded-import cause is still
unconfirmed. No GitHub Actions, main merge or release is authorized here.


The subsequently uploaded `sap-lens-desktop-smoke-diagnostics.zip` was inspected
outside Git. It confirms the old smoke script seeded a legacy CSV-path setting,
the runtime PID belonged to the launched tree, WebView2 started, startup reached
ready at **4953 ms**, and health reported needs_configuration with zero roles.
Service packaging passed. The archive contains build logs/manifest and the old
smoke script, but only the reporter's **25-line application-log tail**, not the
scenario settings or complete sap-lens.log. It therefore does not establish why
that seeded path failed in the packaged app. No hidden-import or CSV failure
cause is asserted from unrelated negative test output in the build log.

Future smoke diagnostics additionally print only settings/source presence,
source existence and a whitelisted source mode; no settings values or source
paths are printed. This helps distinguish absent configuration from a failing
configured source without exposing credentials/data. The final 17 smoke-contract
tests passed after adding this diagnostic regression. Native configured import
acceptance remains deliberately strict at ok/two roles, so this change cannot
turn that unresolved package/data failure into a passing fresh-install result.

Final requested local **REGRESSION passed in 6:07**: backend **1481/1481**,
critical browser **90/90**, tagged browser **33/33**; aggregate **1604 passed,
0 failed, 0 skipped**. Documentation links, workflow contracts, test ownership,
Ruff, ESLint, TypeScript and frontend unit checks also passed. Evidence:
`build/test-logs/exe-health-regression.log` and
`build/test-artifacts/exe-health-regression.json` (local generated artifacts).
The final value-free diagnostic contract was added after the backend stage;
its affected smoke-contract module was separately rerun, **17/17 passed**.
No application/frontend production code changed. A new frontend production
build, FULL, security audits, native packaging and Windows/WebView2 execution
were not performed. REGRESSION is the curated profile, not the complete suite.

## Desktop smoke App Control classification and safe diagnostics

Baseline: `aec1cf5`; branch `work`. The supplied native report establishes a
**pre-process Windows application-control block**: launcher/runtime PID zero,
no runtime record/application log, correlated Code Integrity events 3077/3033,
enforced policy and unsigned EXE. It does not establish why an earlier artifact
was allowed or whether policy, trust, location or artifact identity changed.
No security-policy change, signing, certificate installation or bypass is made.
The earlier running-backend/configured-CSV failure is a separate unresolved issue.

Inspection: Windows desktop remains PyInstaller one-file/windowed/noupx, with
version/icon/resources/frontend bundled by `scripts/build_system/windows/stages.py`.
The orchestration still invokes `scripts/test-windows-exe.ps1`; `Start-Process`
launches the resolved EXE with an isolated source environment/minimal PATH. No
packaging metadata, extraction strategy or launch mechanism was changed in this
work. Neither packaging success nor `NotSigned` alone explains changing policy
acceptance between builds.

Implemented:

- Structured nested Win32 error extraction. Native 1260 or exact time/path-
  correlated blocking events classify `windows_application_control_blocked`;
  other launch errors remain `process_creation_failed`. Error 577 and unsigned
  status alone do not assert WDAC. Every blocked/failed creation remains a failure.
- Read-only Code Integrity query: 3077/3033, attempted launch ±2 seconds, maximum
  128 events; checks event timestamps and exact `FileName`, not parent name or
  basename/suffix. NT device paths use QueryDosDevice mapping. Unavailable logs,
  drive mapping, signature inspection or malformed events report limitations;
  diagnostic failures preserve the original exception and known policy category.
- Safe signature status, native error, event/policy IDs, executable-started flag
  and administrator-approved deployment guidance. No policy changes or elevation.
  A failed start adds no owned process handle; existing ownership-only cleanup,
  mutex, security, readiness and fresh/configured exact-count checks remain intact.
- Safe fixture/schema/path/readability/size diagnostics and bounded allowlisted
  initialization/import evidence. No CSV contents or settings values are logged.
  Configured CSV success is not claimed until a native run passes `ok`/two roles.
- Added executable PowerShell-function tests with mocked OS/event/signature calls
  for success, wrapped policy error, inaccessible log, NT path/policy correlation,
  unrelated/old/audit events and diagnostic-failure/no-process ownership. These
  require PowerShell; Linux structural tests do not substitute for their execution.

Direct validation initially exposed a structural syntax guard treating NT path
and regex literals as new PowerShell operators. The guard now excludes literal
single-quoted strings; actual 5.1 parsing remains a native follow-up. Direct
contracts: 25 discovered, **19 executed successfully / 6 skipped** (PowerShell
unavailable), no failures. The runner displays discovered tests as passed even
when it also lists skips; the counts here distinguish actual execution. No test
is skipped to conceal an observed Windows failure.

Native follow-up commands are in
[Windows Desktop: App Control](../deployment/WINDOWS_DESKTOP.md#app-control--wdac-blocks-before-startup).
Run the PowerShell parser, direct tests (including mocked OS behavior), then the
existing EXE smoke without rebuilding unnecessarily. If policy still blocks it,
retain the native code and correlated events and use organization-approved
signing/deployment. Only after launch is allowed can configured-import and
WebView2 acceptance be assessed. FULL, native packaging and GitHub Actions are
not executed by this task.

Affected Level 2 validation: five Desktop/smoke/stage/package/startup modules,
**115 discovered, 109 executed successfully, 6 Windows-only skips**, no failures
(`build/test-logs/wdac-affected.log`). Final structural contracts were rerun after
small diagnostic safeguards; 19 executed successfully / 6 Windows-only skips.
Documentation checker: 62 Markdown files, zero broken internal links; Ruff and
whitespace checks passed.

The requested REGRESSION was launched with `SAP_LENS_TEST_PROGRESS=summary`.
Its backend stage exposed an existing console-test environment dependency:
`ColorOutputTests.test_live_failures_and_summaries_are_coloured` expects PASS
lines that this summary-only option intentionally suppresses. The call log shows
the expected failure line and absent success line; no application failure is
inferred. With the invocation override removed, that exact test and all **12
ColorOutputTests passed** (`wdac-progress-env-recheck` / `wdac-console-contracts`
logs and JSON reports under `build/`). No assertions, test skip or product code
were changed to resolve it. The original REGRESSION is retained, not restarted;
its original nonzero outcome and focused recovery evidence are reported separately.

Final REGRESSION evidence (`build/test-logs/wdac-regression.log` and matching
`build/test-artifacts/wdac-regression.json`): **6:05, exit 1**, due solely to the
console-output environment assertion above. Backend: 1490 discovered, **1483
passed, 1 failed, 6 skipped**. Browser: **90 critical + 33 tagged passed**, zero
failures/skips. Whitespace, documentation, workflow contracts, ownership map,
Ruff, ESLint, TypeScript and frontend unit checks passed. The profile summary
counts skipped backend tests in its displayed passed number; executed counts
here exclude those six skips. One existing nonfatal resource warning reported
an unclosed file in `test_validation_entrypoint.py:60`. No unrelated repair was
made. The one failed test and its complete 12-test class passed without the
summary override; this is recovery evidence, **not a clean single-run REGRESSION
pass**. Do not restart broad suites just to replace this recorded outcome.

Implementation commit: `43b2a8f` (smoke script and regression coverage). Deployment
guidance and this validation record are delivered in the following documentation
commit. Four files changed; no production Python, build identity/version,
packaging configuration, dependencies, CI triggers or `main` changes. No native
Windows build, PowerShell execution, WebView2 acceptance, FULL, signing or policy
modifications were performed. Native acceptance remains pending, and the earlier
configured-CSV root cause remains unresolved.

## Packaged Windows CSV initialization — loose-source fingerprints

Baseline `69f0f3b`, branch `work`. The supplied native retry log confirms fresh
first-launch passed ownership/API/frontend/WebView2/CORS/shutdown; configured
launch was live but remained needs_configuration/zero roles despite a readable
162-byte Dynamic fixture and matching settings. It also reports backup_failed.
No private paths or source values from that log are committed.

**Reproduced cause:** `csv_lifecycle.source_fingerprint()` calls
`persistent_cache.code_digest()` before parsing. The latter read loose backend
`.py` files by `__file__`. PyInstaller ships those modules in its Python archive,
not as loose source files (the inspected packaging arguments bundle resources,
identity and frontend, not backend source). Missing source bytes cause a
FileNotFoundError before the CSV is parsed. Non-strict lifecycle loading catches
this as a failed per-source report; DataLoader's old exception-only warning does
not run, so the original log can have no explicit CSV failure. Cache activation
never occurs and health correctly reports needs_configuration with zero roles.
`data_loader: ready` previously meant only that its constructor returned.

The new source-mode test simulates frozen execution and a nonexistent bundle
source directory. Before the fix its valid case reproduced exactly
needs_configuration/zero roles instead of ok/two roles
(`build/test-logs/packaged-csv-reproduce.log`). After the fix it passes both the
valid and invalid source cases. This proves the failure mechanism; it is not a
claim that a new native Windows EXE has passed.

**Fix:** frozen fingerprints use the module loader's code objects (PyInstaller's
installed `PyiFrozenLoader.get_code` reads its PYZ archive), recursively normalize
extraction filenames, and hash module identity, Python cache tag and marshalled
code. Source checkouts still hash source bytes. Tests prove unchanged code has
an unchanged digest across extraction paths, changed nested code invalidates it,
and unavailable code fails explicitly rather than using a constant fingerprint.
An additional check verified identical real-module fingerprints across three
subprocesses with PYTHONHASHSEED 1, 2 and 3. No parser, import schema, activation
transaction, HMAC, cache payload, health contract or native security boundary
was relaxed. Built-in modules only; no new dependency or packaging data needed.

**Backup warning:** the same valid configuration/fixture migrates successfully
in a local source-mode reproduction. A forced pre-migration backup failure is
also followed by a successful frozen-simulation load, proving that backup_failed
does not inherently prevent the CSV from activating. Backup verification and
migration gates remain intact. The exact native backup exception is absent from
the supplied tail and remains unconfirmed; retain the full local application log
if it recurs. It is not asserted as the cause of the zero-role failure.

**Diagnostics:** loader construction now reports `created`; independent
`source_initialization` events report starting/ready/failed/unconfigured. Each
source activation reports operation, kind, status/category, skip reason and
record count. Per-source failures report phase, exception class and OS codes.
Unexpected initialization failures remain recoverable with a controlled message.
Tests assert missing-source logs contain both failure and activation evidence
without the private source path. The smoke summary recognizes these failures,
constructor/unconfigured events and the backup_failed marker. Exact fresh and
configured counts and all authentication/ownership/cleanup checks are preserved.

**Summary-output assertion:** reproduced behavior came from the console test
inheriting SAP_LENS_TEST_PROGRESS=summary while asserting per-test success lines.
The test now explicitly selects `tests` mode inside its environment fixture,
preserving its color, text and summary assertions and restoring the caller's
mode afterward. No runner behavior or failing assertion was weakened. All console
checks passed while the parent process remained in summary mode.

Level 1: four direct fingerprint/frozen-load/backup-failure cases passed, then
the safe-diagnostics test passed after correcting its log capture to include both
logger namespaces. Level 2: six complete affected backend modules, **204
discovered, 198 executed successfully, 6 Windows-only skips**, zero failures,
with SAP_LENS_TEST_PROGRESS=summary (`packaged-csv-affected.log` and matching JSON
under build/). Ruff, whitespace and internal documentation links passed. The
requested complete local REGRESSION is recorded below when it finishes.

Native commands are in
[Windows Desktop: packaged source initialization](../deployment/WINDOWS_DESKTOP.md#packaged-source-initialization-and-cache-identity).
Run targeted Windows tests, rebuild only Desktop once to incorporate the Python
fix, then retain all four EXE smoke scenarios. The old EXE cannot validate this
code change. Windows parser/mocked OS tests, native configured activation and
WebView2 acceptance remain pending here. No main, product-version, CI-trigger,
signing, release or security-policy changes; no Actions dispatched.

Final complete local **REGRESSION passed in one run, 7:34, exit 0**, with
SAP_LENS_TEST_PROGRESS=summary enabled: backend **1495 discovered, 1489 executed
successfully, 6 Windows-only skips**; critical browser **90/90**, tagged browser
**33/33**. Thus **1612 actual passed, zero failures, 6 skips**; the profile displays
1618 passed because its displayed backend count includes skipped cases. The
summary-output assertion passed inside this run, not only in an isolated recheck.
Whitespace, documentation links, workflow contracts, ownership map, Ruff, ESLint,
TypeScript and frontend unit tests all passed. Logs/report:
`build/test-logs/packaged-csv-regression.log` and
`build/test-artifacts/packaged-csv-regression.json` (local artifacts, not committed).
One existing nonfatal ResourceWarning remains in `test_validation_entrypoint.py:60`
for an unclosed file wrapper; unrelated code was left unchanged. This is the
complete REGRESSION profile, not FULL/all available tests. Unchanged frontend
assets were reused; no new native package or Windows smoke execution is claimed.

Delivery includes the frozen-code identity fix, initialization/activation
observability, regression coverage and isolated console-test mode, plus updated
Windows commands. Preserve App Control and verify the newly built Desktop EXE
on Windows before declaring the configured native installation fixed.

## Centralized build prerequisites and verified dependency acquisition

Baseline `dd6dee9`, branch `work`. The reported native Windows failure was
workflow_lint BLOCKED while downloading pinned actionlint 1.7.12 (HTTP 403).
The previous helper downloaded only when Repository lint ran, after expensive
frontend/Python/browser preparation. It had one network source, no bounded retry
policy, non-atomic cache writes and no extracted-tool version check. The exact
corporate proxy/authorization rule behind the 403 is not established; this task
does not assert that a User-Agent change or Linux success fixes it.

Audit/ownership:

- Existing `prerequisites.py`, `python_env.py`, `doctor.py` retain Python 3.12 x64
  discovery, Node 24–25/npm 10–11 compatibility, project venvs and lockfile-based
  installs. PyInstaller 6.22.3 and build/audit packages remain pinned by existing
  requirement files. No implicit host Python/Node installation or replacement.
- New `build_system/managed_tools.py` owns actionlint 1.7.12 archive pins and
  Inno Setup 7.1.0 bootstrap pins. `testing/ci.py` is an adapter; both Windows
  installer implementations delegate acquisition to that engine. Existing
  CURRENTUSER provisioning, compiler receipts and packaging verifiers remain.
- Host Git, PowerShell, Docker/Compose and service compiler checks remain
  target-specific. WebView2 remains a separate native runtime prerequisite.
  No new tool-manager dependency, installer framework or CI trigger was added.

Managed policy: explicit artifact, verified persistent/project/run/legacy caches,
configured approved HTTPS mirror, official upstream. Default ignored
`.build-tools/` survives normal build-output cleanup; verified old backend/build
archives are promoted. Archive SHA-256 precedes exact-member extraction; cached
and PATH executables must match the trusted archive, and actionlint must report
the exact version. No constant/unverified fallback. Downloads have size/time
bounds, three attempts maximum per source with exponential backoff for transient
failures, no repeated 403/404/TLS retry, no TLS downgrade, fsynced atomic publication
and kernel-owned cross-process locks. Missing cache in explicit offline mode is
blocked without network access. URL authentication/query data, internal mirror
paths and raw network exception text are omitted from failure messages.

Preflight: fresh local Windows validation resolves managed tools before
Environment/Python/frontend/test stages; packaging-tool versions are checked
before frontend compilation. Deployment shared validation resolves tools before
creating environments/frontend/tests, and prefetches the pinned Inno bootstrap
only on Windows when the selected deployment includes Desktop installers.
Receipt-reuse paths do not repeat unused lint acquisition; quick/dry-run/check-only
modes do not download tools. Explicit target prerequisite setup and setup-only
resolve selected managed tools. Repository lint remains mandatory and nonzero
when acquisition, checksum, version or lint fails.

Tests use synthetic ZIP/tar artifacts and mocked networking/probes; no unit test
requires GitHub or installs a tool. Coverage includes cached/missing dependencies,
legacy cache promotion, PATH reuse, downloads, 403/404, transient 503/timeout/reset/
proxy/incomplete read, TLS failure/downgrade, checksum/version mismatch, atomic
publication failure, concurrent resolution, offline hit/miss, mirror success and
fallback, unsupported platform, link member rejection, Inno delegation and early
preflight/receipt-reuse contracts. The existing strict Windows stage-sequence
expectation was updated for the intentional early stage; no safeguards removed.
A mistyped nonexistent test module in an intermediate command was corrected to
`test_ci_report`; it was not an application failure.

Final affected validation: nine complete tooling/dependency/workflow/installer
modules, **211 discovered, 208 executed successfully, 3 PowerShell-only skips**,
zero failures (`managed-tools-complete-targeted.log` and JSON in build/). The final
19 resolver/cache tests passed separately after legacy-cache coverage was added;
scopes overlap. The final CLI error guard's six acquisition tests also passed.
Ruff, whitespace, workflow contracts and internal Markdown links passed.

Real Linux acceptance: `scripts/testing/ci.py prerequisites` located a previously
verified archive, used the managed cache without downloading and verified the
real actionlint executable and exact version. `scripts/testing/ci.py lint` then
passed actual actionlint workflow lint and documentation links. No native Windows,
PowerShell/installer execution, corporate 403 recovery, packaging build, system
tool installation, workflow dispatch or release is claimed. Windows acquisition
and compiler behavior remain pending on the affected host/network.

Configuration, audit matrix and exact Windows/Linux commands live in
[Build: centralized prerequisites](../BUILD.md#centralized-prerequisites-and-restricted-networks).
Use public prerequisites check/setup before another Windows package build;
configure an organization-approved mirror/local artifact or proxy/trust through
approved channels when upstream is forbidden. Never bypass security controls.

Final read-only installer inspection coverage additionally passed: 37 prerequisite
checks and a dedicated no-network/no-cache-write installer-bootstrap case. This
last tooling-only refinement is covered directly; the application/browser code
is unchanged. Resolver/cache coverage now contains 20 cases (19 passed together,
then the additional inspection case passed); scopes overlap earlier counts.

Complete local **REGRESSION passed in 7:52, exit 0**, summary-output mode enabled:
backend **1495 discovered, 1489 actually passed, 6 Windows-only skipped**;
critical browser **90/90**, tagged browser **33/33**. Thus **1612 actual passed,
zero failures, 6 skips**; the profile displays 1618 passed because its backend
summary includes skipped discoveries. All whitespace, documentation, workflow,
ownership, Ruff, ESLint, TypeScript and frontend unit checks passed. Evidence:
`build/test-logs/managed-tools-regression.log` and matching JSON under
`build/test-artifacts/` (local ignored artifacts). The existing nonfatal unclosed
file ResourceWarning in `test_validation_entrypoint.py:60` remains unrelated.
This is REGRESSION, not FULL; the excluded release/packaging tests were covered
by the separate affected tooling/installer modules above. Unchanged frontend
assets were reused; no application packaging build was repeated.

Final Windows verification (from repository root, approved network/proxy/mirror
configuration in place):

```powershell
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --test test_local_build --test test_windows_ports --test test_prerequisites --jobs 1 --log build/windows-managed-tools.log --report build/windows-managed-tools.json
.\scripts\build.ps1 -Mode prerequisites -Platform windows -Target desktop -CheckOnly -NonInteractive
.\scripts\build.ps1 -Mode prerequisites -Platform windows -Target desktop -NonInteractive
```

Check-only may report missing caches; setup performs verified acquisition. Do not
start another package build if setup fails. For installer-specific acquisition,
select `-Target installer`. Confirm cache reuse by repeating prerequisites setup;
retain sanitized status/error output. Then, if the required tools are verified,
run the intended native build. No native corporate-download success, PowerShell
5.1 execution, Windows cache-lock acceptance or Inno compiler acceptance is
claimed here. No main/version/CI-trigger/release changes were made.

## Prerequisite JSON stdout contract (Windows Node 25)

Baseline `b351871`, branch `work`. Native Desktop packaging/smoke passed per the
provided results; Server shared validation failed before service packaging when
`json.loads(done.stdout)` encountered the Node 25.8.0 non-LTS note. Confirmed
producer: `prerequisites.inspect_tool()` printed the note to stdout while
`doctor.collect()` was constructing the JSON report. The supported Node version
is valid and must remain a visible warning, not become an error or be suppressed.

Audit found related stream risks: optional tool diagnostics, interpreter reexec
notes, setup/repair/dependency progress, CI child output, the missing-Python
report path and bootstrap diagnostics. Internal packaging quick JSON is emitted
without those probes; shared dry-run uses a JSON plan. No versions, prerequisite
checks, release rules or application/runtime behavior changed.

Fix:

- Node notes and optional probe diagnostics always use stderr. Warning report
  items remain intact. Interpreter handoff notes use stderr; JSON/non-interactive
  handoff closes stdin. JSON/dry-run configuration does not prompt.
- Prerequisite operation work and final report emission are separated: JSON mode
  redirects Python progress to stderr and emits one final stdout document for
  check/setup/expected failures. Missing Python still produces exit 3; expected
  setup errors include structured error information with matching exit codes.
- JSON-mode Runner labels/tails and CI child stdout use stderr; stdin is closed.
  Normal human-mode logging behavior stays separate. This prevents dependency
  setup subprocesses from writing ahead of the report.
- PowerShell 5.1-compatible bootstrap diagnostics use stderr in machine-readable
  mode. Pre-engine failures produce an error document. JSON output is buffered
  only as the success stream, without filtering warning lines or rewriting the
  producer's JSON. Legitimate native stderr does not force a false failure;
  the child exit code is preserved, guarded against stale LASTEXITCODE after a
  launch failure, and ErrorActionPreference is restored. A missing engine report
  is an explicit failure. Non-interactive mode never asks installation questions.
- The original failing test now attaches subprocess exit/stdout/stderr to the
  original JSONDecodeError before reraising; the parser/assertions are preserved.

Coverage: direct Node 25.8.0 + diagnostics JSON parsing; actual Python-subprocess
CLI parsing with a mocked supported Node version and a real warning on stderr;
setup success/progress/failure reports; missing Python exit 3; reexec streams;
CI Runner child streams/closed stdin; bootstrap structural guards. No tool is
installed by these tests and no warning is suppressed. An initial mock with an
empty missing-Python collection exposed an exit-code regression in the report
refactor; the authoritative missing-Python row now preserves exit 3. A test
closure's late binding was corrected to satisfy Ruff.

Affected validation: five complete prerequisite/build/diagnostic/local-tool/
Windows-port modules, **207 discovered, 204 executed successfully, 3 PowerShell
skips**, zero failures (`prerequisites-json-final-targeted.log` / JSON under build/).
Final closed-stdin/handoff checks reran both affected prerequisite/build modules:
**91 discovered, 90 passed, 1 PowerShell skip**, zero failures. Scopes overlap.
Ruff, whitespace, workflow contracts and 62-document internal links passed.

Backend REGRESSION was selected as the relevant integration scope. Browser,
frontend build, packaging and FULL are intentionally omitted: this change only
routes build/report streams and does not change application UI/runtime code.
Windows PowerShell 5.1/7 execution and the real Node 25 Server build remain pending
on Windows; structural PowerShell checks do not count as native acceptance.

Native Windows follow-up (run PowerShell 5.1 and PowerShell 7 where available):

```powershell
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --test test_prerequisites --test test_unified_build --jobs 1 --log build/windows-prerequisites-json.log --report build/windows-prerequisites-json.json
New-Item -ItemType Directory -Force build | Out-Null
$report = .\scripts\build.ps1 -Mode prerequisites -Platform windows -Target server -CheckOnly -NonInteractive -Json 2> build/prerequisites-json.stderr.log | ConvertFrom-Json
$checkExit = $LASTEXITCODE
if ($report.exit_code -ne $checkExit) { throw 'Report/process exit codes disagree.' }
$report.items | Where-Object status -eq 'Warning'
Get-Content build/prerequisites-json.stderr.log
if ($checkExit -ne 0) { throw 'Resolve reported prerequisites before building.' }
.\scripts\build.ps1 -Mode build -Platform windows -Target server -NonInteractive
```

Use stdout directly; do not merge stderr into the JSON input. Inspect warning
items and the separate stderr log. No CI triggers, main/version changes or manual
workflow dispatches are part of this task.

Final relevant **backend-only REGRESSION passed (1:59, exit 0)**: 1495 discovered,
**1489 actually passed, zero failed, 6 Windows-only skipped**. The runner displays
1495 passed because its backend summary includes skipped discoveries. Evidence:
`build/test-logs/prerequisites-json-regression.log` and matching JSON under
`build/test-artifacts/` (local generated artifacts). The existing nonfatal unclosed
file ResourceWarning at `test_validation_entrypoint.py:60` remains unrelated.
The build static checks above passed separately; no browser, frontend build,
packaging, FULL or GitHub Actions run is claimed. Changes are limited to build
stream handling, regression coverage and documentation.

## Windows SCM acceptance isolation, outputs and exit status

Baseline `e1c1329`, branch `work`. Provided native evidence: Desktop build/smoke
passed on b351871; Service package built/verified on e1c1329, and SCM install,
start, stop, backup, restore and uninstall ran successfully before cleanup failed.
These are supplied historical results, not new native execution by this task.

Confirmed cleanup cause: private backup directories intentionally have a
SYSTEM-only DACL/owner. An elevated administrator does not automatically have
list/delete access. The old acceptance finally used recursive Remove-Item,
which crossed those protected entries, and recorded native success before its
cleanup completed. Production purge preserves backups and is not a suitable
SYSTEM-context test cleanup mechanism. No new SYSTEM task/endpoint was added.

Implementation:

- Test-only `testing/windows-scm-test-helpers.ps1` creates a unique private Temp/
  RUNNER_TEMP root with creator/SYSTEM access and an in-memory/marker-bound token,
  canonical parent/path and caller SID. All mutable copies, data, sources/logs,
  backups, restore/config targets and upgrade copies are children of this root.
- Cleanup is allowed only after verifying removal of the service whose SCM binary
  path belongs to the isolated bundle. Controller/CIM handles are disposed; an
  unexpected service or incomplete removal retains the workspace, never changes
  an unrelated registration or deletes live application files.
- Root/path/marker/caller/reparse checks precede privileged operations. The tree
  is inspected before deletion. Only when access fails, non-recursive takeown
  recovers that exact test entry and icacls grants FullControl only to the creator
  SID (/L, no /T or /R). No Everyone/Users/Authenticated Users grant, no production
  ACL change. Files/directories are deleted without privileged recursive traversal;
  directory deletion is explicitly non-recursive. Cleanup errors remain nonzero;
  primary errors are retained as inner exceptions and reported with cleanup errors.
- Both directory and ZIP inputs are copied/extracted into the private workspace.
  Required bundle files and the verified report/file hashes are checked before
  service operations. ZIP validation rejects traversal, drive/ADS/reserved names,
  duplicate names, links/reparse metadata, excessive entries and size. Only then
  does extraction occur, without overwriting. ZIP origin-zone metadata is carried
  to extracted files; code is not implicitly unblocked. Use trusted verified
  packages: self-consistent unsigned metadata alone does not establish provenance.
- Runtime version is checked against the selected package identity, removing the
  unrelated previous local build-metadata dependency. Directory input receives
  its updated report only after cleanup; ZIP input remains unchanged and receives
  a .scm-verification.json sidecar. No failed cleanup is marked passed.

Output collision cause: cross-platform local default folders used only product
version while manifests correctly refused a different source SHA. Defaults now
use dist/<version>-<first12SHA>; remote collection uses the same rule. Product and
artifact versions/names are unchanged. Full-SHA manifest checks still guard even
prefix collisions. Explicit output is honored exactly; existing folders and
manifests are not removed. Legacy portable Desktop already has local identity/
run-specific output and retains its layout. Tests instantiate builders for two
sources, preserve an earlier sentinel, honor explicit output and reject a stale
manifest without modifying it.

Exit handling: the bootstrap's script-scoped LASTEXITCODE sentinel could shadow
the global native value. Sentinel/read operations now consistently address the
global variable; exceptions after a successful child force nonzero status.
Acceptance also starts/fails with nonzero status and explicitly exits zero only
after report writing and cleanup. Exact external -Help exit 1 was not reproduced
without native PowerShell; it remains a Windows follow-up, not assumed harmless.
Native tests exercise help, dry-run success, invalid arguments and stale caller
status on each installed PowerShell 5.1/7 host.

Validation: eight complete acceptance/deployment/prerequisite/build/port/contract/
packaging/layout modules, **173 discovered, 166 passed, zero failed, 7 native/
PowerShell skips** (`scm-build-ready.log` and matching JSON in build/). Focused
helper-contract reruns passed after final compatibility/origin-metadata guards:
15 discovered, 10 executed successfully, 5 Windows-only skips; scopes overlap.
The strict old exit-code source assertion was updated to the intentional global
form rather than removed. Native tests cover ordinary workspace removal, outside
paths, valid directory/ZIP, traversal, junction targets, SYSTEM-owner/DACL cleanup
(elevated) and bootstrap outcomes. These were not executable on this Linux host.
The System ACL test touches only a uniquely created marked test subtree.

Relevant **backend-only REGRESSION passed in 2:00, exit 0**: 1503 discovered,
**1492 actually passed, zero failed, 11 Windows-only skips**. The runner displays
1503 passed because its backend summary includes skipped discoveries. Evidence:
`build/test-logs/scm-build-regression.log` and matching JSON under build/test-artifacts/.
The final test-helper-only refinements were covered by the focused contracts;
no application runtime/frontend code changed. Ruff, workflow contracts, whitespace
and 62-document links passed. The pre-existing unclosed-file ResourceWarning at
`test_validation_entrypoint.py:60` remains unrelated. Browser/frontend builds,
FULL, packaging and live SCM/PowerShell execution were intentionally not repeated.

Native commands (replace example artifact paths with the build's actual output):

```powershell
# Standard build shell; no service installed by ordinary packaging.
.\scripts\build.ps1 -Mode build -Platform windows -Target server -NonInteractive
# Elevated shell: parse/test first, then reuse the verified service ZIP if available.
powershell -NoProfile -File .\scripts\check-powershell.ps1
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --test test_windows_acceptance_split --test test_local_deployments --test test_prerequisites --test test_unified_build --jobs 1 --log build/windows-scm-build.log --report build/windows-scm-build.json
.\scripts\test-server-service.ps1 -Bundle 'C:\Builds\verified-service-package.zip'
Get-Service SAPLens -ErrorAction SilentlyContinue
# Confirm bootstrap status in both Windows PowerShell and PowerShell 7 where installed.
powershell -NoProfile -File .\scripts\build.ps1 -Help
$LASTEXITCODE
.\scripts\build.ps1 -Mode quick -DryRun -NonInteractive
$LASTEXITCODE
# Per-user Desktop installer verification; no existing registered installation allowed.
.\scripts\build.ps1 -Mode build -Platform windows -Target installer -NonInteractive
.\scripts\test-desktop-installer.ps1 -Installer 'C:\Builds\SAP-Lens-Setup.exe' -Report 'C:\Builds\installer-acceptance.json'
```

Remaining release gates: actual Windows parser/helper/privileged cleanup and SCM
acceptance, correct native help/caller status, and installer lifecycle verification.
No native success or production release readiness is claimed from Linux tests.
Reboot/recovery/UNC acceptance remains separately pending. No main/version/CI
trigger changes, tags/releases or workflow dispatches were made.

## Windows deployment validation contracts — 2026-11-11

Baseline: `0eff788ab5521a5860e05370a111ad1e19b8bd6f`, synchronized with
origin/work before changes. This entry belongs to the subsequent deployment-contract fix commit.

Root causes and corrections:

- Explicit output was correctly canonicalized by `Path.resolve()`, but the test
  compared path spellings. Windows may expose a Temp directory through an 8.3
  alias. Assert filesystem identity with `samefile()` plus resolved-path equality,
  retaining the real mismatched-manifest rejection and byte-preservation check.
  Add native GetShortPathNameW coverage (capability skip if 8.3 aliases are disabled).
  Reject junction/reparse output paths and children before resolution, as well as
  symlinks; permission errors fail closed. Test reparse attributes and actual
  linked-output rejection without touching the target directory.
- The newly tracked SCM helper was missing from the script inventory. Document
  `testing/windows-scm-test-helpers.ps1` in docs/BUILD.md. The unchanged inventory
  test audits every tracked script; no other omissions remain.
- The layout test required obsolete version-only source text. Replace that
  requirement with the shared `deployment_output_name` contract used by local
  production and remote retrieval, preserving `dist/<version>-<commit12>/`.
  All four deployment targets share it; release verification still requires an
  explicit directory and validates the full source SHA, manifest and artifacts.
  Explicit output overrides and overwrite protection remain covered.

The SCM ZIP support, protected cleanup helpers, service operations, application
runtime, product version and workflow triggers were **not changed**.

Validation evidence:

- Before edits: explicit-output test passed on Linux; script inventory and layout
  tests each reproduced their reported failure. Each original test passed alone
  after correction.
- Deployment backend feature: 376 discovered, **354 passed, 0 failed, 22 skipped**
  in 6.3 seconds. Skips require Windows/PowerShell, including native 8.3 aliases.
  Evidence: `build/test-logs/deployment-fixes-suite.log` and corresponding JSON.
- Ruff (backend/scripts), workflow contracts, test ownership mapping, whitespace,
  and internal links across 62 Markdown documents passed.
- Backend-only REGRESSION: 1503 discovered, **1492 passed, 0 failed, 11 skipped**,
  exit 0 in 1:55. Evidence: `build/test-logs/deployment-fixes-regression.log` and
  matching JSON. The runner includes skipped discoveries in its displayed passed
  count; actual pass counts here exclude them. The existing ResourceWarning at
  `test_validation_entrypoint.py:60` remains unrelated.

Native Windows/PowerShell execution, packaging, SCM acceptance and browser/FULL
regression were not run on this Linux host. No artifacts were built or published.
Next Windows verification (ordinary shell, then elevated SCM acceptance):

```powershell
.\.venv\Scripts\python.exe scripts/run-tests.py targeted deployment --backend --jobs 1 --log build/windows-deployment-contracts.log --report build/windows-deployment-contracts.json
.\scripts\build.ps1 -Mode build -Platform windows -Target server -NonInteractive
# Elevated shell; use the actual verified service ZIP produced by the build:
.\scripts\test-server-service.ps1 -Bundle 'C:\Builds\verified-service-package.zip'
Get-Service SAPLens -ErrorAction SilentlyContinue
```

The SCM acceptance must not run against an existing SAPLens service; its existing
ownership and prerequisite protections remain in force. Native build/acceptance
success is not claimed by these Linux results.


## Desktop HTTP readiness and Windows build visibility — 2026-11-11

Baseline: `8e789b111793278e6c3a3ad7ca93e6eed06ff45f`, clean and synchronized
with origin/work. No Windows runtime or PowerShell is available on this Linux host.

### Failure analysis and correction

Python 3.12's `urllib.request.build_opener()` eagerly constructs an HTTPSHandler,
which calls `ssl._create_default_https_context()` and loads the system trust
store. Desktop readiness is exclusively HTTP on the already-owned loopback socket,
but this unused TLS initialization occurred before the first readiness probe and
outside its HTTP timeout. The GUI fixture independently closes startup after three
seconds unless navigation has occurred.

Evidence gathered before editing:

- All five reported tests passed individually on ordinary Linux execution.
- A controlled certificate-store model advancing the clock by two seconds made
  readiness return `READINESS_TIMEOUT`, with **one TLS initialization and zero HTTP
  requests**, rather than checking the mocked wrong identity.
- Injecting 3.2 seconds into certificate-store construction reproduced the exact
  `test_gui_failure_cleans_up_server` missing-navigation error (`call_args is None`).
  This was a reproduction only; no delay was added to production or committed tests.

Failure mechanisms:

| Reported failure | Mechanism |
| --- | --- |
| GUI failure: missing navigation | Fixture closes before readiness/navigation; the requested GUI-failure scenario was never reached. Reproduced with delayed TLS initialization. |
| Occupied port: return 1 | Same startup/fixture timing hazard can make session verification run before navigation. The port-ownership assertion is retained. |
| Malformed/wrong identity: READINESS_TIMEOUT | Unused TLS construction consumes the deadline before the mocked HTTP request. Reproduced deterministically. |
| Stalled CSV: return 1 | Same early-close/session timing hazard prevents exercising the intended CSV-loading scenario. CSV behavior is unchanged. |
| Unexpected backend exit: no destroy | The intended post-navigation runtime-monitor scenario is not reached if fixture startup closes early. Runtime monitoring is unchanged. |

The common initialization defect and two original failure signatures were
reproduced locally; the other three share the exposed fixture path. Attribution
of every native Windows occurrence still needs the commands below; the supplied
failure summary alone does not establish native certificate-store timings.

`desktop.local_http_opener()` now installs only HTTP, HTTP error, unknown-scheme
and no-redirect handlers. It never initializes TLS or proxies and rejects file,
FTP and HTTPS. The test HTTP helper uses the same transport. Health identity,
allowed health states, response-size limits, worker checks, deadlines, redirects,
listener ownership, shutdown and production single-instance/storage protection
are unchanged. No test assertion or timeout was weakened or increased.

New regression coverage forbids TLS initialization while validating identity and
transient failures, exercises real startup with unusable proxy settings and TLS
setup, and checks rejection of unsupported schemes. Existing redirect, occupied
port, shutdown, stalled CSV and runtime-failure assertions pass unchanged.

Server packaging intentionally invokes `test_desktop.py`, `test_windows_package.py`
and `test_server.py` in `package-windows-deployment.ps1`, after shared deployment
validation. This is the existing common Windows lifecycle gate, not an accidental
selection from the deployment feature map. It remains mandatory for both targets.

### Build visibility

The shared runner emits named stage start/end markers and elapsed time, a heartbeat
every 15 seconds, and the log location. Only authored child progress markers are
relayed to the console; arbitrary child output stays in its detailed log. JSON-mode
runner diagnostics stay on stderr. Deployment manifests now include per-stage
name, status, seconds, exit code and log. Windows packaging names each required
test module. Existing failure classification, exit codes, receipts, output identity,
checksums and overwrite guards remain intact. SCM ZIP/protected cleanup code and
CI triggers were not changed.

### Validation

- Five original tests passed individually before and after the fix; three consecutive
  combined post-fix runs passed **5/5 each** (15 test executions total).
- New HTTP transport regressions: **3 passed**.
- Complete desktop module: **50 passed, 0 failed, 0 skipped**, 52.1 seconds.
- Direct build-tooling modules: **97 passed, 0 failed, 2 skipped**.
- Windows packaging/smoke/server/startup dependents: **62 passed, 0 failed,
  6 skipped**, 18.8 seconds.
- Deployment feature: **356 passed, 0 failed, 22 skipped**, 7.3 seconds.
- The test runner displays backend discoveries as passed, including skips; these
  actual pass counts subtract skipped tests. Logs and JSON records use prefixes
  `desktop-native-before`, `desktop-native-after`, `desktop-native-repeat`,
  `desktop-http`, and `desktop-build` in build/test-logs and build/test-artifacts.
- Ruff (backend/scripts), workflow contracts, ownership map and whitespace passed.
- Backend-only REGRESSION: **1495 passed, 0 failed, 11 skipped** (1506
  discoveries), exit 0 in 2:16. Evidence: `desktop-native-stability-regression.log`
  and matching JSON under build/test-logs and build/test-artifacts. The pre-existing
  `test_validation_entrypoint.py:60` unclosed-file ResourceWarning remains unrelated.
- Internal links across 62 Markdown documents passed.

Native Windows, PowerShell parser/binding, EXE/WebView2 startup, packaging and SCM
acceptance were not executed. Browser/FULL checks and CI were not invoked; no
frontend code changed, no dependencies were installed and no artifacts were built.

### Native follow-up (PowerShell 5.1 or 7)

```powershell
$py = '.\.venv\Scripts\python.exe'
$names = @(
  'test_desktop.DesktopTests.test_gui_failure_cleans_up_server',
  'test_desktop.DesktopTests.test_occupied_port_is_not_contacted_or_terminated',
  'test_desktop.DesktopTests.test_readiness_rejects_wrong_identity_and_malformed_content',
  'test_desktop.DesktopTests.test_stalled_initial_csv_does_not_prevent_window_or_exit',
  'test_desktop.DesktopTests.test_unexpected_backend_exit_reports_error_and_closes_owned_window'
)
foreach ($name in $names) {
  & $py scripts/run-tests.py targeted --test $name --jobs 1
  if ($LASTEXITCODE -ne 0) { throw "Focused test failed: $name" }
}
$selected = @('scripts/run-tests.py', 'targeted', '--jobs', '1')
foreach ($name in $names) { $selected += @('--test', $name) }
foreach ($iteration in 1..3) {
  & $py @selected --log "build/desktop-repeat-$iteration.log" --report "build/desktop-repeat-$iteration.json"
  if ($LASTEXITCODE -ne 0) { throw "Repeat failed: $iteration" }
}
& $py scripts/run-tests.py targeted --test test_desktop --test test_build_diagnostics --test test_windows_package --test test_server --jobs 1 --log build/desktop-affected.log --report build/desktop-affected.json
if ($LASTEXITCODE -ne 0) { throw 'Affected validation failed' }
powershell -NoProfile -File .\scripts\check-powershell.ps1
if ($LASTEXITCODE -ne 0) { throw 'PowerShell validation failed' }
.\scripts\build.ps1 -Mode build -Platform windows -Target server -NonInteractive
```

Use a fresh output directory if an explicit directory already belongs to another
commit. Preserve failed build logs/manifests; never overwrite existing release
artifacts. Native success is not claimed until these checks actually pass.

## Occupied-port Windows packaging isolation — 2026-11-11

Baseline `71e696241a8a0f2d6edb7a3a04c553561ec5c2b7`, clean and synchronized
with origin/work. Native Windows/PowerShell is unavailable on this Linux host.

**Confirmed defect:** DesktopTests mocks `desktop.is_windows()` to False to isolate
WebView2, the native single-instance boundary and GUI integration. The same mock
also selected POSIX SO_REUSEADDR in `reserve_listener()` on a real Windows kernel.
Winsock permits overlapping binding with this option: successful bind does not
establish exclusive ownership, and the later listen/startup may fail or behave
indeterminately. The preferred-port conflict test must exercise actual OS socket
semantics, independently of the mocked GUI platform. No leaked process or shared
mutex was needed to reproduce this policy error.

A regression model of Winsock's occupied-port binding failed before correction:
it reserved the already-owned preferred port 18743 rather than falling back to
49152. After correction it proves SO_EXCLUSIVEADDRUSE on both Windows attempts,
closure of the rejected candidate and retention of the owned fallback socket.
The actual failing native packaging run was not available for tracing here;
native confirmation remains required rather than inferred from this model.

**Fix:** socket policy now reads the actual `sys.platform`, independent of the GUI
helper. Unmocked production behavior is unchanged: Windows exclusive ownership,
POSIX reuse, loopback-only binding and OS-assigned fallback. No service is probed,
terminated or reused. The existing live-port test retains every assertion and now
includes safe startup stage/error-code diagnostics if run() returns nonzero.
Structured startup events include socket policy and numeric OS error codes;
failed reservation logs contain only policy, port and OS codes, not error values,
paths, CSV data or tokens. No deadlines, sleeps, retries, packaging contracts,
GUI cleanup, readiness identity checks, locks or CI triggers were changed.

**Packaging-equivalent execution:** used `backend/build/python-env/bin/python`
(the Linux counterpart of packaging's Scripts/python.exe), repository cwd and
exact flags `-W error::DeprecationWarning -m unittest discover -s backend/tests
-p test_desktop.py -v`. The inherited environment matched the deployment builder:
production/source/deployment overrides and pip/Python destination overrides removed;
PYTHONUTF8=1, PYTHONIOENCODING=utf-8, SAP_LENS_BUILD_SCOPE=targeted, DATA_CSV_PATH and
USER_CSV_PATH empty, SAP_LENS_CONFIG_DIR=backend/build/deployment-test-settings,
RUNNER_TEMP=backend/build/deployment-validation, SAP_LENS_AUDIT_PYTHON pointing to
the prepared audit interpreter, and prepared backend Python first on PATH. Both
local interpreters report Python 3.12.14, Uvicorn 0.54.0 and FastAPI 0.151.0.

**Validation:** regression model failed before and passed after; model plus live
occupied-port test passed 2/2. In the prepared packaging environment the original
test passed five consecutive runs (0.716–0.977s), then the entire desktop module
passed **51/51 twice** (36.953s and 38.927s), with zero failures/skips. Logs:
`build/test-logs/desktop-packaging-single-{1..5}.log`,
`desktop-packaging-module-{1..2}.log`; commands, durations and exit codes in
`build/test-artifacts/desktop-packaging-repeats.json`. The modeled red/green tests
have separate `desktop-winsock-before/after` logs and JSON results.
Related desktop/package/server/startup tests: **62 passed, 0 failed, 6 native
Windows-only skips** (68 discoveries). Complete deployment feature: **356 passed,
0 failed, 22 platform skips** (378 discoveries). Evidence uses
`desktop-winsock-dependents` and `desktop-winsock-deployment` log/JSON prefixes.
Ruff, documentation links (62 files), workflow contracts and whitespace passed.
The broad release regression and artifact builds were intentionally not repeated.

**Windows follow-up** — from the repository root after synchronizing work, reuse
packaging's prepared Python; do not substitute .venv:

```powershell
$py = '.\backend\build\python-env\Scripts\python.exe'
foreach ($iteration in 1..5) {
    & $py -W error::DeprecationWarning -m unittest discover -s backend/tests -p test_desktop.py -k test_occupied_port_is_not_contacted_or_terminated -v
    if ($LASTEXITCODE -ne 0) { throw "Occupied-port repeat $iteration failed" }
}
foreach ($iteration in 1..2) {
    & $py -W error::DeprecationWarning -m unittest discover -s backend/tests -p test_desktop.py -v
    if ($LASTEXITCODE -ne 0) { throw "Desktop module repeat $iteration failed" }
}
.\scripts\build.ps1 -Mode build -Platform windows -Target server -NonInteractive
```

The final public build applies the builder's full inherited environment and logs
any remaining failure through the new safe assertion diagnostics. No artifact
rebuild, complete release regression, GitHub Actions or native success is claimed
by the Linux checks above.

## Release artifact collection and SCM replacement/cleanup — 2026-11-11

Baseline: `c24df34897d14dcb1fc30533277079a52a0953a3`, clean and synchronized
with origin/work. SCM corrections are in `02f3a28`; the following artifact
consolidation commit contains the remaining implementation and this evidence.

### Findings and safety boundaries

The real deployment ZIP finisher reproduced a concrete replacement inventory
mismatch: it adds **package-manifest.json after the server verifier seals
verification-report.json**. The old acceptance test recursively copied this
transport-only file (and any runtime-generated files) from the installed bundle
into a replacement, while Assert-NewBundle correctly permits only the verifier's
file list plus verification-report.json. The new test constructs that real ZIP
and proves the extra entry is package-manifest.json. It does not fabricate a PE
verification pass or relax the production allowlist.

Acceptance now snapshots exactly the verified replacement file list, with hashes
and link/path checks, before installation. Transport metadata, generated XML and
runtime logs stay out. Upgrade diagnostics name unexpected/missing relative paths
and reparse entry types. Existing WinSW pinning, identity checks and approval of
only the verified payload remain intact.

**The original cleanup-denied object/handle is not known:** no retained native
workspace or detailed exception was supplied with this request, and Windows is
unavailable here. Confirmed code gaps were that service absence was treated as
sufficient for deletion, read-only directory attributes were not cleared by
Directory.Delete, and transient sharing locks had no bounded retry. Cleanup now
waits for processes with executable paths inside the owned workspace, clears
read-only attributes only on checked test entries, and retries only error codes
5/32/33 up to five attempts (1.5s backoff). Per-entry caller-SID ACL recovery,
private marker/token boundaries, reparse rejection, primary/cleanup error
separation and nonzero failure remain enforced. No recursive permission changes,
process killing, production-directory cleanup or old retained-workspace deletion
was added. A full successful native replacement/uninstall/cleanup remains a gate.

### Artifact layout and publication

Final public-build artifacts use root **dist/<version>-<commit12>/**. Canonical
archives retain their names; local portable builds preserve their existing
unofficial +local.<commit12> version identity. Portable ZIP roundtrip extraction
and PE inspection moved to temporary backend/build/portable-export-* storage.
IncludeService stages its unpacked payload in backend/build and puts its ZIP
beside the portable ZIP. No duplicate extracted application or nested ZIP is
shipped. backend/dist remains internal compiler input, not the sole final output.

A standard-library shared collector verifies copied bytes, creates sidecars,
rejects existing artifact/foreign identity collisions and linked paths, rolls back
only its own failed copies and atomically records release-manifest.json with
artifact name/platform/version/full source SHA/SHA-256. Local and trusted remote
deployment collection and guarded CI finalization share it. Canonical finishers
can register their adjacent service output into the same managed inventory.

Legacy Windows build-only CI now collects its verified EXE/sidecar into the
versioned directory after native smoke, before upload, through the shared Python
entrypoint's internal windows-collect adapter. The exact two-file GitHub artifact,
its name, retention, compression and provenance checks are preserved. Workflow
contracts reject skipped collection, pre-smoke collection, intermediate-path
uploads or extra upload files. Legacy publication also defaults to the versioned
root directory, retaining explicit output overrides. No public checksum assets
were duplicated. Workflow triggers/permissions and main-only automatic CI are
unchanged; no workflow, release, tag or artifact build was dispatched.

### Validation and remaining native checks

- Transport-manifest reproduction: **1 passed**, real synthetic ZIP finisher.
- Final deployment feature: **362 passed, 0 failed, 22 platform skips** (384
  discoveries), 9.1s; release-consolidation-final-deployment log/JSON.
- Windows/service/release contracts: **106 passed, 0 failed, 7 native skips**;
  release-scm-windows-final log/JSON. Native additions cover locked-file retention
  and retry, read-only cleanup, and manifest-only replacement copying.
- Final CI/local-build/workflow/legacy-release checks: **152 passed, 0 failed,
  3 skips** (155 discoveries), 4.3s; release-final-ci-contracts log/JSON.
- Artifact integrity/rollback/registration tests passed, including checksum
  corruption, different source identity, reparse paths and copy interruption.
- Backend-only REGRESSION checkpoint: **1497 passed, 0 failed, 13 skipped**
  (1510 discoveries), 2:25; release-scm-backend-regression log/JSON. The final
  build-only CI wiring was added afterwards and covered by the targeted checks
  above; the backend checkpoint was not needlessly repeated. The runner includes
  skipped discoveries in its displayed passed count; actual counts here exclude
  skips. The existing test_validation_entrypoint.py:60 ResourceWarning remains.
- Ruff, 62-document links, workflow policy/contracts, ownership map and whitespace
  passed. No frontend files changed, so frontend builds/browser/FULL were not run.
- PowerShell syntax/runtime and privileged SCM cannot execute on this Linux host.
  No Windows build or elevated acceptance success is claimed.

Native follow-up, reusing an existing verified service ZIP where possible:

```powershell
powershell -NoProfile -File .\scripts\check-powershell.ps1
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --test test_windows_acceptance_split --test test_local_build --test test_artifact_layout --jobs 1 --log build/scm-artifact-native.log --report build/scm-artifact-native.json
# Elevated, with no pre-existing SAPLens service:
.\scripts\test-server-service.ps1 -Bundle 'C:\Builds\verified-service-package.zip'
Get-Service SAPLens -ErrorAction SilentlyContinue
# Only if fresh packages are required; ordinary packaging installs no service:
.\scripts\build.ps1 -Mode build -Platform windows -Target all -NonInteractive
```

Inspect any retained workspace, error's relative path/type/code, process state and
ACLs before manual recovery. Do not recursively grant rights or delete production
paths. See docs/BUILD.md, deployment/RELEASES.md and deployment/WINDOWS_SERVICE.md
for the updated layout, checksum verification and administrator requirements.


## Windows Desktop installer acceptance isolation (2026-11-11)

The existing acceptance guard correctly refused the production uninstall AppId.
It therefore could not exercise installation on a developer machine with SAP Lens
already registered. Production identity and upgrade behavior remain unchanged.
Acceptance now compiles a separate GUID-bound wrapper from the exact approved
payload, with producer provenance binding the production Setup, payload, recipe
and build identity. Its private directory and ownership marker are checked by
both the runner and installer/uninstaller. It creates no shared shortcuts.
The production Setup is verified, never installed by this acceptance path.

Read-only snapshots compare production uninstall registration, installation files
and application data before/after every lifecycle stage. Test-only registration
and uninstall paths must match the private workspace. Install, reinstall, EXE
hash/lifecycle, backup/data preservation and uninstall assertions remain. The
production Desktop mutex is retained: exit a running application (including tray)
before testing, but leave its installation registered. Failures identify stages;
cleanup errors preserve private diagnostics. CI uploads only setup/reinstall logs,
never plans, snapshots, settings or backups.

Validation: focused installer/compiler/provenance/workflow tests: 75 passed,
2 Windows-only skips. Final deployment checkpoint after provenance binding:
362 passed, 22 platform skips. Backend REGRESSION checkpoint: 1,506 passed,
15 skipped, zero failures (1,521 discovered); final build-only provenance and
diagnostic-selector changes were subsequently covered by focused tests. Ruff,
documentation, workflow contracts and whitespace checks passed. No frontend code
changed; browser, frontend build and FULL were intentionally not run.

Native Windows PowerShell/Inno compilation and actual install/reinstall/uninstall
are NOT verified on this Linux host. Exact native commands and private-workspace
recovery instructions are in [Windows Desktop](../deployment/WINDOWS_DESKTOP.md#verify-without-repeating-the-entire-windows-build).
Run CompileCheck and the focused native tests first, then isolated acceptance
against a current producer-verified Setup. Production-AppId upgrade acceptance
remains a separate clean-machine/manual gate. No release or workflow was dispatched.
