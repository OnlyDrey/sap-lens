# Testing and validation

Prepare the environment from [Development](DEVELOPMENT.md) and run commands from the
repository root. Never report a check as passed unless it executed; a smoke or
targeted run is not a regression result.


## Test architecture

| Layer | Where | What it proves | Theme / viewport |
| --- | --- | --- | --- |
| Backend unit and integration | `backend/tests/test_*.py` (`unittest`; counts change with the checkout) | Business rules, import, storage, security, SoD governance, packaging scripts | n/a |
| Frontend unit | `frontend/tests/unit/*.test.ts` (`node --test`) | Pure client logic (formatting, session, bulk selection) | n/a |
| Component behavior `@component` | `frontend/tests/component-library.spec.ts` against Settings > Component Library | Generic behavior of shared production components: selection, removal, toggling, validation, confirmation, focus, ARIA | Behavior once in light; focus ring and fit in both themes at 375 and 1280 px |
| Functional page tests (untagged) | `frontend/tests/*.spec.ts` | How each screen uses its data: filters, decisions, exports, navigation, persistence | Default theme, one width, unless the behavior depends on width |
| Layout and visual QA `@visual` | tests generated from `tests/matrix.ts` | No horizontal overflow, wrapping, geometry and placement per width; colors, contrast and focus appearance per theme | See the matrix policy below |
| Accessibility `@a11y` | `a11y-audit`, `navigation-a11y` and tests about keyboard, focus, names, contrast | Names, tab order, visible unclipped focus, modal focus, keyboard operation | Where appearance differs, both themes |
| API integration `@integration` | 2 tests that call the API through the real test server (`revision-consistency`, `sod-user-group-column`) | Complements backend contract tests | TARGETED and FULL only |
| Critical workflows `@workflow` | 9 end-to-end tests (import to package, account review decisions, SoD decisions, period approval, backup/restore, saved filters across reload, bulk review history) | Complete user flows across screens and the server | Default |
| Smoke `@smoke` | 12 tests | The fastest critical path per feature | Default |

There is no screenshot-comparison (pixel) regression: `page.screenshot({ path })` in visual QA tests only writes review artifacts to
`frontend/test-results`. What a visual test proves is in its assertions (overflow, geometry, computed colors, focus outline).

### Theme and viewport matrix policy

The Playwright configuration has no projects; each test chooses its own variants, explicitly, from `frontend/tests/matrix.ts`:

- **Theme-sensitive assertions** (computed colors, contrast, borders, focus outline): an explicit `for (const theme of THEMES)` loop.
- **Theme-independent layout** (overflow, geometry, wrapping, behavior at a width): `for (const { theme, width } of layoutMatrix([375, 800, 1280, 1600]))`,
  which runs every width in light and dark once at 1280 px (or the widest width) so dark rendering of that screen stays exercised.
- **Theme-independent behavior without a width dimension**: `DEFAULT_THEME_ONLY` or no loop at all.

Before choosing, read what the test asserts, not its title. In November 2026, 25 generated groups whose bodies never read the theme
(only applied it) moved to `layoutMatrix`/`DEFAULT_THEME_ONLY`: 909 to 857 executions, all four widths and dark rendering retained.

### Component Library as the shared-component fixture

Settings > Component Library renders the **production** Shared components (no demo copies) with synthetic data. Generic behavior of a shared
component is tested there once (`component-library.spec.ts`, previews in `ComponentLibraryStates.tsx` and `ComponentLibrary.tsx`); a page
spec tests only what the page adds (its data, filter semantics, decisions). New shared components get a preview with stable accessible
names and, when they have interactive behavior, a test in `component-library.spec.ts`. The library is part of Settings and holds no real data.

### Backend output and logging policy

- `run-tests.py` runs backend tests **buffered**: a test's stdout, stderr and application log lines are shown only when that test fails, with
  its traceback. Expected diagnostics of negative tests (CSV retained, retention retried, synthetic packaging and release reports) therefore
  stay out of a passing run, and nothing is suppressed globally: application logging is unchanged.
- Negative tests whose purpose is a logged diagnostic assert it with `self.assertLogs(logger, level)` (example: the CSV preservation tests in
  `test_application.py`), which both proves the message and keeps it off the console.
