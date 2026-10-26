# UI consolidation — implementation and validation

> Historical evidence: applies to the source/phase recorded below, not later
> commits. Use the [current documentation index](../../README.md) for instructions.


## Comprehensive UI/UX refinement — 26 October 2026

Delivery preflight on 26 October 2026 confirmed clean `work` at `aaccce2` and
unchanged remote `work` at `e8e33d2`. The documentation restructuring and both UI
refinement commits are intentional descendants. The approved delivery retains the
standing `[skip ci]` instruction; no manual workflow or release is dispatched.

Baseline `2ba408908a7c090edd623daaa610c10023fe7b9b` and all prior commits are
preserved. Validated implementation commit:
`3661971ddaa9957808da5acb05fbfca251ea74d2` (commands executed on its working-tree
contents before commit). Implementation/test patch SHA-256:
`6d456f06624de17758975da4c6afcc62cd6c5067b199193b9d6ca32d5cc5cc4d`.
No new dependencies, deployment workflow changes, tags, releases or remote pushes.

### Requested areas and shared ownership

| Area | Delivered behavior |
| --- | --- |
| Dashboard | Four primary overview metrics; compact Access & Risk rows; integrated directory coverage; all three sources in secondary configuration. Existing counts/navigation retained. |
| Saved Filters | Shared equal-width Save as new/Clear action row, aligned fields, existing persistence/compatibility/focus behavior. |
| Single Roles | Contiguous full-row zebra surfaces, outer rounding only, reversible hover and transaction count beside module metadata. |
| Role header | Grouped descriptive information, responsive right-aligned exact identifier and existing compact back action. |
| Long identifiers | Shared wrap-safe identifiers; responsive descriptive/technical columns and small-window stacking; exact copying retained. |
| User Directory | Shared icon header; coherent primary grid, expired option beneath role and direction beneath sorting; individual chips and existing predicates retained. |
| Account Review | Equal-density grouped metrics; coherent search/decision/sort controls; bounded right-aligned clear; export moved beside result count. |
| Compare Users | Accessible swap beside title, grouped direction, consistent shared/A/B semantic colors, right-aligned export and unchanged direct interval/provenance evidence. |
| Role Lookup | Restored shared visible title/icon without changing catalogue searches or area filtering. |
| Release Roles | Shared header, stacked sort/direction, existing date controls inside the filter panel and Table/Matrix controls retained. |
| Matrix | Content-sized columns, prominent/sticky headers, bounded relative count intensity, keyboard scrolling/drilldown; no risk classification. |
| CSV previews | Shared local case-insensitive sample search and clear; full validation totals remain separate. Employee search uses the same SearchInput. |
| Source Health | Canonical StatusBadge variants and MetadataList's four full-width facts. Import, availability, snapshot, source check and error/warning remain distinct. |

PageHeader, SearchInput, RoleMetadata, StatusBadge/SourceBadge, FilterPanel,
ResultsToolbar, SavedFilters and ImportPreview are extended/reused. MetadataList
is the small new semantic display primitive. Real controls appear in the isolated
Component Library. Canonical CSS replaces superseded Single Roles/source badge
rules; no separate design system or speculative domain model is introduced.

### Final validation

| Executed command/check | Result |
| --- | --- |
| `.venv/bin/python -m unittest discover -s backend/tests -v` with portable PowerShell on PATH | **408 passed, 18.826 s**, no skips |
| `PATH=/workspace/sap-lens/.venv/bin:$PATH PLAYWRIGHT_EXECUTABLE_PATH=/usr/bin/chromium npm --prefix frontend run test:browser` | **248 passed together, 8.0 min**, one worker, no retries |
| `npm --prefix frontend ci --no-audit --no-fund` | Passed with locked dependencies |
| `npm --prefix frontend run check:types`, `npm --prefix frontend run build` | Passed; existing >500 kB chunk warning retained |
| `.venv/bin/python -m pip check` | Passed |
| Isolated `python -m pip_audit --path .venv/lib/python3.12/site-packages` | No known vulnerabilities in the installed Linux environment; writable workspace cache used |
| `npm --prefix frontend audit --omit=dev` | Zero production vulnerabilities |
| Full `npm --prefix frontend audit` | Three existing moderate development-chain advisories; no suppression or forced updates |
| `python scripts/check-docs.py` | 73 Markdown files, zero broken relative links/images/anchors; external URLs not fetched |
| `python scripts/check-workflows.py`, actionlint | Passed |
| `pwsh -NoProfile -File scripts/check-powershell.ps1` | Parser/static/service-helper tests passed; no SCM operations |
| `node scripts/sync-lucide-catalog.mjs --check` | 1,447 icons verified |
| Documentation and repository-privacy targeted regressions; Git whitespace checks | Passed |

