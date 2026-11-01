# Test execution performance (R8)

Dated record (31 October 2026, commit `39c9c7e`). Environment: Linux sandbox, 4 vCPU, Python 3.12, headless
Chromium. Absolute times are specific to this machine. Entry point and conventions: [Testing](TESTING.md). The
earlier cleanup is in the [optimization record](../archive/validation/TEST_SUITE_OPTIMIZATION.md).

## Result in one paragraph

The full regression is long because the browser suite grew from 473 to 716 tests (2.4 s median each), not because of
waste. No fixed sleeps, repeated application start-ups or redundant imports were found. The two cheap wins are
using the default backend parallelism (65 s instead of 170 s) and the lightweight per-phase Fast Validation
(about 1.5 to 3 minutes) instead of repeated full runs. Process-level browser parallelism helps by at most about
1.5x on 4 vCPUs because Chromium saturates the host.

## 1. Duration per suite (full run, `--jobs 1`)

`--jobs 1` disables all parallelism, including the backend; it was used for the stable evidence run.

| Step | Tests | Duration | Notes |
| --- | --- | --- | --- |
| Backend, 1 process | 849 (3 skipped) | 170 s | `unittest discover` |
| Backend, 3 processes (default `auto`) | 849 (3 skipped) | 65 s | measured separately, 2.6x faster |
| Browser, 1 process | 716 in 81 specs | 34.5 min wall (33.9 min summed test time) | all passed |
| Frontend build | n/a | 24 s | `npm run build` |
| Type check | n/a | 20 s | `npm run check:types` |
| Docs, workflows, whitespace, `pip check`, catalog | n/a | under 1 s each | static |
| Smoke profile | 19 backend + 12 browser | 44 s | `run-tests.py smoke` |

The "about 45 minutes" estimate came from the serial backend, the serial browser suite, the build and the dependency audits.
The browser suite is about 90% of the total.

## 2. Slowest tests and repeated setup

Browser distribution: median 2.4 s, p90 4.3 s, p99 9.7 s; 265 tests under 2 s (400 s together); 7 tests over 10 s.

| Spec | Tests | Time | Why |
| --- | --- | --- | --- |
| `a11y-audit.spec.ts` | 2 | 100 s (one test 97 s) | One test walks 2 widths x about 18 views and sections, each with a scan and a Tab walk of up to 60 stops |
| `refinement-round2.spec.ts` | 37 | 91 s | many small tests |
| `refinement-completion.spec.ts` | 15 | 68 s | |
| `investigation-tools.spec.ts` | 23 | 65 s | |
| `design-system.spec.ts` | 20 | 62 s | |
| `investigation-ux.spec.ts` | 10 | 62 s | four 10 to 12 s light/dark x width screenshot tests |
| `status-consistency-r6.spec.ts` | 4 | 26 s | two 10 s focus-ring tests (light and dark) |

Backend: the 25 slowest tests sum to about 33 s of 170 s. The top ones start real processes or sweep every API
operation: headless shutdown and restart 4.9 s, security-surface sweep 3.5 s, repeated desktop launch 2.6 s. No module dominates.

Measured fixed costs per browser test (5 samples, one server):

| Operation | Average |
| --- | --- |
| `seedGovernance` (reset, three source selects, enable SoD) | 134 ms |
| Page boot (`goto` until navigation ready) | about 100 ms (first call 600 ms) |
| `openSod('Risk Matrix')` including `goto` | 315 ms |
| Reset and cleanup | 14 to 17 ms |

About 150 tests seed governance, so seeding is about 20 s of 2070 s (1%). With boot included, fixed per-test cost is
an estimated 8% of the browser time. Consolidating setup would not pay for the coverage and isolation it would cost.

## 3. Waits, start-ups, imports, timeouts

- Fixed waits: none. `waitForTimeout` does not occur in `frontend/tests`; the one timer-driven notice uses the Playwright clock.
  Backend sleeps are bounded polling loops (documented as intentional).
- Application start-up: one server per Playwright process, started once; tests reset configuration (14 ms) rather than restart.
  Backend lifecycle tests start real processes on purpose (they test restart persistence).
