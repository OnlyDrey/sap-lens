# Testing and validation

Prepare the environment from [Development](DEVELOPMENT.md) and run commands from the
repository root. Never report a check as passed unless it executed; a smoke or
targeted run is not a regression result.

## Profiles

One entry point, `scripts/run-tests.py` (standard library only; Windows and Linux),
selects tests from [`scripts/test-map.json`](../../scripts/test-map.json).

| Profile | Run it | Covers | Typical use |
| --- | --- | --- | --- |
| `fast` | `python scripts/run-tests.py fast [feature ...]` | The cheap checks of one phase: `git diff --check`, documentation links, workflow contracts, Ruff, ESLint, the TypeScript check, then `smoke`, then `targeted` for the features you name | After every phase, before committing (about 2 to 4 minutes) |
| `smoke` | `python scripts/run-tests.py smoke` | Critical backend tests (startup, import, role/user lookup, access package, SoD, security boundary, privacy) and browser tests tagged `@smoke` (launch/import, navigation, dashboard, investigation, comparison, package, SoD, account review) | Seconds-to-a-minute check after any edit |
| `targeted` | `python scripts/run-tests.py targeted sod access-package` | Backend modules and browser specs owned by the named features | While changing a feature |
| `regression` | `python scripts/run-tests.py regression` | Every backend module and browser spec, TypeScript check and production build, documentation links, workflow contracts, icon catalog, whitespace, `pip check` | Before a push of a finished phase or PR |
| `release` | `python scripts/run-tests.py release` | Regression plus `npm audit`, `pip-audit`, PowerShell and workflow lint when those tools exist | Before a release decision |

Useful switches: `--backend` / `--browser` (one side), `--jobs N` (parallel processes;
`auto` by default, `1` disables), `--browser-jobs N|auto` (browser processes, at most 3; see below), `--grep TEXT` (Playwright title filter), `--no-build`
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

### Test categories

| Category | Location | Run by |
| --- | --- | --- |
| Backend unit and integration (`unittest`) | `backend/tests/test_*.py` | every profile; Fast Validation selects owning modules |
| Browser (Playwright) | `frontend/tests/*.spec.ts` | `@smoke` in Fast Validation, the owning specs of a changed spec, everything in regression |
| Frontend unit (`node --test`) | `frontend/tests/unit/*.test.ts` | `npm --prefix frontend run test:unit`; Fast Validation when frontend files change, Full Validation |
| Repository integrity (docs links, tracker, workflows, privacy, ownership) | `repository` feature | always, including documentation-only pushes |
| Platform-specific (Windows, systemd, PowerShell, UNC) | skipped with an explicit reason off-platform | native acceptance, reported separately |

### Retiring a test safely

1. Confirm the production behavior or contract is gone (search for the code, route, option or document it exercised); a failing test is
   not evidence of obsolescence, and a test that exposes a real defect is fixed by repairing the defect.
2. Name the replacement coverage, or state why none is needed, in the commit message. Never retire security, migration, backup or
   regression-for-a-confirmed-defect tests without an equal replacement.
3. Remove the file from `scripts/test-map.json` (including timing hints), then run `python scripts/run-tests.py check`,
   `python scripts/check-docs.py` and the tracker tests: the tracker names spec and document paths, and a stale path fails
   `test_validation_tracker`.
4. When removing documentation, update the validation tracker (CSV and regenerated workbook) in the same change.

## Parallelism and isolation

Backend modules run in parallel processes (each test builds its own temporary storage).
Browser tests are sharded across independent Playwright processes: each starts its own
production-asset server on its own port (`SAP_LENS_BROWSER_TEST_PORT`) with its own
configuration directory, so the shared-state limits of one server never apply across
processes. Within a process there is one worker and no retries, and
`reuseExistingServer: false` prevents testing stale assets. Chromium saturates CPUs, so
`auto` runs backend modules in `min(3, CPUs)` processes and the browser suite in one;
opt in with `--jobs 3` on a host with spare cores. The browser gain was modest and uneven on 4 vCPUs.
Do not raise workers inside one server without proving the fixtures cannot race.
Browser processes: `--browser-jobs N` (or `SAP_LENS_BROWSER_JOBS`) runs the browser tests in up to three isolated processes; `auto` uses one per spare CPU (CPUs minus one, between 1 and 3), so a
1 or 2 CPU host runs one process and a 4 CPU host three. The default stays one process. Spec files are assigned deterministically, longest first, from the measured seconds in
`browser_seconds_hint` of the test map (a new spec gets a 35 s default; refresh the hints from a regression report when specs change a lot). Every process owns its server, port
(18745 upward), configuration directory and Chromium; the runner reports busy ports instead of colliding, starts each process in its own process group and, on completion, error or interrupt,
stops only the groups it started (SIGTERM first, so servers remove their directories), never with a name-based kill. A failure names its process (index, port, spec file count), the failing
tests and the log tail; the regression report lists seconds per process and the ten slowest tests.

