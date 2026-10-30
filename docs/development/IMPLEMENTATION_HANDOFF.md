# Implementation handoff

Status of the UI/UX refinement, the SoD bulk-review additions and the Role Assignment Review corrections on branch `work`.
Canonical behavior lives in the feature guides ([SoD](../features/SOD.md), [Release Roles](../features/RELEASE_ROLES.md),
[Account Review](../features/ACCOUNT_REVIEW.md), [component APIs](../architecture/COMPONENTS.md)); this page records what was
verified and what was not.

## Completed phases

| Phase | Result |
| --- | --- |
| 0. Independent assignment decisions | Quick Keep/Remove/Investigate requests run one after another, read the revision of the previous save, retry once after a revision conflict and track busy state per assignment. Backend and browser regression tests cover several decisions per user, switching, reload, history attribution and bulk runs. The earlier single-selection behavior could not be reproduced in the committed build; the concurrency window was closed and tests added. |
| 1. Investigate as a decision | `Investigate` is a first-class, non-final assignment decision (history, filters, reports, remediation rows). Tracked actions stay separate, are optional (`track_action`) and never duplicated. Historical investigation actions are not treated as decisions. |
| 2. Review queue | Assignments tab defaults to *Needs attention*; sidebar choices Pending review, Under investigation, Reviewed, All; progress strip; saved-filter support; Reset restores the default. Filtering is per assignment. |
| 3. Individual and bulk consistency | Bulk runs never touch unrelated decisions; completed Keep/Remove need explicit replacement, Investigate and Outdated do not; CSV adds `ASSIGNMENT_ID` and `ROLE_SUFFIX`. |
| 4. Verification and fixes | Narrow-row wrapping of role entry actions, keyboard coverage, spec race fixes. |
| 5. Validation | See below. |

## Requirement coverage (original specification)

Item numbers follow the phase headings of the original specification (5 + 6 + 3 + 10 + 6 numbered items, plus the shared
standards and the Phase 6 regression). The original 36-point numbering was not retained in this repository.

| Item | Status | Location | Evidence / remaining work |
| --- | --- | --- | --- |
| Shared standards (role line layout, one badge, wrapping identifiers, circular actions, no color-only status) | Complete | `Shared/RoleEntry`, `RoleIdentifier`, `IdPill`, `components.css` | Browser specs, screenshots at 375 to 1600 px |
| 1.1 Role components consolidated | Complete | `RoleEntry` in Role Lookup, Single Roles, Package, Comparison, SoD lists | Release Roles shows the identifier only (no catalogue evidence exists for release roles) |
| 1.2 Navigation, tabs, focus | Complete | `Shared/Navigation`, `InvestigationNavigation` | `ui-polish-actions`, `navigation-a11y` specs |
| 1.3 Table standards | Partial | `.access-table` rules, `DataTable` | Zebra, sticky, density, pagination sizes applied; empty states not audited for every table |
| 1.4 Filter sidebar and Clear all | Partial | `FilterLayout`, `SodFilters` | Complete for sidebar views; not audited whether every search-only view avoids a sidebar |
| 1.5 Component Library parity | Partial | `Settings/ComponentLibrary` | Production components used, duplicate navigation removed, bulk toolbar, page size and action menu demos added; scrollbar spacing, T-code sizing and popover details were not individually verified |
| 2.1 to 2.6 Dashboard, Role Lookup, cards, Single Roles, Access Package, Release Roles | Complete | `Dashboard`, `RoleList`, `ComparisonView`, `AccessPackagePanel`, `ReleaseRoles` | `release-roles`, `access-package`, layout specs; Release Table paged 10/20/50/100; Matrix has no package controls |
| 3.1 Account Review tiles | Complete | `AccountReview`, `FilterTile` | Tiles filter the list; chips removable |
| 3.2 Review dialog sections | Complete | `AccountReview` | Position change time stays unknown by design |
| 3.3 User Comparison | Complete | `UserComparison`, `InvestigationNavigation` | Role column, one-line SAP User Group, bordered return controls |
| 4.1, 4.2 Overview, compact summaries | Complete | `SodOverview`, `.sod-tiles` | Three equal sections verified visually |
| 4.3 Matrices | Complete | `SodMatrices`, `IdPill` | Page sizes, sticky header and column, icon-distinguished risk and activity pills |
| 4.4, 4.5 Explorer | Complete | `SodExplorer` | Risks listed before activities; shared role entry |
| 4.6 Evidence dialog | Complete | `SodConflicts` | Trace header, technical provenance in a disclosure |
| 4.7 Role Assignment Review | Complete | `SodInvestigation` | Icon decisions Keep, Investigate, Remove; persisted before shown |
| 4.8 Remediation | Complete | `SodRemediation` | Parent rows per user and role, expandable activity rows; no dedicated new spec beyond `sod-governance` |
| 4.9 Period action menu | Partial | `SodPeriods` | Restyled and separated destructive action; collision handling relies on `Popover`; no new dedicated test |
| 4.10 Reports | Complete | `sod_reports.py` | Unchanged apart from Investigate counts |
| 5.1 to 5.5 Settings | Complete | `ThemeEditor`, `SodRiskSettings`, `EmployeeDirectory`, `ScheduledRefresh`, `DataHealth` | Four color controls per row, search only, "Configure source", schedule layout, compact health cards |
| 5.6 Library consistency | Partial | `ComponentLibrary` | See 1.5 |
| 6 Final regression and visual QA | Partial | this page | See validation |