Thirteen new browser cases cover eight theme/width combinations, direct long-role
and multi-interval/wildcard comparison with swap, bounded identity preview search,
small matrix keyboard drilldown, zebra/hover behavior and a synthetic 199-cell
matrix with high counts, empty cells and scrolling in both themes. Existing tests
were retained. Label/role selectors were migrated for SAP Overview, Descending
and the employee searchbox without dropping their assertions.

Earlier targeted failures exposed search-clear hit testing and superseded grid
styles; these were fixed. Screenshot review exposed a source-badge cascade and
stretched clear button, corrected through canonical components/styles. Interrupted
runs are not counted as passes. A preceding complete run had 247 passes and one
legacy textbox selector failure; that selector's full behavior passed targeted
recheck, followed by the final integrated **248-test pass** above.

### Visual review and privacy boundaries

Synthetic light/dark screenshots were captured at 375, 800, 1280 and 1600 pixels.
Representative Dashboard, directory/review, comparison, Role Details, matrix and
source-health/library images were reviewed. Sixty new screenshots supplement the
existing scenarios; full-suite PNGs are kept outside Git. Capture returns the
window to its origin so sticky navigation is not misleadingly stitched mid-page.
Large evidence tables/matrices intentionally scroll inside their named regions.

Preview search is deliberately bounded: catalogue samples at five rows and user
samples at 20, not arbitrary full-export browser loading. To investigate all
records, confirm import and use the relevant investigation page. User preview
names/emails are authenticated response-only evidence, never stored samples in
reports or diagnostic exports; regression tests assert the boundary. Import modes,
schemas, snapshots, matching, account decisions and SAP evidence calculations are
unchanged. No real employee/company data, credentials, private artifacts or new
branding were added; accepted historical P-01 remains unresolved and unchanged.

Native Windows/WebView2, packaged EXE, real systemd/reboot/recovery/UNC and physical
mobile/Safari/Firefox acceptance were not executed. Linux Chromium responsive
screenshots and mocked native exports do not establish those results. No Windows
build, GitHub Actions dispatch or release publication was performed.

## Final integrated validation and conditional delivery — 25.10.2026

Validated test/source checkpoint: `8e11ae7577e893379ddb8effa4ba4ca5d06dd527`.
The application implementation remains `005bf19`; this delivery changed two test
assumptions and clarified the lifecycle document's historical checkpoints.

| Check | Actual result |
| --- | --- |
| Complete browser suite | **235 passed together in 7.2 minutes**, one worker, retries disabled |
| Backend suite | **406 passed in 21.929 seconds**, portable PowerShell available |
| Frontend | Locked npm installation, TypeScript and production build passed |
| Dependencies | pip check passed; installed Python and production npm audits found no known vulnerabilities |
| Static/repository checks | Actionlint, PowerShell parsing/helper regressions, Lucide catalogue, whitespace and 63 Markdown link checks passed |
| Additional Compare Users QA | Six isolated scenarios: light/dark at 375/800/1280px; 223-character role, four validity states/intervals, wildcard patterns, exact copying, transaction provenance and no document overflow |

The first complete run passed 233/235 and caught two remaining test assumptions:
vertical metadata stacking and filling an already-selected Saved Filter without
opening its deliberately closed selector. `8e11ae7` checks the requested horizontal
layout/non-overlap and explicitly clicks the selector before searching. Both
focused cases passed, followed by the clean complete run above. No data/evidence,
classification, persistence or export assertion was removed to obtain a pass.
There were no application runtime changes in this final stabilization.

