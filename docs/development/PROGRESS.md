# Development progress

Resume guide for a new session: read [AGENTS.md](../../AGENTS.md), this file, `git status` and `git log --oneline -15`; the repository state is authoritative, correct this file where it differs.
CI policy: GitHub Actions runs only on push to `main` after an explicitly approved merge; all validation is local; `work` pushes never trigger it.

**Last update:** 2026-11-05 (end of Phase A)

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
| A | Backup retention (automatic 90 days, migration and manual protected) | Completed (pushed with this update) | see Git log |
| B | Employee Directory fingerprint and persistent cache | Pending | |
| C | Backend/API performance (`/api/access/users`, dashboard, memory) | Pending | |
| D | Frontend/API cache consistency (revision-aware) | Pending | |
| E | Parallel browser test stabilization | Pending | |
| F | Final validation: full backend, browser, benchmarks, report | Pending | |

## Local validation (latest)

* Backend full run before the retention work: 1430 tests (3 failures were the workflow tests edited mid-run; re-run OK). Targeted suites for every phase pass.
* Browser: targeted specs per phase pass; full browser suite not yet run (final phase).

## Measured performance (192 000 assignment rows, synthetic, this container)

| Scenario | Original | Step 2 |
| --- | --- | --- |
| Import | 20.2 s, peak 1017 MB | 16.4 s, peak 836 MB |
| Dynamic start, unchanged | 27.8 s, peak 1164 MB | 2.2 s warm, peak 525 MB |
| Static start | 9.8 s, peak 730 MB | 2.1 s, peak 525 MB |
| Refresh, one source changed | 24.6 s, peak 1251 MB | 15.3 s, peak 1125 MB |

## Known limitations and risks

* Resident memory ~525 MB, of which ~185 MB raw source records retained; changed-source refresh peaks above 1.1 GB (Phase C).
* First start after a change derives the model once (~4 s).
* Employee Directory is still parsed on every check (Phase B).
* Native Windows, WebView2 and systemd paths are not validated here.

## Decisions requiring user approval

None open.

## Next actions

Phase B: Employee Directory fingerprint and persistent cache, then Phase C.
