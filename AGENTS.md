# Repository guidance

- Preserve the README `<!-- LOGO -->` block, including the logo path, SAP Lens title, and SAP S/4HANA description, unless the user explicitly requests a change. Keep the navigation links immediately below the description in the centered paragraph.
- Each cloud task is isolated. Use the existing checkout; do not create a Git worktree unless requested.
- SAP role exports, local settings, logs, .env files and credentials must not be committed or included in release artifacts.
- The desktop server binds only to 127.0.0.1, preferring port 18743 and securely falling back to an OS-assigned port. Do not weaken local host/origin checks, expose the API to a LAN, or cache role data in a service worker.
- Validate backend changes with `python -m unittest discover -s backend/tests -v`, and frontend changes with `npm ci` and `npm run build` from `frontend`.
- Windows packaging and desktop lifecycle checks run in `.github/workflows/build-windows.yml`.

## Stack and conventions

Verified against `backend/requirements*.txt`, `frontend/package.json` and configs.

- **Backend:** Python 3.12 (CI and Linux lifecycle tests require it; 3.13 fails
  them), FastAPI, Pydantic, Uvicorn, `unittest` in `backend/tests`. App factory
  `backend/main.py:create_app`, routers in `backend/routers/`, one module per domain
  (`csv_*`, `user_access`, `sod_*`). SoD reports use python-docx and ReportLab.
- **Frontend:** React 18, TypeScript, Vite, TanStack Query, Radix ScrollArea,
  lucide-react, Playwright. Node 24 or 25 is enforced by `engines` and the build gate.
  There is no other UI, state or CSS framework.
- **Styling:** Tailwind 3 utilities plus custom CSS. Theme tokens live in
  `frontend/src/styles/tokens.css` (light/dark, applied by `useTheme` through
  `data-theme` and the `dark` class); Tailwind semantic colors alias them in
  `tailwind.config.ts`. Reusable component CSS is in `src/styles/components.css`
  and `src/index.css`. Rules are in the Tailwind-first section below.
- **Frontend layout:** feature areas in `src/components/<Area>` (Access, Dashboard,
  Modules, RoleComparison, RoleDetail, RoleList, Settings, Sod), shared primitives in
  `src/components/Shared` (Button, Select, Combobox, Dialog, Popover, Navigation,
  filters, status pills), the Component Library under Settings, typed clients in
  `src/api`, plus `src/hooks`, `src/lib`, `src/state`. Component contracts:
  [component APIs](docs/architecture/COMPONENTS.md).
- **Responsive/visual:** check light and dark at 375, 800, 1280 and 1600 px with no
  horizontal page scroll. Count-based UI assertions (main navigation buttons, Settings
  tab order, source tiles) change whenever a feature adds an entry; update the
  affected specs in the same change.

## Commands

From the repository root (full list and risk-based selection:
[Testing](docs/development/TESTING.md)).

- Profiles: `python scripts/run-tests.py smoke | targeted <feature>... | regression | release`
  (`list` shows features; ownership in `scripts/test-map.json`, see [Testing](docs/development/TESTING.md)).
- Backend: `python -m unittest discover -s backend/tests -v` in a Python 3.12 venv
  with `backend/requirements-dev.txt`; one module with `-p test_<name>.py`.
- Frontend, in `frontend`: `npm ci`, `npm run check:types`, `npm run lint`, `npm run build`,
  `npm run test:browser`. Build first: Playwright serves `dist` through
  `scripts/serve-browser-tests.py` on 127.0.0.1:18745, and a stale server on that
  port blocks the run. A prepared Chromium may need `PLAYWRIGHT_EXECUTABLE_PATH`;
  report the override. Target with `npm run test:browser -- tests/<file>.spec.ts --grep <name>`.
- Static: `python -m ruff check backend scripts`, `python scripts/check-docs.py`, `python scripts/check-workflows.py`,
  `node scripts/sync-lucide-catalog.mjs --check`, `git diff --check`,
  `npm audit --omit=dev`, `python -m pip check`, pip-audit per [CI](docs/development/CI.md).

## DOM order, focus and reading sequence

- Visual order must match DOM order; Tab order follows logical reading order. Do not use CSS
  `order`, `flex-direction: *-reverse`, positive `tabindex` or absolute repositioning to make
  the screen read differently from the document.
- Responsive layouts may change columns and wrapping, never the reading or focus sequence.
  Reordering configurable regions (for example dashboard cards) reorders the rendered
  elements from a configuration list, not their CSS placement.
- Focus rings use `--focus-width`/`--focus-offset` (a small visible gap). Keep them unclipped:
  scrolling strips use padding and `scroll-padding`, inset rings only where a gap cannot fit.
- Module identity is the shared `ModuleBadge` (icon and abbreviation on one surface); role
  records use `RoleEntry`. Show a module only from catalogue evidence, never infer it.

## Git workflow

- Develop on `work` (tracking `origin/work`). If a checkout is detached at `main`:
  `git checkout -b work --track origin/work`. `main` receives `work` only through
  pull requests; do not push to `main`, tag, release or dispatch workflows without
  explicit authorization.
