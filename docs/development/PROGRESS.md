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
