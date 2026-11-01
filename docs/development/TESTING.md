# Testing and validation

Prepare the environment from [Development](DEVELOPMENT.md) and run commands from the
repository root. Never report a check as passed unless it executed; a smoke or
targeted run is not a regression result.

## Profiles

One entry point, `scripts/run-tests.py` (standard library only; Windows and Linux),
selects tests from [`scripts/test-map.json`](../../scripts/test-map.json).

| Profile | Run it | Covers | Typical use |
| --- | --- | --- | --- |
| `smoke` | `python scripts/run-tests.py smoke` | Critical backend tests (startup, import, role/user lookup, access package, SoD, security boundary, privacy) and browser tests tagged `@smoke` (launch/import, navigation, dashboard, investigation, comparison, package, SoD, account review) | Seconds-to-a-minute check after any edit |
| `targeted` | `python scripts/run-tests.py targeted sod access-package` | Backend modules and browser specs owned by the named features | While changing a feature |
| `regression` | `python scripts/run-tests.py regression` | Every backend module and browser spec, TypeScript check and production build, documentation links, workflow contracts, icon catalog, whitespace, `pip check` | Before a push of a finished phase or PR |
| `release` | `python scripts/run-tests.py release` | Regression plus `npm audit`, `pip-audit`, PowerShell and workflow lint when those tools exist | Before a release decision |

Useful switches: `--backend` / `--browser` (one side), `--jobs N` (parallel processes;
`auto` by default, `1` disables), `--grep TEXT` (Playwright title filter), `--no-build`
(trust an existing `frontend/dist`), `--list-tests`, `--report FILE` (JSON summary).
`python scripts/run-tests.py list` shows the features; `check` validates the map.
The runner rebuilds the frontend for browser profiles only when sources are newer than
`frontend/dist`. Skipped tests and their reasons are printed with every run, and
`smoke`/`targeted` always state that they are partial.

