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

- Backend: `python -m unittest discover -s backend/tests -v` in a Python 3.12 venv
  with `backend/requirements-dev.txt`; one module with `-p test_<name>.py`.
- Frontend, in `frontend`: `npm ci`, `npm run check:types`, `npm run build`,
  `npm run test:browser`. Build first: Playwright serves `dist` through
  `scripts/serve-browser-tests.py` on 127.0.0.1:18745, and a stale server on that
  port blocks the run. A prepared Chromium may need `PLAYWRIGHT_EXECUTABLE_PATH`;
  report the override. Target with `npm run test:browser -- tests/<file>.spec.ts --grep <name>`.
- Static: `python scripts/check-docs.py`, `python scripts/check-workflows.py`,
  `node scripts/sync-lucide-catalog.mjs --check`, `git diff --check`,
  `npm audit --omit=dev`, `python -m pip check`, pip-audit per [CI](docs/development/CI.md).

## Git workflow

- Develop on `work` (tracking `origin/work`). If a checkout is detached at `main`:
  `git checkout -b work --track origin/work`. `main` receives `work` only through
  pull requests; do not push to `main`, tag, release or dispatch workflows without
  explicit authorization.
- Deliver in logically complete, validated increments with conventional subjects
  (`feat(scope):`, `fix(scope):`, `docs:`). Push to `origin/work` only after the
  pre-push validation below, never force-push or rewrite history, and verify the
  result with `git ls-remote origin work`.

## Working efficiently (AI agents)

- Start at the [documentation index](docs/README.md) and the guide for the area; read
  only the files you change and their direct callers or tests. Prefer Grep/Glob over
  tree-wide exploration, and skip `dist/`, `node_modules/`, `test-results/` and lockfiles.
- Reuse `Shared` components, hooks and `src/api` clients before writing new ones, and
  match the dense style of neighboring code.
- Add no dependencies, frameworks or styling systems, and refactor nothing beyond the
  request. Update the canonical guide instead of writing new reports.
- Run the smallest sufficient checks (see Efficient Execution below); documentation-only
  changes need `check-docs.py` and the affected documentation tests.

## Mandatory pre-push validation

Complete the implementation locally before pushing. Do not push partial work or
start remote builds as an iterative debugging loop. Preserve existing local-only
commits. Run and record the exact commands and results before delivery:

1. Relevant fast checks, including `git diff --check` and workflow lint when changed.
2. `npm ci`, `npm run check:types`, and `npm run build` in `frontend`.
3. `python -m unittest discover -s backend/tests -v` in the prepared virtualenv,
   including repository integrity/privacy, configuration persistence and migration tests.
4. `python -m pip check`, applicable Python vulnerability auditing, and
   `npm audit --omit=dev`. Report development advisories separately; do not suppress findings.
5. `npm run test:browser` in `frontend`, plus regression tests for changed behavior.
   Inspect screenshots and meaningful screenshot comparisons for visual changes.
6. When packaging, Windows build behavior, desktop integration or release readiness
   is affected, run the canonical Windows build and packaged EXE smoke tests on
   Windows. Verify output assets, privacy boundaries and SHA-256 manifests.

A TypeScript build alone is insufficient. If a required check fails, investigate,
fix and rerun affected checks first. Use the risk-based policy below to determine
whether another complete run is justified; a failed full run alone does not mandate
repeating unchanged successful checks. Never report a
check as passed unless it actually executed successfully. Record commands,
outcomes, visual review and platform limitations in the delivery report.

If Windows testing is unavailable, state that explicitly: Linux browser/unit tests
are not equivalent to Windows/WebView2 or packaged-EXE validation. Finish all
available local work and present a concrete reviewable result, then request
explicit approval before pushing with incomplete Windows validation. Do not claim
complete validation. Only push the finished version after required checks pass or
such an exception is explicitly approved. Verify the remote SHA after an authorized
push. Do not start a remote Windows build without explicit authorization.

After changing Lucide or its catalog, run `node scripts/sync-lucide-catalog.mjs --check`
following `npm ci`; regenerate with the same script without `--check` when needed.

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
  Preserve the mandatory validation and explicit pre-push approval rules above.

