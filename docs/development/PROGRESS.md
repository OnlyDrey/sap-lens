# Development progress

Resume guide for a new session: read [AGENTS.md](../../AGENTS.md), this file, `git status` and `git log --oneline -15`; the repository state is authoritative, correct this file where it differs.
CI policy: GitHub Actions runs only on push to `main` after an explicitly approved merge; all validation is local; `work` pushes never trigger it.

**Last update:** 2026-11-05 (end of Phase D)

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
| E | Parallel browser test stabilization | Pending | |
| F | Final validation: full backend, browser, benchmarks, report | Pending | |

## Local validation (latest)

* Backend full run before the retention work: 1430 tests (3 failures were the workflow tests edited mid-run; re-run OK). Targeted suites for every phase pass.
* Phase D: backend test_data_revision (15), account_review, application, server, workflows pass; unit tests 14; browser revision-consistency (3), dashboard-user-transactions, account-review-refinement, csv-lifecycle (41 total) pass; tsc and ruff clean. ESLint reports one pre-existing error (irregular whitespace in `tests/remediation-export.spec.ts`), unrelated.
* Browser: targeted specs per phase pass; full browser suite not yet run (final phase).

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
| Refresh, only the directory changed | 6.6 s | 7.1 s (full path, as intended; within noise) |
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