- Imports: each test seeds the minimal CSVs it needs; no identical fixture is imported repeatedly within a test.
- Timeouts: default 120 s, twelve spec-level overrides (30 to 300 s). Timeouts affect only the cost of a failure, not a passing run.
  The a11y test (97 s) keeps its 300 s override; lowering timeouts would save nothing on green runs and add flake risk.

## 4. Parallelism (measured)

Subset of six stateful specs (93 tests: SoD integration, bulk review, layout, employee directory, refinement completion, design system).
Every run used independent Playwright processes, each with its own port, server and configuration directory; one worker per process, no retries.

| Processes | Wall | Speed-up | Result |
| --- | --- | --- | --- |
| 1 | 308 s | 1.00x | 93 passed |
| 2 | 232 s | 1.33x | 93 passed |
| 3 | 206 s | 1.50x | 93 passed |
| 4 | 223 s | 1.38x | 93 passed |
| 3, `--fully-parallel` (test-level sharding, 31 tests each) | 208 s | 1.48x | 93 passed |

Findings:

- Load average reached 12 on 4 vCPUs. The gain is limited by CPU, not by shard balance: perfectly balanced test-level
  sharding was no faster than file-level sharding (208 s against 206 s), so it is not worth changing.
- Four processes are slower than three on 4 vCPUs. Use at most one browser process per spare core.
- Process isolation is safe: no state is shared (each process owns its server and configuration directory), and review history,
  the local SoD catalogue and unique-user fixtures live inside that directory. Parallel workers inside one server stay disallowed.
- No flake appeared in 4 parallel runs (372 test executions). That is evidence, not proof; keep `retries: 0`.
- Extrapolating 1.5x to the whole suite suggests about 23 minutes with `--jobs 3`. This is an estimate; the full suite was not run in parallel.

## 5. Prioritized optimization proposal

| Priority | Proposal | Expected effect | Risk |
| --- | --- | --- | --- |
| 1 | Run regressions with the default `auto` jobs; reserve `--jobs 1` for diagnosing a failure | Backend 170 s to 65 s | None |
| 2 | Per-phase Fast Validation (section 6) instead of browser suites at every phase | Avoids roughly 35 minutes per phase | None |
| 3 | Use `--jobs 3` for the final browser regression on hosts with 4 or more vCPUs | About 1.5x, measured on a subset | CPU load; failures under load must be re-run serially before they are classified |
| 4 | Tag the theme x width screenshot families (`@visual`); keep one representative combination in Fast Validation and the full matrix in Full Validation | Part of the roughly 450 s these families cost, without removing any combination from the final run | Needs a tag convention and a guard test |
| 5 | Split the `a11y-audit` mega-test into one test per width and view group | No total saving; clearer failures and shard balancing | Low; keep every assertion |
| 6 | Report shard seconds and the slowest ten tests at the end of each regression | Makes drift visible | None |

Not recommended: more workers inside one server, retries, lower timeouts, skipping or weakening visual and a11y tests,
sharing one server between processes, or sharing seeded state between tests (saves about 1% and costs isolation).

## 6. Fast Validation per phase

Defined from existing profiles; none of it needs a new tool. Typical total: 1.5 to 3 minutes.

| Step | Command | Time |
| --- | --- | --- |
| Static | `git diff --check`, `python scripts/check-docs.py` (docs changed), `python scripts/check-workflows.py` (workflows changed) | under 1 s |
| Types | `npm run check:types` in `frontend` | 20 s |
| Critical path | `python scripts/run-tests.py smoke` | 44 s |
| Changed feature | `python scripts/run-tests.py targeted <feature>` (needs `npm run build` when the UI changed, 24 s) | 20 to 90 s |
| Repository integrity | `python scripts/run-tests.py targeted repository` when files, docs or the test map changed | seconds |

The complete backend, the complete browser suite, visual QA, audits and packaging checks stay in the single Full
Validation after the final phase ([Testing](TESTING.md), repository guidance).
