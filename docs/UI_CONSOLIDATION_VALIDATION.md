# UI consolidation — implementation and validation

## Baseline and boundaries

Started from clean `work` at `4918bcc3657a463c8df7b593066479fe06574e54`, equal to fetched `origin/work`. Read AGENTS.md and inspected the existing shared controls, theme derivation, router, layout, source forms, tables, filters and browser suites before changing code. No reset, rebase, discarded work or new worktree.

This is an incremental consolidation of React/TypeScript/Vite/Tailwind/Lucide. No framework/dependency additions. Backend APIs, source parsing, classification, comparison calculations, saved-filter storage, review evidence, account-state interpretation, Windows packaging/versioning, branding assets and protected README remain unchanged.

## Architecture and migration

- Existing working selectors, localized dates, identifiers, notifications, module registry and pagination remain canonical. New small primitives fill genuine gaps; the [component inventory](COMPONENT_LIBRARY.md) documents usages, variants, accessibility and specialized components intentionally retained.
- Default palettes and dimensions moved to `styles/tokens.css`; current runtime theme property names and validation remain compatible. Shared action/control/table styling has one owner in `styles/components.css`. Legacy Settings action classes are compatibility adapters. Removed duplicate 40/42px Settings rules, table padding/font overrides, badge base/tone duplicates and obsolete navigation-label hiding.
- Buttons, icon utilities, pressed button groups, controls/fields, toggles, chips, shared status presentation, navigation/tabs, popovers and lightweight table/layout wrappers are real shared components. No generic table/query engine or duplicate multi-select framework was introduced.
- User Access secondary links have real hash destinations, underline current state, query preservation, direct loading and Back/Forward. Account Review investigation controls now retain their bounded state across subnavigation. Existing primary paths and bootstrap history boundary remain supported.
- User Details role categories and Data Sources use one tab keyboard implementation; source tab/panel IDs remain stable. Release Table/Matrix and transaction AND/OR remain clearly labeled pressed filter/view controls.
- Navbar utilities are labeled icon buttons with focus tooltips, loading/disabled behavior and a refresh request guard. Removed the navbar timestamp and redundant frontend clock. Actual metadata remains on Dashboard and Data Sources.
- All five Saved Filters callers use one compact portal. Persistence/schema/CRUD are unchanged. Pages with their own Clear action avoid a duplicate outside action; clearing is neutral, deletion remains explicitly destructive/confirmed.
- User Comparison has paired selector/identity panels, compact summary counts, aligned filters, a discoverable evidence disclosure, structured exact-role/interval evidence, shared table and export button. No comparison arithmetic changed.
- Component Library is a lazy Settings page, built from real components. Its synthetic data and instance-keyed memory filter adapter never write production state; the settings save footer is hidden on this page.

## Regression corrections made during implementation

Regression tests identified duplicated Clear actions; they were consolidated rather than scoping tests around the duplicate. Larger copy targets initially overlapped the existing two-second overlay; its inset now derives from the target-size token and existing exact timing/geometry assertions remain. Lock-state appearance was preserved while sharing badge rendering. Form labels are associated with controls without help text contaminating names. Shared tab hover/underline assertions replace obsolete filled-button assertions, retaining exact icon/label alignment and focus coverage.

## Validation

Executed locally on Linux with Node 24.19.0, Python 3.12.14 and Chromium 154:

- `npm --cache /workspace/.npm-cache --prefix frontend ci` — 143 packages installed; lockfile unchanged.
- `npm --prefix frontend run check:types` — passed.
- `npm --prefix frontend run build` — passed; Vite compilation 1.45 seconds.
- `.venv/bin/python -W error::DeprecationWarning -m unittest discover -s backend/tests -v` — 301 passed, zero skipped, 17.000 seconds.
- `.venv/bin/python -m pip check` — passed.
- Dedicated `pip_audit` environment with runtime/dev/build requirement inputs — no known vulnerabilities in Linux-resolved dependencies. Windows-only installed packages were not audited on a native Windows interpreter.
- `npm --prefix frontend audit --omit=dev` — zero production advisories.
- Workflow checker, actionlint, portable PowerShell parsing/static checks, Lucide catalog verification and documentation-link checks — passed.
- `git diff --check` — passed.
- Full `npm --prefix frontend run test:browser` with the prepared virtualenv on PATH and `PLAYWRIGHT_EXECUTABLE_PATH=/usr/bin/chromium` — 207 passed in 6.2 minutes. A further frozen-source repeat is recorded at the consolidation checkpoint.

Browser tests use an isolated production-asset server with synthetic data; no real SAP or employee exports are required.

## Visual QA

The new design-system browser suite captures navbar/secondary navigation, paired comparison panels, saved-filter popovers and Component Library in light/dark at 375, 800 and 1280 px. Existing suites continue to capture Dashboard, role comparison, user profile/role tabs, release views, sources, settings, diagnostics, long identifiers and empty/error states.