The complete suite captured responsive light/dark surfaces. Representative
comparison/evidence, navigation, source, role-detail and Saved Filter screenshots
were inspected. Synthetic screenshots/logs remain outside Git under
`/workspace/sap-lens-dev/delivery-visual-qa/`,
`/workspace/sap-lens-dev/delivery-compare-qa/` and `delivery-*.log`.
These are Chromium/Linux tests and reviewed captures, not native Windows or
physical mobile-browser certification.

The outgoing privacy review is recorded in [Privacy](../../architecture/PRIVACY.md). README LOGO
links and documentation targets resolved locally; no external download/release
availability is implied. The four deployment filenames and five target choices
(including All) match the canonical scripts/workflow. No CHANGELOG.md was added.
The lifecycle guide now distinguishes the initial pending list from later
implemented Docker/installer definitions and still-pending native acceptance.

Native Windows/WebView2, compiled installer/EXE/SCM, real systemd, reboot/recovery,
UNC and physical Safari/mobile acceptance remain pending. No Windows package,
release, tag, registry publication or manually dispatched Actions run was created.
Existing nonblocking warnings remain: three moderate npm development-chain
advisories and Vite's >500 kB chunk advisory. No dependency audit was suppressed.

The user's standing `[skip ci]` instruction applies to the final documentation
record/push; local results above are separate from GitHub Actions status. The
conditional push must recheck a clean `work`, remote ancestry and the live remote
SHA and use a normal non-force push. Existing history and accepted P-01 branding
handling are preserved.


## Current coordinated refinement — 25.10.2026

This section describes the current local batch; earlier sections below are
historical checkpoints, not certification of this source revision.

- Shared navigation containers now use one strip primitive, preserving main and
  secondary navigation landmarks, actual secondary links, tab roles, roving focus
  and associated panels. Component Library continues to use the real exports.
- Blurred/glow shadows are removed from cards, role selection, drawers, floating
  surfaces and shared controls. Crisp focus outlines and opaque bordered portal
  surfaces remain. No dependencies or theme/preset schemas changed.
- Dashboard retains its four primary metrics, uses compact secondary statistics,
  and retains coverage counts/progress, source health and existing drilldowns.
- Role Details uses a compact ghost back action, responsive identifier/header,
  smaller navigation/statistics spacing and horizontal single-role metadata where
  space permits. Zebra backgrounds apply to the row rather than an inner block.
- Saved Filter selection remains searchable and all schema/CRUD behavior is
  retained. Save and clear actions share a wrapping row in the compact popover.
- User Directory adds a catalogue identifier/description selector, preserving the
  existing single-role exact/pattern association rather than inventing multi-role
  AND/OR behavior. Individual role/group/search/expired/transaction chips and one
  panel reset preserve unrelated controls when an individual chip is removed.
- Account Review metrics are compact; sorting/direction/export are in its filter
  panel. Display capitalization changes do not alter enums, review decisions or
  account interpretation.
- Compare Users has exactly four columns and direct evidence, not counts or an
  evidence accordion. All distinct intervals, assigned identifiers, copy actions,
  groups, status and matching patterns remain inspectable. Transaction evidence
  now includes bounded assignment provenance alongside the unchanged explanatory
  role lists. Provenance is deduplicated across the result page. Further evidence
  pages preserve source-generation/date guards; arithmetic and exports remain
  unchanged. Wide evidence tables intentionally scroll inside their named region.
- Release date controls belong to the primary filter panel; optional group
  comparison has its own toolbar. Table/matrix codes are more prominent without
  changing counts, date bounds or drilldowns.
- Employee Directory health/diagnostics follow selection and import controls.
  Retained valid data is Loaded in success styling; failed replacement warnings
  are reported separately. No parser, snapshot or replacement semantics changed.

The earlier queued lifecycle, documentation-index and synthetic-example work is
preserved in separate commits. README LOGO links, platform guides, standalone
package instructions, offline link checks and repository guidance were aligned in
`62895c9`. Linked synthetic examples and real import/fresh-process recovery tests
were added in `3b923df`; they are not auto-loaded or packaged.