Recommended settings: local development on 4 or more CPUs: `regression --browser-jobs auto`; a 1 or 2 CPU host or a memory-constrained container: leave the default; CI: unchanged until it is
measured on the runner you use (hosted runners have 4 CPUs, but Chromium saturates them, and one load-dependent failure appeared in a three-process run). Backend `auto` (min(3, CPUs)
processes) is safe everywhere: each test builds its own storage. Reproduce any failure of a parallel run with `--browser-jobs 1 --grep TITLE` before classifying it.

R8 measurements on 4 vCPUs (716 browser tests, 34.5 min serial): 2 processes 1.33x, 3 processes 1.50x, 4 processes 1.38x on a six-spec subset, with no failures; test-level
sharding was no faster than file-level sharding.

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
dispatch expensive builds or publish artifacts without approval.

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

## Lean local validation (preferred for development)

One policy layer delegates to the existing test engine and ownership map; it does
not replace CI or create a second suite.

| Level | Scope | Default browser behavior |
| --- | --- | --- |
| FAST | Changed-area backend plus relevant type/static checks | No browser |
| FEATURE | Affected area and declared dependency integration tests | Targeted workflows; use `--grep` to narrow |
| FULL | Existing release-validation profile: regression plus security/platform checks | Only when explicitly selected |

```sh
./scripts/validate.sh --level fast --area sod
./scripts/validate.sh --level feature --area sod --grep 'activity matrix'
./scripts/validate.sh --level fast --base origin/work --plan
./scripts/validate.sh --level full --reports
```

```powershell
.\scripts\validate.ps1 -Level Fast -Area SoD
.\scripts\validate.ps1 -Level Feature -Area SoD -Grep 'activity matrix'
.\scripts\validate.ps1 -Level Full -Reports
```

Activate the Python 3.12 development venv first (or set `PYTHON` to its executable),
install the pinned frontend/dev requirements and Playwright Chromium as described
above. No Codex session is needed. FULL uses the existing `release` validation profile; it does not create tags, publish releases or dispatch workflows. With no area, Git diff against `HEAD` includes
working-tree/untracked changes. `--base origin/work` compares against that ref;
it does not fetch or alter Git history. An unrecognized path fails closed and
requires an explicit area or mapping update; it never silently selects FULL.
Source rules and dependency expansion are in `scripts/test-map.json`.

The wrapper removes inherited server/auth/source settings and creates disposable
configuration/data/source directories. SAP Lens uses private JSON/snapshot stores,
not a production test database. Existing browser processes have distinct servers,
ports and storage. Browser **workers remain one**. Optional `--jobs` and
`--browser-jobs` process counts are bounded to 1–3, default one; benchmark CPU/memory
before opting into browser process parallelism. Windows uses `-Jobs`/`-BrowserJobs`.

Concise results point to `build/validation/<UTC timestamp>/validation.log` and JSON
summaries. Traces and browser JSON remain there; `--reports` also retains HTML/JUnit.
Commands are bounded by `--timeout` (seconds); nonzero child/timeout codes propagate.
These directories contain synthetic test artifacts and must not be committed.

Functional grouping already follows feature ownership. Keep semantic/edge-case
checks in backend or focused browser tests; retain meaningful release visual
coverage. During development select the changed workflow rather than repeating
all themes/viewports or the whole SoD area. Shared helpers reduce repeated fixture
setup, but stateful browser workers must not share a backend. The historical full
run's 120-second obsolete-locator failures were wasted time, not evidence that more
workers would help. Full visual matrices remain available for release validation;
no tests were removed to reduce counts.

### Focused SoD reference and navigation checks