## Additional requirements

| Requirement | Status | Evidence |
| --- | --- | --- |
| Exact role suffix filtering on the actual assigned role (OR within, AND between) | Complete | `test_sod_bulk_review` (suffix tokens CDK, EMS, ES2, ENO, ESH, ENP, XCDK trap), browser spec |
| Multi-select dropdowns (open while toggling, search keeps selections, Select all with scope, Clear, keyboard) | Complete | `sod-bulk-review.spec.ts` |
| Bulk selection (row, page, all matching, explicit stable identifiers) | Complete | browser and backend tests |
| Batch Keep, Recommend removal, Investigate with confirmation, replacement protection, history, partial failures | Complete | backend per-assignment results; partial failures in the browser use a mocked response |
| Toolbar behavior and responsiveness | Complete | specs at 1280, 800 and 375 px |
| No SAP write-back or source modification | Complete | source file hashes unchanged in the browser spec |
| Role Assignment Review corrections (Phases 0 to 3) | Complete | `sod-assignment-decisions.spec.ts`, `test_sod_bulk_review` |

## Consolidated refinement (second specification)

| Area | Status | Notes |
| --- | --- | --- |
| 1.1 Sidebar Clear | Complete | Compact "Clear" with the filter-reset icon in the sidebar header, aligned with Close; toolbar twins removed (Role Lookup repeats it only while the sidebar is hidden) |
| 1.2 Shared multi-select | Complete | `MultiSelectFilter`: open while toggling, checkboxes, search, Select all (scoped), Clear selection, chips, keyboard; used for SAP User Group, roles, roles to lack, Release Area, Group and Strategy, and the SoD scope fields |
| 1.3 Active states | Complete | Selected, pressed and active states use the primary action color (`--accent`); module chips and the segmented control no longer use module or secondary colors; module badge hover ring removed |
| 1.4 Capitalization | Partial | Sentence case applied to inconsistent table headers and sort labels; main navigation and feature names keep their established Title Case |
| 1.5 Codeblocks and pills | Complete | Status pills min height 1.75 rem with centered content; Risk IDs use the risk pill (also in Role conflicts); usernames and roles are codeblocks in the SoD tables |
| 2.1 Role cards | Complete | Description centered against the module badge; selected module filters use the primary color |
| 2.2 Group and role multi-select | Complete | `groups` and `roles` on the user directory API (OR within, AND between); Missing ANY and ALL, transaction AND/OR and exclusion untouched |
| 2.3, 2.4 Access Package | Complete | Header Clear package with confirmation (no footer duplicate), footer shows the valid/invalid summary, copy and export; Clear selection (comparison) never touches the package |
| 3.1, 3.2 Account Review and Compare users | Complete | Shared sidebar with Saved Filters and Clear; sort and export in the toolbar; the same SAP user cannot be on both sides |
| 3.3 Release Roles users | Complete | Users count opens a panel (codeblock, name, SAP User Group, status and validity, user details, export); Release Strategy is multi-select |
| 4.1, 4.2 Overview | Complete | Heatmap controls on one wrapping row; compact empty review period card |
| 4.3 Tiles | Complete | Filter tiles are buttons with primary active state, toggle, combine and Reset tile filters; informational tiles stay flat |
| 4.4 to 4.7 Matrices and Access Explorer | Complete | Multi-select SoD filters (backend lists for risks, activities, groups, roles, transactions, areas, criticalities, usernames, suffixes); simplified Assignments and Roles tables with default active scope; Role conflicts risk pill |
| 5.1 Reviewer session | Complete | Remembered for the session, reused by quick decisions, forms, bulk review and report preparation; changeable |
| 5.2, 5.3 Assignment review rows and batch | Complete | Compact rows with Keep, Investigate, Remove icons and expand; Select all visible; batch confirmation by checkbox |
| 5.4 Activity review | Partial | Existing compact rows kept; no further change |
| 5.5 Work queue | Complete | Username codeblocks, tile filters, icon action |
| 5.6 Review periods | Complete | Icons in the menu, trigger the same height as Open |
| 5.7 Reports | Complete | Document details expanded by default |