### Current validation

- Backend: 406 tests passed in 21.013 seconds, with the installed portable
  PowerShell available. Comparison provenance and source recovery are covered.
- TypeScript and production build passed; Vite retains its existing >500 kB chunk
  advisory. No warning suppression or dependency upgrade was used.
- Documentation checker: 63 Markdown files, no broken local targets/anchors.
  External URLs were not fetched. Actionlint and Lucide catalogue checks passed.
- Portable PowerShell parsing and isolated service-helper regressions passed.
  These did not install a Windows service or compile/run the desktop installer.
- Python installed-dependency audit and production npm audit found no known
  vulnerabilities. Full npm audit retains three moderate development-chain
  advisories (Tailwind/PostCSS); no forced major update or suppression.

Browser validation used one full run (235 scenarios): 227 passed in 7.6 minutes;
eight older visual assertions failed. Four required the former stacked single-role
layout; four required filled tab hover backgrounds. Updated assertions check the
requested alignment, non-overlap, containment and persistent active underline.
A 33-case affected/visual run passed 27 and exposed six remaining cases: the four
long-description row cases, an outside-click target covered by the upward date
popover, and Saved Filters autofocus opening its selector over Load. The row grid
and selector focus behavior were corrected; the outside-click test now verifies
an actually uncovered navbar point without force-clicking. All 14 final affected
checks passed in 37.1 seconds, including keyboard focus, load/CRUD, direct evidence
and six light/dark comparison captures. The four tab-hover cases passed in the
33-case run. No second complete browser suite was executed.

Representative screenshots were inspected in both themes at 375, 800 and 1280 px.
They show crisp focus outlines, retained long evidence, scroll-contained tables,
responsive navigation and filters. Synthetic captures are retained outside Git at
`/workspace/sap-lens-dev/ui-refinement-final-qa/`. These are reviewed screenshots
and geometry assertions, not cross-platform pixel-golden certification.

Exact local commands included `npm --prefix frontend ci --no-audit --no-fund`,
`npm --prefix frontend run check:types`, `npm --prefix frontend run build`,
`python -m unittest discover -s backend/tests -v`, `python -m pip check`, installed
Python `pip_audit --path`, `npm --prefix frontend audit --omit=dev`, full npm audit,
`python scripts/check-docs.py`, pinned actionlint, `node
scripts/sync-lucide-catalog.mjs --check`, `pwsh -NoProfile -File
scripts/check-powershell.ps1`, and `git diff --check`. Browser commands used the
prepared Python environment and `PLAYWRIGHT_EXECUTABLE_PATH=/usr/bin/chromium`.
Reports/logs are retained under `/workspace/sap-lens-dev/refinement-*`.

The final visual-only set passed 10/10 in 43.7 seconds. The final Saved Filters
set passed 9/9 in 21.2 seconds, including six theme/viewport captures. Its internal
Save/Clear row is shared across callers; the component hides its external Clear
while open. All known browser failures from the complete/targeted runs above have
passing affected-case results. There is no claim of a second green full-suite run.
Implementation commit: `005bf19` (backend/frontend/tests only).

### Current changed-file inventory