Reviewed the actual light/dark comparison, saved-filter and Component Library captures at desktop, tablet and mobile widths. Checked visible destination labels, source-tab wrapping, form alignment, focused controls, compact role evidence and bounded popovers. Captures are retained outside Git under `/workspace/sap-lens-dev/design-system-qa/`.

Reusable visual contracts check equal 42px default controls, viewport-bounded popovers, no document overflow, visible primary destination labels, keyboard focus and exact overlay timing. These complement screenshots; they are not cross-platform pixel goldens. Tables intentionally scroll inside named focusable regions on small screens.

## Remaining limitations

No native Windows/WebView2, real UNC share, native save dialog, packaged EXE build or newly built PE/archive was tested in this Linux environment. Existing synthetic verifier/privacy/lifecycle tests remain part of backend validation. Portable PowerShell parsing is not native Windows execution. Production dependency audits and Windows-marked dependency resolution are reported separately.

No runtime SAP processing, configuration migrations, persistence layer or package format changed. Native visual QA remains recommended for a future authorized Windows build. No workflow dispatch, tags, signing changes, releases or repository settings changes are part of this task.

Known full npm audit findings are the existing three moderate development-chain entries (`postcss-selector-parser`, `postcss-nested`, `tailwindcss`), with no production JavaScript advisories. No broad updates or suppressions. Node's NO_COLOR/FORCE_COLOR test-environment warning remains visible. CI uses `[skip ci]` under the standing explicit instruction until further notice; GitHub status is verified separately from local results.

## Changed files

The consolidation changes the frontend component/layout/state/style files and their browser tests, plus four new design/navigation/validation documents and the Configuration guide link. The exact checkpoint inventory follows:

- `docs/CONFIGURATION.md`
- `docs/UI_CONSOLIDATION_VALIDATION.md`
- `frontend/src/App.tsx`
- `frontend/src/components/Access/AccountReview.tsx`
- `frontend/src/components/Access/ReleaseRoles.tsx`
- `frontend/src/components/Access/Shared.tsx`
- `frontend/src/components/Access/UserAccess.tsx`
- `frontend/src/components/Access/UserComparison.tsx`
- `frontend/src/components/Dashboard.tsx`
- `frontend/src/components/Layout/AppLayout.tsx`
- `frontend/src/components/RoleList/RoleList.tsx`
- `frontend/src/components/Settings/DataHealth.tsx`
- `frontend/src/components/Settings/Diagnostics.tsx`
- `frontend/src/components/Settings/EmployeeDirectory.tsx`
- `frontend/src/components/Settings/ImportPresets.tsx`
- `frontend/src/components/Settings/ModuleEditor.tsx`
- `frontend/src/components/Settings/SettingsView.tsx`
- `frontend/src/components/Settings/ThemeEditor.tsx`
- `frontend/src/components/Shared/AccountStatus.tsx`
- `frontend/src/components/Shared/AssignmentDateFilters.tsx`
- `frontend/src/components/Shared/ClearFilterButton.tsx`
- `frontend/src/components/Shared/Combobox.tsx`
- `frontend/src/components/Shared/InvestigationNavigation.tsx`
- `frontend/src/components/Shared/SavedFilters.tsx`
- `frontend/src/components/Shared/TransactionFilter.tsx`
- `frontend/src/hooks/useViewHistory.tsx`
- `frontend/src/index.css`
- `frontend/src/main.tsx`
- `frontend/tailwind.config.ts`
- `frontend/tests/access-investigation.spec.ts`
- `frontend/tests/account-review-refinement.spec.ts`
- `frontend/tests/consolidated-role-ui.spec.ts`
- `frontend/tests/desktop.spec.ts`
- `frontend/tests/global-navigation.spec.ts`
- `frontend/tests/investigation-filter-refinement.spec.ts`
- `frontend/tests/investigation-tools.spec.ts`
- `frontend/tests/investigation-ux.spec.ts`
- `frontend/tests/live-filters-polish.spec.ts`
- `frontend/tests/navigation-modules.spec.ts`
- `frontend/tests/user-role-export.spec.ts`
- `docs/COMPONENT_LIBRARY.md`
- `docs/DESIGN_SYSTEM.md`
- `docs/NAVIGATION_PATTERNS.md`
- `frontend/src/components/Settings/ComponentLibrary.tsx`
- `frontend/src/components/Shared/Button.tsx`
- `frontend/src/components/Shared/Controls.tsx`
- `frontend/src/components/Shared/FilterChip.tsx`
- `frontend/src/components/Shared/Navigation.tsx`
- `frontend/src/components/Shared/Popover.tsx`
- `frontend/src/components/Shared/Presentation.tsx`
- `frontend/src/components/Shared/SAPUserSelector.tsx`
- `frontend/src/styles/components.css`
- `frontend/src/styles/tokens.css`
- `frontend/tests/design-system.spec.ts`