The follow-up [UI/UX gap audit](UI_UX_GAP_AUDIT.md) converted the Account Review finding, classification and decision filters, the Release SAP User Group filter and the Compare users SAP area filter to multi-select, made the Release username and role name searches multi-value, and made Activity Review rows compact and expandable. Still single-choice: Release PR/PO and assignment status, Compare users validity and section.

## KPI standardization and UI refinement (fourth specification)

Verified against the code and behavior, not the commit messages. Evidence names the files and the specs that exercise the behavior; `kpi-standard` is the new shared-component spec.

| Requirement | Status | Evidence | Notes |
| --- | --- | --- | --- |
| 1.1 Shared KPI component (compact and expanded, label, value, icon, note, progress, buttons with active, hover, focus, disabled, themes, responsive) | Implemented | `Shared/Kpi.tsx`, `styles/components.css`, `kpi-standard` | `FilterTile` and `MetricTile` wrap it; SoD tiles, Account Review, Dashboard and Overview use it. Informational KPIs are groups, interactive ones real buttons that keep keyboard focus while filtering |
| 1.1 AND between dimensions, OR within one | Implemented | `AccountReview` tile toggling, `account-review-refinement` | Finding KPIs join with OR; the classification KPI adds AND |
| 1.2 Button consistency: Compare users, Review and Edit icons, Investigate preserved | Implemented | `UserAccess`, `AccountReview`, `SodRiskSettings`, `sod-catalogue`, `position-changes` | Lucide icons throughout |
| 1.2 Transaction count as an actionable button | Implemented | `SodRiskSettings` (Activities table), `sod-catalogue` | Other tables show transaction counts that do not open details |
| 1.2 Equal heights beside each other | Partial | Release toolbar, risk configuration, source health (geometry specs) | Checked on the affected screens, not audited on every page |
| 1.3 Multi-select toolbar: Select all, Clear, Close as bordered buttons in one row | Implemented | `MultiSelectFilter`, `kpi-standard`, `sod-bulk-review` | Popup minimum width 300 px; wraps only on very narrow screens |
| 1.4 Full-width Saved filters and Assignment date filters in sidebars | Implemented | `styles/components.css`, `kpi-standard` | |
| 1.5 One chevron disclosure pattern | Partial | Global `details > summary` style, `kpi-standard`; Technical details on source cards is a button with a chevron | The Single Roles pattern named in the specification could not be identified; the chevron control already used on review rows is the reference. Non-`details` expanders were not all audited |
| 1.6 Status pills: vertical padding, centered content | Implemented | Matrix pills (`.matrix-pill`), `StatusBadge` minimum height, `kpi-standard` | |
| 1.7 No thick selected borders | Implemented | `Kpi`, review rows, active period row | Callouts and detail indents keep a side rule because they are not selection |
| 2.1 to 2.4 Dashboard KPI section and detail sections | Implemented | `Dashboard.tsx`, `account-review-refinement`, `refinement-round2`, `sod-overview-heatmap` | Detail sections no longer repeat the key figures; review progress shows only real counts and the real share reviewed |
| 3.1 Position changes table | Implemented | `AccountReview.tsx`, `position-changes` | Previous and current position, no Status column, icon Review action; snapshot and first-detected moved to the review dialog |
| 3.2 Review dialog limited to identity, position changes, decision | Implemented | `AccountReview.tsx`, `position-changes`, `refinement-round2` | Findings and evidence stay in the row details and behind Investigate SAP user; history and persistence unchanged |
| 3.3 Account Review KPIs | Implemented | `AccountReview.tsx`, `account-review-refinement` | Five review KPIs, account status secondary |
| 4.1 Compare users icon | Implemented | `UserAccess.tsx` | |
| 4.2 Assigned role layout | Implemented | `UserAccess.tsx`, `styles/components.css`, `access-investigation` | No separate description column; badge at natural width |
| 4.3 Release Roles toolbar | Implemented | `ReleaseRoles.tsx`, `release-roles` | Role actions and Compare SAP User Groups to the left of Export CSV |
| 4.4 No repeated record text under the users count | Implemented | `ReleaseRoles.tsx`, `release-roles` | The count stays a button |
| 4.5 Release filter sidebar | Implemented | Shared sidebar button styles | |
| 5.1 Shared SoD context bar | Implemented | `SodShared.ContextBar`, `GET /api/sod/context`, `sod-layout`, `test_sod_governance` | One bar on every SoD page; pages no longer repeat it |
| 5.2 Overview redesign | Implemented | `SodOverview.tsx` | Compact KPI groups; the existing additional metrics were kept as compact KPIs, and the evaluation date row moved to the context bar |
| 5.3 Heatmap preserved | Implemented | `SodGroupHeatmap`, `sod-overview-heatmap` | Unchanged |
| 5.4 Compact review period summary | Implemented | Unchanged from the earlier compact state | |
| 6.1 Explorer role codeblock width | Implemented | `col-role` minimum width | |
| 6.2 Status pills in SoD tables | Implemented | See 1.6 | |
| 6.3 Work queue KPIs | Implemented | `SodReviews.tsx` | |
| 6.4 Risk configuration | Implemented | `SodRiskSettings.tsx`, `sod-catalogue` | |
| 6.5 Data source health buttons | Implemented | `Diagnostics.tsx`, `refinement-round2` | Side by side, wrapping when narrow |
| 7 Cross-product consistency audit | Partial | Screenshots at 1280 and 375 (and 800) in both themes for Dashboard, Account Review, dialog, User details, Release Roles, SoD, Settings | A representative subset was inspected by eye; zebra, hover and selected rows were fixed and tested |
| 8 Validation | See Validation | | |