- `backend/routers/user_comparison.py`
- `backend/tests/test_investigation_tools.py`
- `backend/tests/test_local_build.py`
- `docs/architecture/COMPONENTS.md`
- `docs/architecture/DESIGN_SYSTEM.md`
- `docs/features/FILTERS.md`
- `docs/archive/validation/UI_CONSOLIDATION_VALIDATION.md`
- `docs/features/COMPARE_USERS.md`
- `frontend/src/components/Access/AccountReview.tsx`
- `frontend/src/components/Access/ReleaseRoles.tsx`
- `frontend/src/components/Access/UserAccess.tsx`
- `frontend/src/components/Access/UserComparison.tsx`
- `frontend/src/components/Dashboard.tsx`
- `frontend/src/components/Layout/AppLayout.tsx`
- `frontend/src/components/RoleComparison/ComparisonView.tsx`
- `frontend/src/components/RoleDetail/RoleDetailPanel.tsx`
- `frontend/src/components/RoleList/RoleCard.tsx`
- `frontend/src/components/RoleList/RoleList.tsx`
- `frontend/src/components/Settings/EmployeeDirectory.tsx`
- `frontend/src/components/Shared/Combobox.tsx`
- `frontend/src/components/Shared/Navigation.tsx`
- `frontend/src/components/Shared/SavedFilters.tsx`
- `frontend/src/components/Shared/SourceBadge.tsx`
- `frontend/src/index.css`
- `frontend/src/styles/components.css`
- `frontend/src/styles/tokens.css`
- `frontend/tests/access-investigation.spec.ts`
- `frontend/tests/account-review-refinement.spec.ts`
- `frontend/tests/dashboard-user-transactions.spec.ts`
- `frontend/tests/design-system.spec.ts`
- `frontend/tests/investigation-tools.spec.ts`
- `frontend/tests/investigation-ux.spec.ts`
- `frontend/tests/live-filters-polish.spec.ts`

Native Windows/WebView2, compiled EXE/installer, SCM, real systemd, reboot/recovery,
UNC and physical mobile/Safari acceptance remain unexecuted here. Earlier Docker
and Linux user-mode lifecycle results apply to their documented source fixtures,
not a newly built current-source production distribution. Nothing in this batch
was pushed, published or remotely dispatched. P-01 remains separately unresolved;
no history was rewritten.

---


This document describes the UI-only consolidation checkpoint `246ef42`. The subsequent CSV lifecycle batch and final frozen stabilization are documented in [the final validation report](STABILIZATION_VALIDATION.md); its results supersede the intermediate execution results below.

## Baseline and boundaries

Started from clean `work` at `4918bcc3657a463c8df7b593066479fe06574e54`, equal to fetched `origin/work`. Read AGENTS.md and inspected the existing shared controls, theme derivation, router, layout, source forms, tables, filters and browser suites before changing code. No reset, rebase, discarded work or new worktree.

This is an incremental consolidation of React/TypeScript/Vite/Tailwind/Lucide. No framework/dependency additions. Backend APIs, source parsing, classification, comparison calculations, saved-filter storage, review evidence, account-state interpretation, Windows packaging/versioning, branding assets and protected README remain unchanged.

## Architecture and migration

- Existing working selectors, localized dates, identifiers, notifications, module registry and pagination remain canonical. New small primitives fill genuine gaps; the [component inventory](../../architecture/COMPONENTS.md) documents usages, variants, accessibility and specialized components intentionally retained.
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

- `docs/getting-started/CONFIGURATION.md`
- `docs/archive/validation/UI_CONSOLIDATION_VALIDATION.md`
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
- `docs/architecture/COMPONENTS.md`
- `docs/architecture/DESIGN_SYSTEM.md`
- `docs/architecture/NAVIGATION.md`
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

## Compact evidence and desktop/browser connectivity — 26 October 2026

Baseline: clean `work` at `be7be626d9247255f3ec6049a8b1372e2321bb32`.
This follow-up preserves the preceding implementation and changes no dependencies,
CSV schemas, assignment calculations, matching rules or deployment workflows.

| Request | Implemented change |
|---|---|
| 1 | Shared Popover remeasures dynamic contents, constrains only to available viewport; Saved Filter actions have a token-sized gap |
| 2 | Single-role zebra surfaces remain invariant on hover; toggle/copy retain independent interaction and focus |
| 3 | Canonical role identifiers stay single-line, complete and copyable, with contained keyboard/horizontal scrolling |
| 4 | RoleMetadata uses backend classification only; description prefixes cannot invent an area; BC parent and unclassified child evidence remain distinct |
| 5 | TransactionCount consolidates existing lightning/count presentation across catalogue cards, single roles, comparison and the real Component Library |
| 6 | Compare Roles identifiers retain canonical area colors; exclusive counters have explicit spacing; calculations unchanged |
| 7 | Desktop User Directory has five primary columns, plain expired checkbox below role and Descending below sorting; Clear stays bottom-right |
| 8 | Account Review uses five filter columns and three readable metric groups; existing counts/actions preserved |
| 9 | Compare Users Saved Filters sits above the filter panel; the panel has its own shared Clear action |
| 10 | Shared / A-only / B-only consistently use green / blue / red theme tokens and explicit labels |
| 11 | Evidence shows exact identifier, interactive assignment status and source group; status popover exposes exact dates/status, with Unknown distinct from 31.12.9999 |
| 12 | Comparison summary counters size to content and wrap |
| 13 | PR/PO matrices are content-sized, side-by-side when space allows, stacked at tablet width, independently scrollable |
| 14 | Owned desktop listener supports plain 127.0.0.1 and localhost browser roots through a guarded per-launch capability handoff; no second backend |