- `ResourceWarning`s (unclosed files, sockets, pipes) are collected and listed in the summary instead of disappearing in the buffer.
- A worker prints a heartbeat (`[backend 2/3] 812 tests, 0 failed, 90s`) every 30 s (`SAP_LENS_TEST_HEARTBEAT`, `0` disables).
- `--verbose` shows one line per test and unbuffered output, the mode for debugging what a test prints.

## Progressive validation

The default for every change (policy in [AGENTS.md](../../AGENTS.md)). Start small, widen only after the smaller set is green, stop
widening at the first failure and fix it there.

| Level | When | Command (Windows PowerShell 5.1, PowerShell 7 and Linux alike) |
| --- | --- | --- |
| 1 Direct | after every change | `python scripts/run-tests.py targeted --spec session-recovery --grep "Retry"` (browser, one process); `targeted --test test_sod_periods_v2.WorkflowTests` (backend); `npm --prefix frontend run check:types`; `python -m ruff check <files>` |
| 1 Repeat | a test that failed or was intermittent | add `--repeat-each 5` (passed through to Playwright) |
| 2 Affected | Level 1 green | the complete spec files (`--spec` without `--grep`); `python scripts/run-tests.py quick` selects the backend modules and specs the change reaches through the import graphs |
| 3 Stability | when concurrency or load is part of the behaviour | the smallest group with `--browser-jobs 2` or `3`; load reproduction under Troubleshooting |
| 4 Checkpoint | phase end, cross-component change, before delivery, before merge | `targeted <feature>...`, `regression`, `full` (FULL only before a merge or release or when asked) |

Report which tests ran, why, and the counts. A change without a relevant automated test is reported as a coverage gap.

## Common tasks