## Task Planning, Progress Tracking & Reporting

These requirements apply to every future Codex task in this repository.

- Before implementation, read the complete request and review pending work. Publish
  a complete sequentially numbered checklist with dependencies, execution order and
  a clear completion criterion per task. Preserve earlier requirements; explain
  scope changes instead of silently removing, skipping or redefining tasks.
- Use `[ ]` Pending, `[~]` In progress, `[x]` Completed and `[!]` Blocked. Maintain
  the full checklist in the working plan. Preserve it across interruptions or
  context compaction using available planning mechanisms or temporary notes;
  avoid unnecessary permanent tracking files in the repository.
- Report progress visibly before implementation, when starting/completing a task,
  when blocked, before/after major validation stages, before commits and at final
  delivery. At meaningful checkpoints summarize completed, active, pending and
  blocked work; do not repeatedly print an unchanged full checklist.
- Use this concise format, adjusting counts and content to actual evidence:

  **Progress: 12/28 tasks completed (43%)**

  **Current task:** #13 — Improve Release Roles filter alignment

  **Next task:** #14 — Redesign Release Roles matrices

  **Blocked:** None

  **Validation:** Not started

- Count only fully completed tasks. Implementation alone is not completion when
  validation is required. Never invent results; distinguish implementation,
  automated validation and native/manual acceptance. Report dependency blockers
  promptly and reopen completed items if new evidence requires rework.
- Continue authorized independent work without requesting approval after each
  task. Keep updates concise and meaningful, without repetitive status messages
  when nothing has changed. Existing scope, safety and publication limits remain
  in force.
- The final report must reconcile completed/total counts with the full checklist,
  final statuses, partial/blocked work, executed validation, branch/commit state,
  remaining limitations and recommended next actions.

## Efficient Execution & Risk-Based Validation

Core principle: use the smallest sufficient validation scope during implementation,
followed by appropriate final regression validation. These rules apply to all tasks.

- **QUICK — implementation:** directly affected tests, relevant component/browser
  cases, targeted type/lint checks where supported, and necessary smoke tests.
  Avoid complete backend/browser suites.
- **STANDARD — completed logical phase:** affected modules and integration tests,
  type checking, and a production build when compiled assets need verification.
- **FULL — final implementation freeze:** complete backend and browser suites,
  production build, required static/security/documentation checks, and representative
  visual review. Normally run once after the planned scope is complete. High-risk
  shared infrastructure changes and release preparation may justify broader checks.

Before an expensive command, identify its purpose, affected inputs, equivalent prior
results, expected runtime and whether a targeted alternative suffices. Reuse results
only when relevant code, dependencies, configuration and environment are unchanged.
A failed full suite requires diagnosis and affected-test verification first, not an
automatic complete restart. Perform a final complete run when the remaining risk
justifies it. Never silently skip required coverage or weaken assertions.

Batch related edits and independent inspections/checks. Avoid repeated dependency
installs, builds, unchanged file reads, large log output, documentation rewrites and
screenshots of unchanged screens. During implementation capture affected screens at
representative widths/themes; final shared CSS/token/theme changes still require
both themes and required breakpoints. Investigate unexpected slowness rather than
repeating runs or imposing arbitrary cutoffs on legitimate tests.

Use the changed-area selection guide in [Testing](docs/development/TESTING.md).
Consider transitive dependencies and shared components, not filename matching alone;
when impact is uncertain, broaden validation. Preserve test isolation and meaningful
coverage. Do not increase browser workers without representative before/after
benchmarks and proof that backend/storage fixtures cannot race. Do not reuse a test
server with unknown state, assets or credentials. Review caches, artifact reuse and
job dependencies before changing CI; preserve required checks and trust boundaries.
Do not dispatch workflows to measure these changes without authorization.

Report Quick/Standard/Full scope, commands, results, reused evidence and limitations
accurately. Claim speed improvements only with comparable measurements. Keep visible
progress concise at meaningful task/validation/commit milestones; do not repeatedly
print unchanged checklists. Publication and pre-push safety rules remain in force.

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