- Deliver in logically complete, validated increments with conventional subjects
  (`feat(scope):`, `fix(scope):`, `docs:`). Push each phase to `origin/work` once its
  targeted FEATURE validation passes (see Lean development and validation policy), never force-push or rewrite
  history, and verify the result with `git ls-remote origin work`. Allow the
  automatic Fast Validation workflow to run; do not tag, release or manually
  dispatch workflows without authorization. A passing Fast Validation run is not
  proof that deployment packages were built; report package availability only
  after checking the workflow runs and artifacts.

## Working efficiently (AI agents)

- Start at the [documentation index](docs/README.md) and the guide for the area; read
  only the files you change and their direct callers or tests. Prefer Grep/Glob over
  tree-wide exploration, and skip `dist/`, `node_modules/`, `test-results/` and lockfiles.
- Reuse `Shared` components, hooks and `src/api` clients before writing new ones, and
  match the dense style of neighboring code.
- Add no dependencies, frameworks or styling systems, and refactor nothing beyond the
  request. Update the canonical guide instead of writing new reports.
- Run the smallest sufficient checks (see Lean development and validation policy and Efficiency below);
  documentation-only changes need `check-docs.py` and the affected documentation tests.

## Lean development and validation policy

- Prefer focused changes and existing components; no unrelated cleanup or dependencies.
- Use 3–4 logical phases where practical, the lowest sufficient reasoning/check scope,
  short command output and milestone-only reporting. Do not repeatedly read unchanged files.
- **FAST** during implementation: directly affected backend tests and targeted type/static
  checks. Browser checks are opt-in when the behavior needs a browser.
- **FEATURE** after a functional change: affected backend modules/integration tests,
  targeted Playwright workflows and critical edge cases.
- **FULL** only before releases/major merges or explicit user requests: complete backend
  and browser suites, production build, security/static and available platform checks.
  Never run FULL automatically during ordinary development. A failure normally requires
  only its root-cause fix and affected recheck; broader reruns need a concrete impact reason.
- Local entry point: `python scripts/validate.py --level fast|feature|full --area sod`;
  wrappers `scripts/validate.sh` and `scripts/validate.ps1`. Mapping and dependencies live
  in `scripts/test-map.json`; unknown changes fail closed rather than silently omitting tests
  or escalating to FULL. See [Testing](docs/development/TESTING.md).
- Commit and push validated, independently functional phases to `origin/work`; do not wait
  for full regression. Preserve user instructions that explicitly delay a push. Report
  targeted checks separately from pending full regression and automatic GitHub Actions.
- Test storage is disposable and isolated from configured production paths. Browser workers
  stay at one; optional bounded *process* parallelism uses distinct servers/ports/storage.
- Native Windows/WebView2/SCM, real systemd, reboot/recovery and UNC acceptance must be
  reported separately. Do not dispatch remote workflows without explicit authorization.

## Architecture and documentation map

- Preserve approved history and private data; publication limits are in Git workflow.
- SoD: evidence in `sod_import`/`sod_analysis`, pure derivations in `sod_governance`, context
  and filters in `sod_scope`, private decisions in `sod_decisions`, periods and reports in
  `sod_periods`/`sod_reports`; routers `backend/routers/sod*.py`; UI in
  `frontend/src/components/Sod` plus Shared `MatrixGrid`/`SidePanel`. Review decisions never
  change conflict detection, snapshots and decisions are immutable private data, reports render
  from one frozen model. Browser specs share `frontend/tests/sod-fixture.ts` (unique users per
  test because reset keeps review history). Guides: [SoD workflow](docs/features/SOD.md),
  [SoD architecture](docs/architecture/SOD.md), [SoD matrix reference](docs/data/SOD_MATRIX.md).
- Shared business logic lives under `backend/`; `backend/desktop.py` owns the
  Windows WebView2 lifecycle and `backend/server.py` the headless single-worker
  runtime. Centralize hosting policy in `backend/deployment.py`. Do not duplicate
  CSV import, role matching, transaction evidence or account interpretation per OS.
- Server mode must use separate mutable storage, enforce its authentication and
  host/origin boundary, and keep browser uploads local to the configured server.
  Optional disabled/missing sources are not permission to erase valid snapshots.
- `build.sh`/`build.ps1` delegate local orchestration; canonical packaging remains
  in `scripts/`. Keep legacy desktop release behavior separate from deployment
  publication. No automatic tags/releases/registry pushes from local builds.
- Reuse frontend Shared components, semantic tokens and isolated Component Library
  previews. Navigation links, content tabs, filters and actions have distinct
  semantics; preserve keyboard focus and source evidence.
- Start at [documentation index](docs/README.md), [deployment](docs/deployment/README.md),
  [local builds](docs/deployment/BUILD.md),
  [design system](docs/architecture/DESIGN_SYSTEM.md) and
  [component APIs](docs/architecture/COMPONENTS.md). Update the canonical guide and index
  when behavior/commands change, rather than copying procedures into new reports.