`release` runs only what this machine can run and prints a NOTE for the rest. Docker
image build/run, Windows installer/service/WebView2, native Linux package and systemd
acceptance belong to the manual build workflows and the
[validation matrix](../deployment/README.md#validation-status); a Linux run never
proves them.

Underlying commands (still valid on their own): `python -m unittest discover -s backend/tests -v`,
`npm --prefix frontend run build`, `npm --prefix frontend run test:browser -- tests/<file>.spec.ts --grep <title>`,
`python scripts/check-docs.py`, `python scripts/check-workflows.py`,
`node scripts/sync-lucide-catalog.mjs --check`, `git diff --check`. A prepared host may
need `PLAYWRIGHT_EXECUTABLE_PATH` for Chromium; report that override.

## Ownership and adding tests

- Every backend module (`backend/tests/test_*.py`) and browser spec
  (`frontend/tests/*.spec.ts`) belongs to exactly one feature in `test-map.json`.
  `backend/tests/test_test_profiles.py` fails when a file is unmapped, mapped twice or
  missing, so no profile can silently drop tests. Add a new file to the map in the same
  change.
- Name new files after the behavior or feature they protect (`sod-periods.spec.ts`,
  `test_access_package.py`), not after an iteration or review round. Existing
  history-named specs keep their names; the map is the source of ownership.
- Keep specs independent: each resets state in `beforeEach` and uses unique synthetic
  data. Put shared setup in `frontend/tests/support.ts` (session headers, reset,
  navigation, `seedSources`, `openSettings`) or `sod-fixture.ts` before writing a new
  helper. Wait on assertions or `expect.poll`; use Playwright's `page.clock` for timers
  and `reducedMotion` for transitions, never fixed sleeps.
- Mark a browser test `@smoke` only for a critical, fast end-to-end path:
  `test('title', { tag: '@smoke' }, async ...)`. Smoke must stay near a minute; the
  guard test requires at least one tagged test in each critical feature.
- Use synthetic data only. Test the backend rule in a backend test; use Playwright for
  what the browser owns (rendering, keyboard, routing, client-side matching).

## Parallelism and isolation

Backend modules run in parallel processes (each test builds its own temporary storage).
Browser tests are sharded across independent Playwright processes: each starts its own
production-asset server on its own port (`SAP_LENS_BROWSER_TEST_PORT`) with its own
configuration directory, so the shared-state limits of one server never apply across
processes. Within a process there is one worker and no retries, and
`reuseExistingServer: false` prevents testing stale assets. Chromium saturates CPUs, so
`auto` runs backend modules in `min(3, CPUs)` processes and the browser suite in one;
opt in with `--jobs 3` on a host with spare cores. Measurements (the browser gain was
modest and uneven on 4 vCPUs) are in the [optimization record](../archive/validation/TEST_SUITE_OPTIMIZATION.md).
Do not raise workers inside one server without proving the fixtures cannot race.
R8 measurements on 4 vCPUs (716 browser tests, 34.5 min serial): 2 processes 1.33x, 3 processes 1.50x, 4 processes 1.38x on a six-spec subset, with no failures; test-level
sharding was no faster than file-level sharding. See [test execution performance](TEST_PERFORMANCE_R8.md).

## CI

[CI](CI.md) runs the same runner: Fast Validation runs the full backend through
`regression --backend` plus type checks on every push and PR; Full Validation (PRs to
`main`) runs `regression --backend` and, after one install, type check, catalog check
and production build, `regression --browser --no-build` with dependency audits. CI never
runs `smoke` or `targeted`: path-based selection is not reliable enough to replace
the full backend gate. Deployment package workflows stay manual.

## Troubleshooting

- *Port in use / stale server*: stop leftover `serve-browser-tests.py` processes; browser
  processes use ports 18745 upward.
- *Stale assets*: the runner rebuilds when sources changed; rebuild manually before
  running Playwright directly.
- *Unmapped test file*: add it to `scripts/test-map.json` (`run-tests.py check` explains).
- *One shard fails*: the runner prints the tail of the failing shard log; rerun that spec
  with `--jobs 1` and `--grep` to reproduce serially. Traces stay in the ignored
  `test-results` directory.
- *Timing failures under load*: replace sleeps with assertions, the clock or reduced
  motion; do not add retries.

## Evidence and limits

Record source SHA, exact commands, failures/corrections, final results and environment.
Keep screenshots/traces outside tracked files because real investigations may contain
personal data. Review light and dark themes at 375, 800, 1280 and 1600 px for visual
changes. Linux unit/browser tests and mocked native bridges do not prove
Windows/WebView2, SCM, installer, real systemd boot/recovery or UNC behavior. Never
dispatch expensive builds or publish artifacts without approval; [dated
evidence](../archive/README.md) is historical.

## Fast Validation per phase

About 1.5 to 3 minutes: `git diff --check`, `python scripts/check-docs.py` when docs changed, `python -m ruff check backend scripts` and `npm run lint` in `frontend` (a few seconds each), `npm run check:types` (20 s),
`python scripts/run-tests.py smoke` (44 s), and `python scripts/run-tests.py targeted <feature>...` for what the phase touched
(build first when the UI changed). The full backend and browser suites run once, after the final phase; use the default
`auto` jobs (backend 65 s instead of 170 s) and reserve `--jobs 1` for reproducing a failure.

## Risk-based selection

Run targeted checks while editing, Fast Validation at each phase boundary and Full
Validation once after the final phase ([repository guidance](../../AGENTS.md)).

| Changed area | Targeted coverage |
| --- | --- |
| UI component or filter | Owning feature (`shared-ui`, `role-lookup`, ...), keyboard behavior, type check |
| CSS, layout, theme | `shared-ui` plus the screens changed, representative screenshots |
| Backend API | The feature's backend modules and its browser consumers |
| CSV import | `data-sources`: validation, atomic replacement, failure preservation, persistence, dependent views |
| Authentication/access | `platform` and `repository` plus affected integration tests |
| Shared infrastructure | `regression`; broaden when impact is uncertain |
| Documentation only | `python scripts/check-docs.py` and the `repository` feature |

Inspect imports, callers and fixtures before selecting; this table is guidance, not a
filename-based exemption.

## Linting

- **Python:** `python -m ruff check backend scripts` (Ruff pinned in `backend/requirements-dev.txt`, configured in `ruff.toml`). The baseline selects correctness rules only
  (pyflakes, syntax, pylint errors, mutable defaults, useless expressions, loop closures, `raise` without `from` in `except`, unsafe YAML, blocking calls in async code). It selects no
  formatting or line-length rule because the code base is deliberately dense; nothing was reformatted. A finding is fixed, or silenced on its own line with a reason (`# noqa: CODE (reason)`),
  never ignored globally.
- **Frontend:** `npm run lint` in `frontend` (ESLint 10, flat config in `eslint.config.js`): recommended JavaScript and TypeScript rules, `react-hooks/rules-of-hooks` as an error,
  `react-hooks/exhaustive-deps` as a warning, and two type-aware rules (`no-floating-promises`, `no-misused-promises`) for `src`. The script is `eslint . --max-warnings N`, where N is the
  current backlog (30 hook-dependency warnings in `src`, 81 `any` uses in `tests`): fixing warnings lets you lower N, adding one fails the run. Errors fail it outright.
- Both run in Fast and Full Validation (`ruff`, `eslint` steps), in the `regression` profile's static stage and belong in every phase's Fast Validation.