### Connectivity evidence and trust boundary

The failure was capability delivery, not a missing frontend server: WebView2 alone
received the launch fragment, and the localhost alias was absent from allowed
origins. The desktop now opts into an exact selected-port/loopback-peer root
handoff. Only a top-level non-cross-site document navigation receives non-cacheable
HTML with a fresh CSP nonce; cross-site/frame/resource requests do not obtain the
capability. API reads/writes still require it. Server hosting behavior is unchanged.

Executed real Chromium against the actual ManagedBackend HTTP runtime on Linux:
both plain roots loaded/reloaded, authenticated APIs returned 200, unguarded APIs
returned 403, and a synthetic configuration update through one origin was visible
through the other. The owned runtime shut down cleanly. This did not initialize
Windows/WebView2 and is not native desktop acceptance. Existing desktop lifecycle
tests exercise real HTTP/readiness/port-conflict/shutdown behavior with GUI/Windows
boundaries mocked. Retry connection already performs a real configuration refetch.

### Validation procedure and limits

Logs are outside Git at `/workspace/sap-lens-dev/connectivity-*.log`; synthetic
screenshots are under the ignored `frontend/test-results/` and a retained external
`/workspace/sap-lens-dev/connectivity-visual/` directory. Use current canonical
[desktop](../../architecture/DESKTOP.md), [role](../../features/ROLE_LOOKUP.md),
[comparison](../../features/COMPARE_USERS.md) and
[component](../../architecture/COMPONENTS.md) documentation for behavior.

Executed results for this follow-up:

- `npm_config_cache=/workspace/.cache/npm npm --prefix frontend ci --no-audit --no-fund`: passed; lockfile unchanged. The first attempt used an unwritable default npm cache; retrying with a workspace cache succeeded.
- `npm --prefix frontend run check:types` and `npm --prefix frontend run build`: passed. Existing large-chunk build advisory remains.
- `.venv/bin/python -m unittest discover -s backend/tests -v`: 412 run, 410 passed and two PowerShell availability skips. With the prepared portable PowerShell on PATH and writable XDG directories, the complete `test_local_build.py` group reran: 17 passed, including both skipped checks.
- Focused browser changes: six final targeted regressions passed. The first full run found two obsolete four-column expectations (248 passed); these were updated to the required five-column contract. Screenshot review additionally bounded comparison columns so long identifiers cannot displace evidence.
- Final frozen implementation: `PATH=/workspace/sap-lens/.venv/bin:$PATH PLAYWRIGHT_EXECUTABLE_PATH=/usr/bin/chromium npm --prefix frontend run test:browser`: **250 passed together**, 8.3 minutes, one worker, no retries.
- `python -m pip check`, installed-environment `pip_audit` and `npm audit --omit=dev`: passed, no production vulnerabilities found. Full npm audit reports three moderate development advisories in the existing Tailwind/PostCSS chain; no dependency upgrades or suppressions were introduced.
- `python scripts/check-docs.py`: 73 Markdown files, zero failures. `python scripts/check-workflows.py`, actionlint, PowerShell syntax/static/service-helper checks, Lucide catalogue check (1447 icons), and `git diff --check`: passed.
- Captured light/dark layouts at 375/800/1280/1600 pixels; inspected representative directory/review/filter popovers, comparison evidence, role details and matrices. Geometry assertions cover action spacing, contained overflow, keyboard focus, single-line identifiers and PR/PO placement. Screenshots are review artifacts, not pixel-golden comparisons.
- New content review found only synthetic/reserved-domain fixtures, generic documentation and code; no new private assets, credentials, company identifiers or source exports. Accepted historical branding remains unchanged.