A defect found while validating: showing the previous result while a filter loads (needed to keep keyboard focus on KPI filters) rendered a differently shaped result after a drill-down and blanked the page; kept results are now limited to the same query shape and review context.

## UI/UX Refinement Round 2

Status is stated per requirement from the code and the tests that exercise it. Commits are on `origin/work`; every push was followed by a successful *Fast Validation* run.

### Phases and where they landed

| Phase | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| 1 Shared foundation | Information-density rules, button icons, no decorative module-icon hover ring, multiselect toolbar (Clear visible when empty), one-line codeblocks with full copy, zebra/hover/selected tables incl. Single Roles, one disclosure chevron | Implemented | `InfoList`, `Charts`, `DisclosureChevron`, `RoleIdentifier`, `refinement-r2`, `kpi-standard`, `ui-polish-actions` (`eca735a`) |
| 2 Dashboard | Charts and information lists from real data, no invented trends | Implemented, then superseded by Dashboard v4 below | `91082f1`, `36d9aef` |
| 3 Access Package | Compact rows (badge, description, one codeblock, suffix field right of it, validation status, remove), sticky Clear/Copy/Export bar, suffix eligibility from role patterns, Confirmed/Unconfirmed/Invalid/Needs suffix, unconfirmed names exportable with a warning, CSV gains a Validation column | Implemented | `backend/access_package.py`, `AccessPackagePanel`, `test_access_package`, `access-package`, `access-package-r2` (`0585c60`, style fix `0a0e637`) |
| 4 Account Review / User Access | Position changes table, review dialog scope, comparison filter chip at content width, role rows without full-width badges and with unbroken codeblocks | Implemented (most already present from the earlier round; chip width and role-row geometry are now tested) | `investigation-tools`, `refinement-r2`, `position-changes` (`9d54598`) |
| 5 Release Roles | Toolbar order Compare SAP User Groups, Add filtered roles, Copy role names, Export role list, Export CSV at one height, wide users modal with intact names | Implemented | `release-roles` (`9d54598`) |
| 6 Shared SoD heatmap | One heatmap under the Review Context on all seven SoD pages, expanded by default, collapse persisted as a local preference, group/risk/activity/cell selection written to page filters or handed to the matching matrix, visible removable filters, compact SAP User Group rows with sticky header in the Risk Matrix | Implemented | `SodGroupHeatmap`, `localPreference`, `sod-shared-heatmap`, `sod-overview-heatmap` (`a32672a`) |
| 7 SoD analysis | Explorer users and roles evidence in wide modals, redesigned Potential SoD evidence dialog (both activity sides, transaction, single role, assigned role, catalogue role or pattern, validity, provenance), Risk Acceptance row layout | Implemented | `SodExplorer`, `SodConflicts`, `SodInvestigation`, `sod-evidence-modals`, `sod-governance` (`a32672a`) |
| 8 Settings | Source health cards in independent columns, Technical details and Review source side by side, Component Library patterns, tab strip spacing | Implemented | `IndependentColumns`, `ComponentLibraryPatterns`, `settings-r2` (`cb9f36b`) |
| 9 Validation and handoff | Targeted tests, visual QA, full regression, audits | See Validation | |