For reference/schema changes, use `python -m unittest discover -s backend/tests -p test_sod_reference.py`.
If metadata snapshot preparation changes, also run `test_sod_report_metadata.py` with that
same command pattern. Reference fixtures derive populated records from the canonical JSON;
template tests invoke the real importer and compare generated XML without depending on the
platform's ZIP compression bytes. Source files and inventory are documented in
[SoD reference maintenance](../data/SOD_MATRIX.md#reference-file-inventory-and-maintenance).

After an affected frontend build, navigation can be isolated with
`npm --prefix frontend run test:browser -- tests/sod-catalogue.spec.ts --grep 'entity navigation|Previous and Next|stale navigation' --workers=1`.
Historical definitions deliberately persist: select explicit IDs/search scopes in tests
instead of assuming the target is the only row or remains on page one after other cases.
Full regression remains a release/explicit-request check, not this workflow's prerequisite.

### Synthetic SoD performance profile

With the Python 3.12 development environment installed, run from the repository root:

```sh
python scripts/profile-sod.py --users 200 --samples 9 --output /tmp/sod-profile.json
```

On Windows use a writable output such as `$env:TEMP/sod-profile.json`. The tool generates
synthetic CSVs and imports/reviews them through real APIs in temporary isolated storage;
it never uses configured user data. No server, browser or real dataset is required.
Keep generated results outside Git. Compare the same corpus/sample count/environment.
Measurements and limitations: [SoD architecture](../architecture/SOD.md#measured-request-local-review-state-reuse).
This focused profiler is not a replacement for correctness tests or release regression.


Dependency-free frontend unit checks (`frontend/tests/unit/*.test.ts`: session state machine, Bulk Review selection helpers) run with
`npm --prefix frontend run test:unit`, in Fast Validation whenever frontend files change and in Full Validation. Browser coverage
remains in the mapped specs; these checks do not replace it.

### Data-path benchmark

```sh
python scripts/benchmarks/data_benchmark.py --roles 800 --users 16000 --assignments 12 --json out.json
SAP_LENS_BENCH_BACKEND=/path/to/other/checkout/backend python scripts/benchmarks/data_benchmark.py ...   # compare revisions
```

Synthetic, deterministic data is generated in a temporary directory (nothing under the repository, nothing from a real installation) and each scenario runs in a fresh process against
disposable storage: `import`, `startup` / `startup-warm` (sources dynamic, the default) and `startup-static` / `startup-static-warm`. Output: seconds, peak and resident memory, snapshot and store sizes.
`--employees N` adds an Employee Directory of N employees (matched to the first SAP users) and the `refresh-directory-changed` scenario; `--api` times the heavy read endpoints on a started instance (`--profile api` prints the hottest backend functions per endpoint). `--profile <scenario>` prints the hottest functions. Compare runs only on the same machine, corpus and Python version; keep result files outside Git.

## CI policy and local validation

GitHub Actions CI runs only on push to `main`; pushes to `work`, feature branches and pull requests do not trigger it ([CI policy](CI.md)). Run the Fast/FEATURE validation locally after every phase and the full regression (`python scripts/run-tests.py regression` and the complete browser suite) before merging into `main`.


## Revision consistency

`backend/tests/test_data_revision.py` covers the `X-Data-Revision` token and review submissions during source changes (Account Review and SoD). `frontend/tests/unit/data-revision.test.ts` covers response classification; `frontend/tests/revision-consistency.spec.ts` covers a stale response being repeated and a newer revision from another user being noticed without the configuration poll. Feature: data-sources.

## Browser parallelism experiment (SoD feature, 222 to 245 tests, 4 CPUs, 16 GB)

| Mode | Wall | CPU | Largest process | Result |
| --- | --- | --- | --- | --- |
| 1 Playwright worker | 15.1 min | 419 s | 325 MB | 3 failed (state left by `sod-configuration-recovery`, fixed) |
| 2 workers, one server | 12.0 min | 466 s | 316 MB | 14 failed |
| 3 workers, one server | 12.8 min | 587 s | 306 MB | 34 failed |
| 1 process (`--browser-jobs 1`) | 12.3 min | 396 s | 718 MB | 2 failed (recovery spec, fixed) |
| 2 processes, own server each | 5.6 min | 366 s | 345 MB | 0 failed |
| 3 processes, own server each | 5.4 min | 383 s | 345 MB | 0 failed |

Findings
* Several workers against one server fail because the specs reset configuration and swap the active SoD source, which is global state. This is shared state, not load, so timeouts or retries would only hide it. Workers stay at 1.
* Process-level parallelism (separate server, port and storage per process) is clean. Two processes halve the wall time; a third gains little on 4 CPUs because the shard of the slowest spec files still takes about 5.4 min. Use `--browser-jobs 2` for large browser runs.
* Root cause of the sequential failures: a configuration reset keeps catalogue edits, so a spec that edits a shared risk ID changes later specs. Specs that save catalogue edits must use their own risk IDs and locate them through search, because earlier entries can push them off the first page.
* Specs that wait on a dataset change use `expect.poll` on a request counter or visible text, not fixed delays.
