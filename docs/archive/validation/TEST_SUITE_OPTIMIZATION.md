# Test suite cleanup and optimization

Dated record (29 October 2026). Environment: Linux sandbox, 4 vCPU, Python 3.12, Node 22,
headless Chromium; absolute times are specific to that machine. Baseline is commit `03088fb`.
Entry point and conventions: [Testing](../../development/TESTING.md).

## Audit findings

| Finding | Evidence | Action |
| --- | --- | --- |
| Time is evenly spread; no single slow spec | Browser tests average about 2 s (largest spec 56 s); backend 716 tests sum 93.7 s, top module 12.8 s | None needed |
| Theme x width visual families dominate browser time | 46 families, 450 s of 946 s (48%) re-seed and re-navigate for 4 widths x 2 themes | Kept: they implement the responsive and theme policy; recommend consolidating only after per-assertion review (not done, risk of losing coverage) |
| Duplicated browser helpers | `headers` copied in 36 files, main-navigation helper in 11, seed boilerplate in about 30 | Moved to `frontend/tests/support.ts` (36 + 11 migrated, `seedSources` for new and two migrated specs) |
| Fixed waits | One 7 s sleep (SoD export notice) plus four short waits in recent tests | Replaced with Playwright's clock and reduced motion; no `waitForTimeout` remains. The spec went from 16.8 s to 7.4 s |
| Backend sleeps | 8 uses, all bounded polling loops or a 20 ms step | Kept (documented as intentional) |
| Duplicate tests | No identical titles and no identical CSV fixtures across 473 browser tests | Confirmed redundant tests removed: 0 |
| Specs named after iterations | `refinement-*`, `stabilization`, `ux` | Not renamed (churn); `scripts/test-map.json` assigns each file to one feature, naming convention documented |
| No selectable subsets | Only file-name arguments | Added smoke, targeted, regression and release profiles |
| Browser server fixed to port 18745 | Prevented parallel processes | Port and storage are per process (`SAP_LENS_BROWSER_TEST_PORT`) |
| Stale documentation claim | TESTING.md said no fixed waits existed | Rewritten |

Missing-coverage check: critical areas named in the request (role assignments and validity,
wildcard matching, T-code lookup, comparison, SoD, account review decisions, access package,
CSV, source lifecycle, authentication and isolation, dates) all have backend and/or browser
tests; no gap was found that justified new application tests.

## Before and after

| Metric | Before | After |
| --- | --- | --- |
| Backend tests | 716 (3 skipped) | 720 (3 skipped); +4 profile-integrity tests |
| Browser tests | 473 in 49 specs | 473 in 49 specs; none added or removed |
| Skipped tests | 3 backend (PowerShell x2, PyInstaller) | Same 3, now printed with reasons by every run |
| Smoke duration | no smoke profile | 36 to 47 s (12 browser + 19 backend tests; 47.2 s first run, 35.9 s later) |
| Targeted duration | file selection by hand | e.g. access-package 19.8 s (4 browser + 14 backend), account-review backend 4.4 s, SoD backend 39.5 s |
| Backend regression | 88.5 s serial | 34.3 to 35.0 s with 3 processes (about 2.5x) |
| Browser regression | about 16.1 min serial (3 batches 6.1 + 5.4 + 4.6) | 3 processes 12.7 min (one run); 2 processes 16.0 min (shards 961 s and 731 s); default stays 1 process because the gain was uneven and CPU-bound |
| Full `regression` profile | not available | 1016 s with 2 browser processes, including build, docs, workflow, catalog, whitespace and `pip check`; passed after fixing two docs-link failures caused by editing documentation during the run (backend rerun: 720 passed) |
| Confirmed redundant tests removed | n/a | 0 |
| CI execution time (hosted `ubuntu-latest`, single samples) | Fast Validation run 72 (`b590930`): backend step 71 s, job 99 s, run 103 s; Full Validation 9 to 14 min (runs 2 to 4, before this change) | Fast Validation run 74 (`cb26cfb`): backend step 48 s (-23 s, about 32%), job 81 s, run 85 s, success. Full Validation (PRs to `main`) not yet run with the new commands |

Parallel scaling detail (SoD browser specs, 80 tests): 1 process 195.6 s, 2 processes 138.3 s,
3 processes 131.2 s. Load average reached 10 on 4 vCPUs, so Chromium saturates the host;
`--jobs N` for the browser is opt-in for hosts with spare cores. Splitting the browser job
across CI runners was evaluated and not adopted: it would duplicate install, build and audit
per shard, rename the required job and add runner minutes for an uncertain gain.

## Validation

- Backend: 720 tests, 0 failed, 3 skipped (3 processes, deprecations as errors).
- Browser: 473 passed, 0 failed (2 processes, run on the committed test code); earlier 3-process
  run exposed one timing flake in a new test, fixed by disabling transitions.
- Smoke, targeted (access-package, SoD backend, account-review backend) and `check` verified.
- Static: documentation links, workflow contracts, icon catalog, `git diff --check`, `pip check` passed.
- Not run here: `actionlint`, PowerShell checks, `pip-audit`, `npm audit` (release profile reports
  them as unavailable or runs them when installed); Docker, Windows and systemd acceptance remain manual.