### Dashboard addenda

- **Visual refinement** (`36d9aef`): central match-health thresholds (`lib/health.ts`: green from 95%, amber from 85%), spacing under progress bars, Role Distribution shows five areas and opens the rest in a dialog (the grid never stretches), Review Progress uses green, gray and amber, Assignment Distribution shows counts with shares, technical notes in info popovers.
- **Dashboard v4** (`fc1de4e`): three-column grid, no key figure row and no repeated metric; Access & Risk with SAP users as the headline; Review Progress as the only review completion view; Directory & Data Health with match percentage and separate Matched, Missing and Ambiguous counts (backend counts the existing match statuses) plus an independent Position changes row; Segregation of Duties card; five assignment ranges (0-5, 6-10, 11-20, 21-30, 31+) over every SAP user with a matching `assignment_band` filter in User Access; Data Sources & Configuration cards with honest states. Account Review gained `directory_missing` and `directory_ambiguous` findings.

### Startup data restoration (root cause and fix, `4f0c10d`)

Persisted datasets are restored by the backend (static sources from private snapshots, dynamic sources re-read). The client only re-read dataset views when the configuration `data_revision` changed, but a restored snapshot keeps its old timestamp, so a client that stayed open across a restart, or views fetched while the backend was still restoring (default 5 minute cache), kept their loading-time empty state until a manual refresh. Fix: the configuration carries a per-process `instance_id`, the end of any observed load re-reads active views, the backend marks itself loading before it serves its first request, and the application reports loading until configuration has answered. No delay, extra polling or automatic reimport was added. Tests: `test_loading_publication` (restart restore for static and dynamic sources, a real fresh process, loading from the first request, missing source, missing file with a validated snapshot, failed reload), `startup-reliability` (the two defect scenarios fail against the old provider and pass now).