| Question | Command |
| --- | --- |
| Run only backend tests | `python scripts/run-tests.py full --backend` (quiet, three processes) |
| Run one failing backend test | `python scripts/run-tests.py targeted --test test_sod_reports.FormalReportTests.test_status_labels_distinguish_draft_reviewed_approved_and_external_signature` (module, class or method; repeat `--test`) |
| Plain `unittest`, without the runner | `cd backend/tests && python -m unittest -b --durations 10 test_sod_reports` (`-b` buffers output like the runner) |
| Only frontend functional tests | `npm --prefix frontend run test:functional` (everything not tagged `@visual`, `@a11y` or `@component`) |
| Validate the Component Library | `npm --prefix frontend run test:component` |
| Accessibility tests | `npm --prefix frontend run test:a11y` |
| Layout and visual QA | `npm --prefix frontend run test:visual` |
| Critical workflows | `npm --prefix frontend run test:workflow` |
| What did my change reach? | `python scripts/run-tests.py targeted --plan` (add `--base origin/work` for committed work) |
| The complete suite | `python scripts/run-tests.py full` (add `--browser-jobs auto` on 4+ CPUs) |
| Keep a log | add `--log build/test-logs/run.log`; `validate.py` writes `build/validation/<UTC timestamp>/` |
| Find slow tests | `--slowest 20` (backend and browser; `regression` and `full` list 10 by default) |
| Which tests need native Windows | the platform rows of the [validation matrix](../deployment/README.md#validation-status); Linux runs never prove them |

Browser commands need a current build (`npm --prefix frontend run build`) and, on a prepared host, `PLAYWRIGHT_EXECUTABLE_PATH`.
Run `--workers=1 --retries=0` while investigating; never add retries to hide a flaky test.


## PowerShell 7 on Linux

`backend/tests/test_powershell.py` runs when `pwsh` is installed (Microsoft's `packages-microsoft-prod` apt repository for Ubuntu/Debian, `apt-get install powershell`) and is skipped otherwise. It checks that every `.ps1` parses, `build.ps1` parameter binding (including `-CheckOnly`, `-Repair`, `-Json`), interpreter probing with paths containing spaces, exit-code propagation, a bounded hung child, and that `prerequisites --check-only` through PowerShell is read-only. It does not cover Windows PowerShell 5.1, Windows APIs or native paths; those stay in the native Windows acceptance list. Hosted Linux runners ship `pwsh`, so the file adds about ten seconds to the existing backend job and needs no extra workflow. `scripts/check-powershell-compat.ps1` (also run by `check-powershell.ps1`) is a built-in AST analysis, with no extra module, for constructs Windows PowerShell 5.1 lacks: ternary, `??`, `?.`, `&&`/`||`, PowerShell 7-only parameters, cmdlets, variables (`$IsWindows`) and .NET Core-only APIs, plus warnings for encoding defaults, `Start-Process -ArgumentList` quoting and literal quotes in native arguments. Errors fail, warnings inform. It is static: it cannot prove that 5.1 runs a script, and successful PowerShell 7 execution is not evidence for 5.1. PSScriptAnalyzer was not available in the sandbox (PowerShell Gallery blocked) and has not been run.

## Profiles

One entry point, `scripts/run-tests.py` (standard library only; Windows and Linux), four profiles. `validate.py --level` is the same
four levels with isolated storage, a log directory and a timeout (`fast` = quick, `feature` = targeted).

| Profile | Run it | Covers | When | Measured (Linux, 4 vCPUs, `--browser-jobs auto`) |
| --- | --- | --- | --- | --- |
| `quick` | `python scripts/run-tests.py quick` | Whitespace, docs links, workflow contracts, test map, Ruff; ESLint and the TypeScript check when frontend files changed; frontend unit tests; the backend modules the change reaches (release/packaging modules only when the change touches packaging). **No browser.** | After every edit | 35 to 50 s for a test-infrastructure change (96 to 439 backend tests) |
| `targeted` | `python scripts/run-tests.py targeted` (or `targeted FEATURE ...`) | The backend modules and browser specs the change reaches, browser smoke, the security modules for security-sensitive paths | Before committing a change | Backend source change: 2 min 27 s (1,285 backend + 45 browser tests). SoD page change: 2 min 6 s (Periods, 6 specs) to 4 min 11 s (bulk review on Explorer and Reviews, 20 specs); a shared SoD file still runs all 31 SoD specs (5 min 24 s) |
| `regression` | `python scripts/run-tests.py regression` | Every backend module except release/packaging (1,431 tests), the non-matrix tests of 16 critical specs, every `@smoke`, `@workflow`, `@component` and `@regression` test (123 browser tests), static checks, unit tests | Before pushing a finished phase | 4 min 42 s |
| `full` | `python scripts/run-tests.py full` | Everything: all backend modules, all browser tests including the theme/viewport matrices, unit tests, build, static checks, and `npm audit`/`pip-audit`/PowerShell checks where available (a NOTE names each check this machine cannot run) | Before a merge or release, and in Full Validation | 15 min 45 s with 3 browser processes (1,786 backend + 859 browser tests, all green); the browser half alone takes 26 min with 1 process (the CI setting) |

QUICK and TARGETED compare with `HEAD` by default (uncommitted and untracked changes); `--base origin/work` covers committed work.
`--plan` prints the selection and the reason for each path without running anything. Earlier names still work and say so: `fast`
is `quick`, `release` is `full`. `changed` is the conservative CI selection (whole backend for any backend change) and `smoke` the
`@smoke` subset; neither is a development profile.

**How QUICK and TARGETED select** (`plan_targeted` in `run-tests.py`, tested by `test_test_profiles.RiskBasedSelectionTests`):

- A backend file selects every test module that imports it, directly or through other modules (the Python import graph), plus the
  browser specs of its feature in `validation_sources`. `main.py` imports every router, so most backend changes reach about 75 of
  109 modules; the selection is exact, not small.
- A frontend file selects the specs that import it and the specs of the features whose files import it (the TypeScript import
  graph). A file used by more than four features, a stylesheet, a toolchain file or a new file with no consumer yet selects the
  REGRESSION browser set instead; a Shared component also runs `component-library`.
- A frontend file inside a mapped area (`profiles.page_specs`, currently SoD) is walked up the import graph to the page roots that
  render it, and selects the specs that open those pages plus the area's core specs (`page_core_specs`). A file that reaches the
  area's container, `App.tsx` or anything outside the area first (the shared module, the investigation panel, decision status) is
  shared and selects the whole feature. Keep the page lists current when a spec starts or stops opening a page.
- A test file runs itself; a test helper runs the tests that import it (a browser helper used by more than 25 specs selects the
  REGRESSION browser set).
- Security-sensitive paths (`profiles.security_sensitive`: server, deployment, routers, storage, backups, Windows identity) always add
  `profiles.security_modules`. Changes to the selection system (`test-map.json`, `run-tests.py`, `validate.py`, the Playwright
  configuration) run its own tests.
- Documentation selects only the repository-integrity modules. Anything else that cannot be resolved runs the whole backend and the
  REGRESSION browser set. Nothing is skipped silently: every broadening is printed as a NOTE.

Useful switches: `--backend` / `--browser` (one side), `--jobs N` (backend processes; `auto` = min(3, CPUs)), `--browser-jobs N|auto`
(at most 3 isolated browser processes), `--grep TEXT`, `--no-build`, `--list-tests`, `--plan`, `--report FILE` (JSON),
`--test NAME` (backend unittest names, with `targeted`), `--verbose`, `--slowest N`, `--log FILE`. `list` shows the features;
`check` validates the map. The runner rebuilds the frontend only when sources are newer than `frontend/dist`, prints skipped tests with
their reasons, and every partial profile says that it is partial and what it left out.

Windows-only items are reported NOT EXECUTED on Linux: the checklist in [Windows service](../deployment/WINDOWS_SERVICE.md#native-windows-acceptance-checklist-accounts-reviewer-identity-and-encrypted-backups) (rows 1 to 18) is the list of what a Windows run must still show. The Service Manager C# is parse-checked and its pure validation members are compiled and run under Mono when `mcs` and `mono` are installed; it is not compiled with the .NET Framework `csc.exe` here. CI runs only on pushes to `main` after a merge; development validates locally (focused tests per change, REGRESSION per phase, FULL before a merge).

App Control diagnostics are tested without touching any policy: `test_windows_app_control_evidence.py` runs the PowerShell evidence functions against synthetic Code Integrity events (field spellings, path correlation, window, 3077 and 3033, audit-only 3076, unreadable events), the backup-key command contract against throw-away directories, and the installer-harness contracts; `test_native_blocked_reporting.py` covers the blocked manifest row, the verdict lines and the exit status. Real enforcement is NOT EXECUTED on Linux.

A Linux run never proves Docker image runs, the Windows installer, service, WebView2, native Linux packages or systemd; those belong to
the manual build workflows and the [validation matrix](../deployment/README.md#validation-status).

Underlying commands (still valid on their own): `python -m unittest -b discover -s backend/tests` (`-b` keeps expected diagnostics out of a passing run),
`npm --prefix frontend run test:unit`, `npm --prefix frontend run build`, `npm --prefix frontend run test:browser -- tests/<file>.spec.ts --grep <title>`,
`python scripts/check-docs.py`, `python scripts/check-workflows.py`, `node scripts/sync-lucide-catalog.mjs --check`, `git diff --check`.
A prepared host may need `PLAYWRIGHT_EXECUTABLE_PATH` for Chromium; report that override.

### Runner output, exit codes and artifacts

- The run starts with a header (profile, backend and browser processes, log file). Every stage prints `[start]` and `[done]` lines.
- Browser tests report live through `frontend/tests/progress-reporter.ts`: each finished test (`[02:31] PASS    file.spec.ts:12 > title (1.4s)`),
  each failure with its first error lines as soon as it happens (`FAIL`, `TIMEOUT`, `FLAKY`), and every `SAP_LENS_TEST_HEARTBEAT` seconds
  (30 by default) `[05:00] 191/666 completed | passed 190 | failed 1 | skipped 0` with each process's position. `SAP_LENS_TEST_PROGRESS=summary`
  hides the passing tests. Backend workers print a heartbeat with failed and skipped counts and a `FAIL:`/`ERROR:` line the moment a test fails.
- The run ends with `Summary: P passed | F failed | S skipped` and `Result: PASSED|FAILED... | Duration | Exit code | Log | Report`, plus the
  failed test names.
- Console encoding: the runner prints to stdout only (stderr made Windows PowerShell 5.1 show `NativeCommandError` when output was
  redirected). A terminal and a UTF-8 pipe get the text unchanged; a redirected Windows console, whose bytes PowerShell 5.1 decodes in
  another code page (`›` became `ΓÇ║`), gets readable ASCII (`>`); `SAP_LENS_TEST_ASCII=1|0` forces it. `--log FILE` keeps UTF-8.
  Prefer `--log` over `*>`, `Out-File` or `Tee-Object`.
- Status colours on an interactive terminal: PASS green; FAIL, ERROR, TIMEOUT and infrastructure problems red; FLAKY, NOTE and warnings
  yellow; SKIP gray; `[start]` and the profile header cyan; non-zero counts in the summaries and the final `Result` in the matching colour.
  Only the status word or value is coloured. Windows uses ANSI where the console accepts it (Windows 10+ console, Windows Terminal,
  PowerShell 5.1 and 7) and console text attributes otherwise. Redirected or piped output, `--log`, JSON reports and `TERM=dumb` stay
  plain; `NO_COLOR` (any value) or `SAP_LENS_TEST_COLOR=never` switches colours off, `SAP_LENS_TEST_COLOR=always` forces ANSI.
- The summary counts passed, failed and skipped tests per stage and in total. Exit codes: `0` everything passed, `1` a test or check
  failed, `2` only infrastructure failed (a busy port, a test server or Playwright that did not start, a worker or process without a
  report, a timeout); infrastructure problems are listed separately and never counted as test results.
- Each Playwright process (also a single one) writes stdout and stderr to separate UTF-8 files (`log-N.out.txt`, `log-N.err.txt`, with the test server's lines), which are closed before they are read or deleted. A process
  that runs longer than `SAP_LENS_BROWSER_TIMEOUT` seconds (5,400 by default) is stopped with its last position and log tail.
- The runner stops only the process trees it started: on POSIX the process group, on Windows Ctrl+Break to the group and then
  `taskkill /PID <pid> /T /F` (never by name), so no node, Chromium or test server keeps files or ports open. Scratch directories are
  removed with bounded retries for transient Windows locks; a cleanup problem is a note and never replaces the test result.
- A failed browser stage keeps its reports, logs and traces in `build/test-artifacts/<stage>-<time>/` (ignored by Git).
- The test server and every Python subprocess of a spec use the runner's interpreter (`SAP_LENS_TEST_PYTHON`, resolved in
  `frontend/tests/python.ts`; without the runner the project `.venv`), never the first `python` on PATH.

### Test ownership and the coverage map

Test behavior in the layer that implements it: pure frontend functions in `frontend/tests/unit` (`node --test`), business rules and API
contracts in backend `unittest` modules, generic component behavior in `component-library.spec.ts`, page integration and user journeys
in Playwright, installer and service behavior in native platform tests. A browser test that never touches the page belongs in a lower
layer (nine such tests moved to `frontend/tests/unit` in November 2026).

`scripts/test-map.json` is the coverage map. Each feature lists its backend modules and browser specs (each file belongs to exactly one
feature), its primary test `owner` layer (`backend`, `browser`, `component`, `platform`), `criticality` (`critical`, `standard`, `release`)
and `platform`. `validation_sources` maps source paths to features, `validation_dependencies` the features a change also reaches, and
`profiles` holds the release features excluded from REGRESSION, the REGRESSION browser specs and tags, and the security rules.
`test_test_profiles` fails when a file is unmapped, a critical feature is excluded from REGRESSION, or a listed spec or module is missing.

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

[CI](CI.md) runs only on push to `main`. Fast Validation uses the conservative `changed` selection (whole backend for any backend
change, browser smoke and changed specs for frontend changes); the manual Full Validation runs `full --backend` and
`full --browser --no-build`. Deployment package workflows stay manual and may not run the complete suites.

## Troubleshooting

- *Port in use / stale server*: stop leftover `testing/serve-browser-tests.py` processes; browser
  processes use ports 18745 upward.
- *Stale assets*: the runner rebuilds when sources changed; rebuild manually before
  running Playwright directly.
- *Unmapped test file*: add it to `scripts/test-map.json` (`run-tests.py check` explains).
- *One shard fails*: the runner prints the tail of the failing shard log; rerun that spec
  with `--jobs 1` and `--grep` to reproduce serially. Traces stay in the ignored
  `test-results` directory.
- *Timing failures under load*: replace sleeps with assertions, the clock or reduced
  motion; do not add retries.
- *Failure only in a 3-process run*: look for a one-shot read after an asynchronous action (`expect(await x.count())`,
  `await x.textContent()` used as a baseline, reading the clipboard right after a click) and wait for the application's own signal
  instead (`toHaveCount`, `expect.poll`, the status message the action announces). To reproduce, copy the spec to a temporary file
  and add `test.beforeEach` with CDP CPU throttling (`Emulation.setCPUThrottlingRate`, rate 6 to 10) plus a `page.route('**/api/**')`
  that delays each request randomly before `route.fallback()`; run it with `--repeat-each`. Delete the copy afterwards.
- *Layout failure only on one machine (fonts)*: the UI font is `'Montserrat',Arial,sans-serif` and Montserrat is not bundled, so a machine
  with Montserrat installed (seen on Windows) renders text about 12% wider than the Arial-metric fallback that Linux and CI use. Wrapped
  labels and taller panels then change heights, popover sides and hit targets. Reproduce on Linux by routing a same-origin URL to the
  Montserrat woff2 files and injecting `@font-face` rules with `addInitScript` in a temporary spec copy (`font-src 'self'` blocks `data:` fonts;
  attach the style once `document.documentElement` exists). Fix the component when it breaks its own contract; assertions that depend on text
  width measure the brand font when it is present and otherwise allow the 12% (see `session-recovery` and `ui-polish-actions`), and assertions
  on popover placement derive the expected side from the measured room instead of assuming one.
- *State left by a test*: saved filters, local SoD annotations, review decisions and review periods are user data that a configuration
  reset keeps. A spec deletes what it can delete in `afterEach` (`cleanup()` in `sod-fixture.ts` removes SoD saved filters; see also
  `release-roles` and `sod-metadata`) and gives immutable records unique names (`uniqueName()` for periods, unique users for decisions),
  and audit-log assertions filter to the records the test created. Check with `--repeat-each 2`: a leak fails the second repetition.
- *Settings Apply*: Settings count as unsaved until Apply completes. Navigating meanwhile opens the discard prompt (Playwright dismisses it,
  so the view stays where Settings opened), a reload cancels the save, and a configuration read can still return the old values. After
  `Apply settings`, wait for `getByRole('status').filter({ hasText: 'Settings saved successfully.' })` before the next step.
- *Recovery the application does by itself*: the configuration poll (every 3 s) reconnects a lost session without the user. A test that
  checks a manual action (Retry) keeps the failure in place until that action happened, detected in the page, instead of racing the poll.
- *Search-as-you-type lists*: server-backed option lists are debounced and show the previous results while a search runs. The shared
  `MultiSelectFilter` treats Enter during that window as a choice only for a value that matches the typed text; tests do not need sleeps.
- *`PermissionError: [WinError 32]` on a `.sqlite3` file in teardown*: a SQLite connection is still open. Windows opens database files
  without delete sharing, so one connection left to the garbage collector blocks removing the temporary directory (and, in production,
  restoring or migrating a data directory). `with sqlite3.connect(...)` only commits; it does not close. Every connection is closed
  explicitly (`contextlib.closing` or a `finally`), as `auth_store.ConnectionLifecycleTests` asserts with the collector disabled. Do not add
  sleeps, retries or `ignore_cleanup_errors`; find the connection. On Linux, `python scripts/testing/open-files-at-cleanup.py [MODULE ...]`
  lists every file still open inside a temporary directory when it is cleaned up, which is exactly what Windows refuses.
- *`ENVIRONMENT ERROR: the test interpreter is missing ... required package(s)`* (exit code 2, no test started): the Python that runs
  the tests lacks pinned requirements, typically after an update added a dependency. Run the printed `pip install -r` command for that
  interpreter or `build.ps1 -Mode prerequisites`; see [setup](DEVELOPMENT.md#1-one-time-setup). `--plan` and `--list-tests` need no
  dependencies.
- *Clipboard assertions*: never read `navigator.clipboard.readText()` back. The clipboard belongs to the whole browser (on Windows
  possibly to every browser process of a parallel run) and `writeText` finishes after the click, so a read can return an earlier
  test's value. Call `recordClipboard(page)` from `tests/support.ts` before the copy (it also grants the permissions) and assert
  with `await expect.poll(() => copiedText(page)).toBe(...)`; the real `writeText` still runs.
- *Reading a failure's page snapshot*: `error-context.md` and the failure screenshot are taken when the `page` fixture closes, after
  `afterEach` has run. Fixtures reset the server there, so the snapshot usually shows "Choose a SAP role catalogue or user access CSV in
  Settings" or an empty source even when the data was loaded while the test ran. Judge the failure by the error and call log, not by that banner.
- *Server diagnostics*: every test server reports on stderr (kept in the shard's `log-N.err.txt` of a failed run) its start and stop, requests
  slower than 2 s (`SAP_LENS_TEST_SLOW_MS` changes the threshold), server errors and requests that ended without a response.
  `SAP_LENS_TEST_REQUEST_LOG=<file>` appends every request with its duration (paths only, no query strings) for latency analysis.
  Failed CSV loads log their operation, source, category and exception class or OS error code, never the path or content.
- *`socket hang up` / `ECONNRESET` on API requests*: the test server keeps idle connections for 150 s, longer than the test timeout,
  because Playwright's API client reuses keep-alive connections without an idle limit; a shorter server timeout closes a connection the
  client is reusing at that moment.
- *`route.fulfill: Route is already handled!`*: `page.unroute()` does not wait for a handler that is still awaiting
  `route.fetch()`; Playwright continues that request underneath it and the handler's later `fulfill` fails. When a handler is
  asynchronous, remove it with `await page.unrouteAll({ behavior: 'wait' })` (or keep it for the whole test).

## Evidence and limits

Record source SHA, exact commands, failures/corrections, final results and environment.
Keep screenshots/traces outside tracked files because real investigations may contain
personal data. Review light and dark themes at 375, 800, 1280 and 1600 px for visual
changes. Linux unit/browser tests and mocked native bridges do not prove
Windows/WebView2, SCM, installer, real systemd boot/recovery or UNC behavior. Never
dispatch expensive builds or publish artifacts without approval.

## Linting

- **Python:** `python -m ruff check backend scripts` (Ruff pinned in `backend/requirements-dev.txt`, configured in `ruff.toml`). The baseline selects correctness rules only
  (pyflakes, syntax, pylint errors, mutable defaults, useless expressions, loop closures, `raise` without `from` in `except`, unsafe YAML, blocking calls in async code). It selects no
  formatting or line-length rule because the code base is deliberately dense; nothing was reformatted. A finding is fixed, or silenced on its own line with a reason (`# noqa: CODE (reason)`),
  never ignored globally.
- **Frontend:** `npm run lint` in `frontend` (ESLint 10, flat config in `eslint.config.js`): recommended JavaScript and TypeScript rules, `react-hooks/rules-of-hooks` as an error,
  `react-hooks/exhaustive-deps` as a warning, and two type-aware rules (`no-floating-promises`, `no-misused-promises`) for `src`. The script is `eslint . --max-warnings N`, where N is the
  current backlog (30 hook-dependency warnings in `src`, 81 `any` uses in `tests`): fixing warnings lets you lower N, adding one fails the run. Errors fail it outright.
- Both run in QUICK (ESLint when frontend files changed), REGRESSION and FULL, and in CI Fast and Full Validation.

## Isolated local validation (`validate.py`)

`scripts/validate.py --level quick|targeted|regression|full` (also `fast` and `feature`) runs the same profile with disposable
configuration, data and source directories, no inherited server, authentication or source settings, a log directory and a timeout:

```sh
python scripts/validate.py --level quick
python scripts/validate.py --level targeted --area sod --grep 'activity matrix'
python scripts/validate.py --level targeted --base origin/work --plan
python scripts/validate.py --level full --reports
```

The same commands run in Windows PowerShell (`python scripts\validate.py --level quick`). Run `.\scripts\build.ps1 -Mode prerequisites`
once first. Results go to `build/validation/<UTC timestamp>/` (`validation.log`, `run-tests.log`, JSON summary, traces; `--reports`
also keeps HTML/JUnit). These are synthetic artifacts and are never committed. REGRESSION and FULL cannot be narrowed with
`--area`, `--grep` or `--no-build`. Browser workers stay at one per process; `--jobs`/`--browser-jobs` are bounded to 1 to 3.

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
python scripts/benchmarks/profile-sod.py --users 200 --samples 9 --output /tmp/sod-profile.json
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

GitHub Actions CI runs only on push to `main`; pushes to `work`, feature branches and pull requests do not trigger it ([CI policy](CI.md)). Run QUICK/TARGETED during a phase, REGRESSION before pushing a finished phase and FULL (`python scripts/run-tests.py full`) before merging into `main`.


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

### Interrupted runs and resource cleanup

* `scripts/run-tests.py` stops the process groups it started (servers, Chromium) on normal exit, Ctrl+C, SIGTERM and SIGHUP (`cleanup_on_signals`). It never signals a process it did not start; a busy test port is reported, not freed.
* A killed runner or Playwright (SIGKILL) cannot clean up itself, so the test server watches its parent (`exit_with_parent` in `scripts/testing/serve-browser-tests.py`): when the parent is gone it exits through its SIGTERM handler, which removes its storage directory and releases the port. `playwright.config.ts` starts the server with `exec` on POSIX so the parent is Playwright itself.
* Every job has its own port (`18745 + index`), its own server and its own temporary configuration directory, which holds that job's SQLite store, snapshots and settings. Nothing is shared between jobs.
* Regression tests: `backend/tests/test_test_profiles.py` (SIGTERM of the runner, SIGKILL of the parent, SIGTERM of the server, busy ports, distinct ports and storage).
* A stray server on a test port is identified before it is stopped: `ps -o pid,ppid,etimes,user,args -p PID`, its working directory (`readlink /proc/PID/cwd`) and its parent. Only a `testing/serve-browser-tests.py` process with a dead parent (PPID 1) that you started is an orphan.

## PowerShell 5.1 SCM management host

SCM acceptance starts its management host with `System.Diagnostics.Process`,
`UseShellExecute=false` and a retained process handle. The former
`Start-Process -PassThru` path could report HasExited but expose an empty ExitCode
on Windows PowerShell 5.1. Missing/non-integer exit status now has its own explicit
failure; it is never treated as zero. Disposal happens after exit/output handling.
The executable is passed via ProcessStartInfo.FileName, and Arguments contains
only fixed switches and a UTF-16 Base64 encoded command. Script paths and named
argument values remain quoted in that payload; shell joining of space-containing
paths is avoided. No execution-policy bypass is used.

Both output streams drain asynchronously to avoid pipe deadlocks and are relayed
before the outer PASS/FAIL message. Management has a 180-second limit; only the
owned child is terminated on timeout. Post-exit pipe draining is bounded, since a
descendant could retain an inherited pipe. Capture failures block acceptance.
The retention.json cleanup correction and evidence-after-cleanup gate are unchanged.

From the Windows repository root (no SCM lifecycle is executed by these tests):

```powershell
powershell -NoProfile -File .\scripts\check-powershell.ps1
python scripts/run-tests.py targeted --test test_windows_acceptance_split --jobs 1 --log build/scm-process-native.log --report build/scm-process-native.json
```

Run with Windows PowerShell 5.1 and PowerShell 7 installed when possible: the helper
cases cover both detected shells, success, explicit nonzero exit, timeout,
unavailable exit status, output capture and paths containing spaces/apostrophes.
A helper pass does not establish native SCM installation/upgrade/cleanup acceptance.

### SCM large-workspace regression

The acceptance helper module includes a 620-file nested workspace (including
Read-only `retention.json` and directories), child cleanup followed by create-only
evidence, and a simulated blocked-operation watchdog preserving diagnostics and
ownership. Existing lock, inaccessible/SYSTEM-owner, junction, marker and boundary
tests remain. Native helper cases require Windows/PowerShell and do not install
SCM services. See [cleanup diagnostics and native commands](../deployment/WINDOWS_SERVICE.md#cleanup-traversal-and-external-watchdog).