Native Windows/WebView2 startup, browser/real WebView simultaneous state, native
clipboard/dialogs, packaged EXE and UNC remain untested here. No Windows build,
push, workflow dispatch, tag, release or package publication was performed.

Final narrow-screen follow-up: removed the expired-checkbox container at every
breakpoint, not just desktop. Production build and the light-800/dark-375 shared
layout regressions passed (2/2); no functional changes or additional full run.

## Refinement Round 2 — tasks 15–29

Continued from locally preserved `17d48ec`, `be5a3ae` and `c2dd2b5`; no push.

- 15–16: explicit User Details AND/OR mode, shared backend role-set filtering and
  matching export scope; compact assignment count/warnings, with provenance in rows.
- 17–18: directory matching modal and consistent status labels, preserving actual
  candidate evidence and source navigation.
- 19–21: canonical three-source status summary, interactive feature pill with pending
  preference versus persisted operational status, shared technical-source modal.
- 22–23,25–26: evidence-backed dashboard distributions/review population/freshness,
  single coverage indicator, shared icons, subtle interactions and three/two/one grids.
- 24,28: review modal presents findings before the decision; protected drafts, current
  evidence checks, backward-compatible annotation history, order-independent new
  fingerprints and removed/reappearing-account handling. Review storage failure
  cannot erase annotations or block independent CSV loading.
- 27,29: four-column change table, readable records and exact copyable identifiers,
  actual retained before/after details in the shared modal, consistent action icons.

Targeted validation before beginning task 30:

- User Access backend: 43 passed; filter backend: 17 passed; Account Review backend:
  23 passed (history, format-1 migration, restart, ordering, changed identity/assignment/
  AD evidence, disappearance/reappearance, corrupt storage and permission failures).
- CSV lifecycle backend: 22 passed. Lifecycle browser: 10 passed, including native-save
  bridge mocks, complete replacement, failed refresh retention and both themes at
  375/800/1280. New Round 2 browser suite: 14 passed, with source/review/matching
  modals and dashboard geometry at 375/800/1280/1600 in both themes.
- Relevant existing browser groups: 43 passed; four legacy OR visual cases were then
  updated to explicitly choose OR under the new AND default and all four passed.
  Obsolete inline-details/coverage selectors were migrated to the actual modals and
  single coverage control, retaining evidence, date, export and focus assertions.
- TypeScript/production build, whitespace and 73-document link checks passed.
  Representative screenshots were inspected and retained outside Git in
  `/workspace/sap-lens-dev/round2-visual/`. Native Windows/WebView2 remains untested.

Tasks 30–31 remain separate follow-ups; final combined regression/audits follow those
implementations. No comprehensive browser suite was repeated for each UI edit.

## Task 30 — first-open assignment date positioning

Reproduced before the fix by holding a real directory-match response, opening the
date filter once, then releasing the response. Profile growth moved the button
without scroll/resize or popup-size changes, leaving stale portal coordinates.
The regression failed after that response while its initial placement passed.

Shared event-driven anchor-layout observation now covers surrounding content and
ancestor sizes/styles in Popover, Combobox and NorwegianDateInput. Placement is
viewport-clamped; initial popup focus avoids unsolicited page scrolling. No timer,
positioning delay, remount workaround or dependency was introduced.

Production build/type checking passed. Ten targeted browser tests passed: first
and subsequent opens, delayed real profile enrichment, no profile overlap when
space is available, viewport resizing/scroll, Escape/focus, advanced Apply and
Clear/Cancel semantics at 375/800/1280/1600 in both themes; shared dropdown/calendar
layout-shift checks and the existing combobox keyboard regression also passed.
Native Windows/WebView2 remains pending. No push or workflow dispatch.