### SoD Dashboard initialization (root cause and fix, `2b0eb66`)

The Dashboard SoD card shared its query key with the SoD Overview page and treated an `available: false` answer as a final verdict. While persisted data was still being restored the backend answers "unavailable" (no snapshot yet); the card showed "SoD analysis is not available" and the answer was only refreshed when a SoD page, which uses the same query key, fetched it again. The backend itself restores SoD correctly (probed for static and dynamic sources). The card now has four distinct states: loading ("Preparing SoD analysis" while the application loads), failed (message and Try again), unavailable (the backend coverage lists the missing inputs, a shared button opens the matching source) and ready; the Dashboard requests its own data and re-reads when a load ends. Tests: `sod-dashboard-startup` (loading then ready without visiting SoD, same values after a SoD visit and a reload, unavailable naming the source, failed with retry, disabled), `test_loading_publication` (`SodRestartTests`: static and dynamic restart twice, unavailable names the missing source, mapping disabled).

### Defects found while validating

- The package-row stylesheet block was dropped by an earlier edit of mine (`36d9aef`); the 375 px visual check showed the stretched suffix field and large status text. Restored with stronger selectors and a 375 px assertion.
- The shared heatmap's header buttons had clipped focus rings (found by `a11y-audit`); the scroller now has padding.
- Two heatmap-related ambiguities (two "Export CSV" buttons, two retry alerts) were removed by naming the heatmap export "Export heatmap CSV" and giving its error a distinct title.

## Validation

- **Round 2 final regression** (`python scripts/run-tests.py regression --jobs 1`, head `0a0e637`): backend 793 tests, 3 skipped (PowerShell and PyInstaller only), 0 failed; build with type check, documentation links, workflow contracts, Lucide catalog (1447 icons), whitespace and `pip check` passed; browser 569 tests, 553 passed and 16 failed. The 16 failures were two specs still asserting the superseded Dashboard (`refinement-27` looked for the former "Configuration" region, `refinement-search-layout` for the removed review completion progress bar and the former 1-5 range). They were updated to the v4 structure and re-run: both specs pass (29 tests). The complete suite was not re-run a second time after those two spec edits.
- Dependency audits: `npm audit --omit=dev` and `npm audit` 0 vulnerabilities; `pip-audit` on `requirements.txt` and `requirements-dev.txt` none.
- GitHub: *Fast Validation* succeeded on every Round 2 push on `work`, including the final code head (`0a0e637`). No workflow was dispatched; no package build was run or checked.
- Visual QA: a temporary harness captured 104 full-page screenshots (Dashboard, Access Package panel, Role Details, Account Review, Release Roles, SoD Overview, Risk Matrix, Activity Matrix, Access Explorer, Reviews, the Explorer evidence modal, Data Source Health and the Component Library, in light and dark at 375, 800, 1280 and 1600 px) and every one passed the no-horizontal-overflow assertion. About twenty screenshots over the session (Dashboard at 1280, 1600 and 375 in both themes, SoD Overview light 1280, Risk Matrix dark 375, evidence modals, Data Source Health dark 1280, package panel at 375, Release Roles 375 and 1280, the SoD unavailable button) were inspected by eye and the defects above fixed. The remaining screenshots, the Component Library at every width and the Account Review and Role Details pages at 800 and 1600 px were checked only by the overflow assertion. The Employee Directory and SoD-enabled Dashboard variants were covered by tests more than by eye.