- README LOGO navigation links may be maintained when requested, retaining the
  product image/title/description and existing header structure. Do not substitute
  organization branding. Keep licensing and third-party notices intact.
- Run `python scripts/check-docs.py` for relative documentation/image/anchor links.
  GitHub Releases is the release-history mechanism; do not introduce CHANGELOG.md.
- Use synthetic/reserved-domain data only. Never auto-import examples into real
  settings, include examples/private data in packages, or infer effective SAP
  authorization/license entitlement from role/T-code mappings.
- Native Windows installer/SCM/WebView2, real systemd, reboot/recovery and UNC
  acceptance must be reported separately from Linux unit/browser/static checks.
  Keep the Lean development and validation policy and its platform limits in force.

## Planning, continuous execution and progress reporting

- At the start, read the whole request, assess the repository once and publish a
  numbered phase list with dependencies and a completion criterion per phase. Keep
  it in the working plan (not a repository file); explain scope changes instead of
  silently dropping or redefining phases.
- When a multi-phase implementation is authorized, complete all phases sequentially
  without waiting for confirmation, commit and push each validated phase, and
  continue after each milestone report. Do not stop after planning, avoid repeated
  inspection and planning, preserve completed work and unrelated changes, and do not
  restart finished phases. If a blocker stops one phase, report it and continue with
  independent work; never silently skip a requirement.
- Report concisely at: initial assessment, start and completion of each phase,
  genuine blockers, final validation and overall completion. Do not narrate
  individual commands, edits or routine retries. Use this format:

  **SAP Lens — Implementation Progress**
  **Overall:** X/Y phases completed (Z%)
  **Current phase:** Phase N — Name
  **Status:** In progress / Completed / Blocked
  **Completed in this phase:** actual functionality and important corrections
  **Remaining in this phase:** specific unfinished requirements
  **Validation:** FAST/FEATURE Passed/Failed/Pending; targeted results;
  FULL pending unless explicitly requested or required for release
  **Git:** Commit SHA or Not committed; Push Verified/Pending; Branch `work`
  **Next:** next concrete milestone

- Report implemented work, not activity; distinguish implemented, tested, committed
  and pushed. A phase is Completed only after its required validation and push
  succeeded. Percentages count completed phases. Do not claim deployment artifacts
  exist unless verified. Do not ask for approval after a phase unless a genuine
  decision or external authorization is needed.
- The final report reconciles phase counts with the plan and states executed
  validation, branch/commit state, limitations and recommended next steps.


## Efficiency

Use the smallest sufficient check while implementing, FEATURE validation at phase
boundaries; FULL only for an explicit request, release or major merge. Never trade correctness, data
integrity, security or required functionality for speed.

- Prefer scoped inspection, existing shared components, batched related edits, and
  established documentation. Avoid repeated full suites, duplicate implementations,
  unnecessary rewrites, re-reading unchanged files and expensive checks without a
  specific reason.
- Before an expensive command, identify its purpose and whether a targeted
  alternative suffices. Reuse earlier results only when code, dependencies,
  configuration and environment are unchanged. A failed run needs diagnosis and
  affected-test verification first, not an automatic complete restart.
- Use the changed-area selection guide in [Testing](docs/development/TESTING.md).
  Consider transitive dependencies and shared components; when impact is uncertain,
  broaden the targeted set. Preserve test isolation and meaningful coverage; never
  weaken assertions. Do not raise browser workers without before/after benchmarks and
  proof that backend/storage fixtures cannot race, and do not reuse a test server
  with unknown state, assets or credentials.
- Review caches, artifact reuse and job dependencies before changing CI; preserve
  required checks and trust boundaries. Claim speed improvements only with comparable
  measurements. Avoid repeated installs, builds, large logs and screenshots of
  unchanged screens; capture affected screens at representative widths and themes
  during development, with the full theme/breakpoint matrix reserved for explicit FULL validation.
- Controlled parallelism is fine for independent read-only inspections and checks.


## Tailwind-first frontend styling

- Use Tailwind utilities for new or migrated layout, spacing, typography, sizing,
  responsive behavior and routine interaction states. Semantic utilities (`surface`,
  `elevated`, `content`, `secondary`, `muted`, `line`, `action`, `focus`) resolve to
  existing runtime theme variables; do not replace the theme/branding pipeline.
- Order classes by layout, sizing, spacing, typography, colors, then interaction
  and responsive variants. Reuse canonical components before repeating controls.
- Keep custom CSS for reusable component contracts, complex table/portal behavior,
  browser-specific styling and runtime values that utilities cannot express cleanly.
  Inline styles are appropriate for measured portal coordinates, validated dynamic
  module colors and scoped draft theme variables, not ordinary fixed spacing.
- Remove superseded selectors when migrating consumers. Check both themes, keyboard
  focus and hover geometry; tabs reserve a transparent bottom border in every state.
  Active indicators use the primary action color; hover contrasts with the current
  theme. Keep a separate focus-visible outline, avoid persistent rectangular
  selection rings, and retain neutral code borders.