- KPI standardization (fourth specification), single-process full regression (`python scripts/run-tests.py regression --jobs 1`, head `ffed040`): backend 780 tests, 3 skipped, 0 failed; browser 530 tests, 529 passed and 1 failed (`settings-runtime-theme` data source health, which still asserted the former `details` element for Technical details); build with type check, documentation links, workflow contracts, Lucide catalog (1,447 icons verified), whitespace and `pip check` passed. The spec was updated and re-run on the final code (5 of 5 passed); no product code changed after the full run. `npm audit --omit=dev`: 0 vulnerabilities; `pip-audit` on `backend/requirements.txt`: none. An earlier three-process targeted run found one genuine defect (blank page after drilling from a group row, caused by showing a differently shaped previous result), fixed before the full run.

- Full regression on the final code, single process as in CI (`python scripts/run-tests.py regression --jobs 1`, commit `d9bf29f`): backend 775 tests, 3 skipped
  (PowerShell and PyInstaller only), 0 failed; browser 513 tests, 0 skipped, 0 failed; build with type check, docs links, workflow contracts, Lucide catalog,
  whitespace and `pip check` passed. An earlier `--jobs 3` run on the same feature set also passed. The GitHub single-process run on `c3ca4e5` failed
  `sod-governance:105` because of saved filters left by another spec; the spec now compares only its own view's saved filters.
  An earlier full run had 1 browser failure (`data-aware-ux` visual QA dark 800) that passed in 12 repeats and in 24 repeats under CPU load
  and did not recur; its cause is not explained and it is not classified as harmless.
- `npm audit --omit=dev`: 0 vulnerabilities. `pip-audit` on `backend/requirements.txt`: none.
- Visual QA: screens loaded without horizontal page overflow in light and dark at 375, 800, 1280 and 1600 px (SoD Overview, Assignments, Remediation, Risk Matrix,
  Role Assignment Review panel, Account Review and dialog, Compare users, Release Roles, Role Lookup, Settings tabs). Screenshots were
  inspected for SoD Overview, Assignments, Account Review, the review panel (a narrow-row defect was fixed) and the Component Library; the other combinations were checked
  by the overflow assertion only.
- Accessibility: existing audit and keyboard specs pass; keyboard coverage added for multi-select and bulk selection. No external audit tool was run.

## Not verified

- Round 2: Windows/WebView2 startup and restart restoration, native save dialogs for the new package CSV (the Windows bridge was only unit tested with the new header), Windows Service, installer, systemd and UNC paths were not run here. The startup behavior was validated by real fresh-process backend tests and by browser tests that model the restart, not on a packaged desktop app.
- Known limitations: with SoD disabled the second Dashboard row has two cards (one empty column slot at desktop width); Data Source Health cards lose their expanded state when a resize changes the number of columns; the package suffix eligibility rule keeps exact roles unchanged even if a user would like to rename them (by specification).

Windows/WebView2 lifecycle, Windows Service, installer acceptance, Linux systemd and deployment packages were not run here.
Deployment workflows were not dispatched.

## Recommended next steps

1. Find the cause of the intermittent `data-aware-ux` dark 800 failure (capture the error with a retained trace in CI).
2. Audit remaining tables for empty states and the Component Library for scrollbar spacing, T-code sizing and popover details.
3. Add dedicated specs for the remediation grouping and the period action menu.
4. Run the native Windows and systemd acceptance checks before a release.
