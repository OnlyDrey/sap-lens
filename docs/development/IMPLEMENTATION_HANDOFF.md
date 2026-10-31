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

## UI/UX Refinement Round 3 (Access Package, navigation, Account Review, SoD Overview)

Commits are on `origin/work`; no workflow was dispatched and no tag or release was created.

| Phase | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| 1 Access Package | Clear selection in the floating bar; statuses Confirmed, Pattern match, Needs attention, Invalid; Confirmed needs the exact generated name in imported roles or assignments, a wildcard match is only a Pattern match; colon-terminated stems such as `ZC:BC:S4_COMMON_USERS_____MGT:` are valid | Implemented | `a9a65e5`, `access-package*`, `test_access_package` |
| 2 Navigation | Main link opens the module page, a separate chevron opens the submenu; Return to previous user in the manager card; Single Roles hover; Explorer action icons; secondary navigation icons; SoD settings actions | Implemented | `ef4fe6c`, `navigation-r3` |
| 3 Account Review and shared UI | One progress overview and compact action tiles (no Classified unlicensed, duplicate SAP accounts or duplicate Pending), visible progress bars, source health 3/2/1 columns, distinct Dynamic, Criticality and Type pills, no criticality filter in operational SoD views | Implemented | `97b6d75`, `account-review-refinement` |
| 4 SoD Overview | Users with more than one risk (Explorer filter), most common conflicting roles (top five, Show more, Explorer drilldown), remediation awaiting action, remediation verified with explained unavailable state | Implemented | `649c5f8`, `sod-overview-actionable`, `test_sod_governance` |
| 5 Audit and regression | Visual QA, full regression, audits, handoff | See Validation | |

### Decisions worth knowing

- *Remediation verified* needs three things: a tracked removal action, the assignment absent from current evidence with complete source coverage, and a User-Role import newer than the action. A Completed status or a missing assignment alone never verifies. A removal whose user has disappeared from the evidence is not assessable, so it is not verified.
- *Users with more than one risk* counts distinct risk IDs per user; the drilldown uses the same rule (`multiple_risks`), so list and tile agree.
- The Account Review Outdated reviews tile is shown whenever review annotations are available (a zero is information, and the existing investigation spec relies on it).

### Validation (Round 3)

- Single-process full regression (`python scripts/run-tests.py regression --jobs 1`, head `649c5f8` plus the stylesheet change below): backend 800 tests, 3 skipped (PowerShell and PyInstaller only), 0 failed; browser 581 tests, 0 skipped, 0 failed; build with type check, documentation links, workflow contracts, Lucide catalog, whitespace and `pip check` passed.
- After that run, one stylesheet rule changed (Account Review action tiles share one row from tablet width); `account-review-refinement`, `investigation-tools` and `refinement-search-layout` were re-run and passed (50 tests). The complete suite was not repeated.
- `npm audit --omit=dev`: 0 vulnerabilities. `pip-audit` on `requirements.txt` and `requirements-dev.txt`: none.
- Visual QA: SoD Overview, SoD Remediation (Awaiting action), Account Review and Data Source Health in light and dark at 375, 800, 1280 and 1600 px loaded without horizontal page overflow (assertion on all 32 captures). Screenshots inspected: Overview (375, 1280), Account Review (800, light and dark), Remediation (1280 dark), Data Source Health (1600). Other combinations were checked by the overflow assertion only.
- GitHub *Fast Validation* succeeded for the Phase 1 to 3 pushes; the Phase 4 run (`649c5f8`) was queued when last checked.

### Remaining limitations

- Remediation at 1280 px with the filter sidebar open scrolls the table horizontally inside its card, so the Actions column is partly hidden until scrolled. The page itself does not overflow. Not changed in this round.
- The info tip button beside *Most common conflicting roles* is the shared 32 px icon button, taller than the heading text.
- Windows/WebView2, Windows Service, installer, systemd and UNC acceptance, and deployment package builds, were not run here.

## UI/UX Refinement and Validation Framework (Round 4)

Commits are on `origin/work`; no workflow was dispatched and no tag or release was created.

| Phase | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| 1 Access Package | Package bar only describes and clears the package (Clear package, confirmed); the selection bar shows one or more selected roles with Clear selection and offers Compare now from two; role codeblocks first wrapped long names (`70f1092`), which was corrected: names are one complete line, never wrapped, scrolled or truncated (see Codeblock correction) | Implemented, corrected | `70f1092`, correction commit, `access-package-r2`, `refinement-r2`, `role-codeblocks` |
| 2 Navigation | Submenu is a no-scroll menu popover that overlays the page, never resizes the navbar and has no left border on hover, focus or current | Implemented | `f015008`, `navigation-r3` |
| 3 Account Review | Compact progress section (heading, percentage, bar, one legend row; about 120 px on desktop) | Implemented | `5535c22`, `account-review-refinement` |
| 4 SoD Overview | Most common conflicting roles and Remediation verified removed from the UI (API data and the Verified removals filter stay); card rows share one height | Implemented | `043ac7a`, `sod-overview-actionable` |
| 5 Matrices | Username with group beneath, sticky first column, optional Group by SAP User Group (collapsible, distinct counts over the filtered scope, each user once), multi-select group filter with grouping | Implemented | `7413462`, `sod-matrix-grouping`, `test_sod_governance` |
| 6 Validation framework | `docs/validation` CSV (138 items, 18 areas), checker, summary, workbook export and merge | Implemented | `0bf327f` (tooling and guide), the CSV itself in the final commit because `*.csv` is git-ignored; `test_validation_tracker` |
| 7 Final validation | See below | Done | |

### Decisions worth knowing

- The old Rows view of the matrices (aggregated SAP User Groups) was replaced by Group by. The aggregate API (`group_by=group`) stays for the shared heatmap; `group_by=user_group` is the new presentation mode.
- A user in several SAP User Groups is listed once, under the first selected group or else the first group, so group counts partition the users; other groups are noted under the username.
- Grouping is presentation only: matrix exports use the Explorer export of the active filters and are identical with and without grouping (tested).
- The validation tracker marks 133 of 138 items Not reviewed; two are recorded improvement opportunities found during visual QA plus the new floating-bar item, and three Windows checks are Blocked in Linux CI. Nothing is Approved.

### Codeblock correction (single line, no scrolling)

Commit `70f1092` made role codeblocks wrap; the requirement is the opposite: always the complete name on one line, no wrapping, scrolling, truncation or ellipsis, copy icon beside it. Implementation:

- `.role-identifier code` is `white-space:nowrap; overflow:visible; text-overflow:clip` everywhere (the old `overflow-x:auto` and the `wrap` of the first attempt are gone). Width caps on the codeblock (260 px in the user directory and role detail heading, 360 px in SoD tables) and `overflow:hidden` on the side panel link were removed.
- `RoleIdentifier` fits the name to its container: when the container is narrower than the name, the font scales down (not below 9 px) and grows back when space returns (shared `ResizeObserver` on the parent). Containers of a codeblock may shrink (`min-width:0`) so a long name no longer pushes neighbours, such as the Close button of the role details panel, off screen. The role card grid uses `auto-fill` with a 22 rem minimum column instead of fixed 2, 3 or 4 columns, and the role detail heading puts the name on its own row.
- Limit, stated plainly: a name that does not fit even at 9 px (about 40 characters in a 375 px card, more on wide screens) keeps its full single line (`data-fit="overflow"`), and the immediate container of the codeblock becomes the horizontal scroll region while the page does not scroll. The codeblock itself never scrolls or clips. Tables are scroll regions of their own layout. A smaller floor would make long names fit but would not be readable.
- `role-codeblocks.spec.ts` checks, at 375, 800 and 1280 px in Role Lookup, role details, the Access Package panel, User Access, the Access Explorer and Reviews: `nowrap`, no overflow or ellipsis, one line of text height, no internal scrolling, the complete text, the copy icon beside the name and not clipped, exact clipboard value, scaling down and growing back, and that realistic names (42 characters) are fully on screen. Three existing specs that asserted wrapping were corrected back.

### Validation (Round 4)

- Codeblock correction: the first full regression after the change found 19 browser failures (role detail Close button pushed off screen by an overlong name, Component Library and role cards overflowing, three specs that still asserted wrapping); after the fixes a second full run had 6 failures, all in `refinement-search-layout` (the role detail name must stay right-aligned with the Close button), fixed by one rule. The affected specs (`refinement-search-layout`, `role-codeblocks`, `refinement-27`, `role-visuals`, 47 tests) pass; the complete suite was not repeated after that last rule. Backend: 810 tests, 3 skipped, 0 failed in both runs.
- Single-process full regression (`python scripts/run-tests.py regression --jobs 1`, head `0bf327f`, before the tracker CSV was un-ignored and committed): backend 809 tests, 3 skipped (PowerShell and PyInstaller only), 0 failed; browser 593 tests, 0 skipped, 0 failed; build with type check, documentation links, workflow contracts, Lucide catalog, whitespace and `pip check` passed. `a11y-audit` and `navigation-a11y` are part of that run.
- `npm audit --omit=dev`: 0 vulnerabilities. `pip-audit` on `requirements.txt` and `requirements-dev.txt`: none.
- Visual QA after the regression: submenu, Role Lookup with a long role name and both floating bars, SoD Overview, grouped Risk and Activity Matrix and Account Review in light and dark at 375, 800, 1280 and 1600 px loaded without horizontal page overflow (assertion on all 64 captures). Screenshots inspected: submenu (1280 light), Role Lookup (375 light), grouped Risk Matrix (800 dark). The other combinations were checked by the overflow assertion only.
- The workbook export was opened with openpyxl and converted by LibreOffice; it was not opened in Excel.

### Remaining limitations

- Remediation at 1280 px with the filter sidebar open scrolls the table horizontally inside its card (tracker `SODR-006`).
- The shared info tip button is taller than the headings it sits beside (`UI-016`); at 375 px the package and selection bars stack to roughly a quarter of the viewport (`PKG-009`).
- Windows/WebView2, Windows Service, installer, systemd and UNC acceptance, and deployment package builds, were not run here.

## Shared SoD filters, Review Periods and data sources (Round 5)

Commits are on `origin/work`; no workflow was dispatched and no tag or release was created.

| Phase | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| 1 Navigation and UI | Navbar scrollbar root cause fixed (the main navigation was an `overflow-x:auto` scroll container, so the SoD chevron group overflowed the header at medium widths and classic scrollbars appeared; it now wraps), Review Context evaluation text centered on the dropdown, Module and Submodule capitalized | Implemented | `5a1a498`, `navigation-r3`, `shared-ui-r5` |
| 2 Matrices and shared filters | Compact identity column (copyable username, SAP User Group beneath), shared SoD filter context with Clear page filters and Clear all SoD filters, investigation links add to existing filters | Implemented | `3baa1ae`, `sod-shared-filters`, `sod-matrix-grouping` |
| 3 Review Periods | Create and delete dialogs as responsive grids with icons, toolbar tooltip for Compare periods, visible archived toggle | Implemented | `5fae2b9`, `sod-periods-dialogs` |
| 4 Data sources | Browse CSV always available with an explained alternative, failed replacements never replace active data, read-only SoD Matrix inspection | Implemented | `6abca73`, `data-source-browse`, `test_sod_inspection` |
| 5 Regression, tracker, handoff | See Validation | Done | |

### Decisions worth knowing

- **Shared filters.** One shared slot (`sodFilters.shared`) holds the seven dimensions that mean the same wherever they exist (group, username, risk, activity, transaction code, business area, assigned role). Role Conflicts offers only risk, transaction code and business area; its other selections stay stored. Clear page filters clears the page's own filters and the shared dimensions it offers; Clear all SoD filters clears the whole filter context. Overview links merge into existing filters, which means a drilldown can show fewer rows than its tile counted when a filter is already active (the chips show why).
- **Typed paths.** Typing a CSV path imports it on leaving the field (existing behavior), so a pre-import preview of a typed SoD file cannot run first; the SoD inspection therefore describes the active validated snapshot. A failed attempt keeps the attempted path in the field (needed for correction and column mapping) while the message states that the active file is unchanged.
- **Tracker.** `docs/validation` gained the columns Implementation status and Test evidence; Status is documented as the manual acceptance status. The 11 items (UI-017, UI-018, SET-010, SODM-012, SODM-013, SODP-006 to SODP-008, DATA-010, DATA-011, SET-011) are Implemented with test evidence and stay Not reviewed.

### Validation (Round 5)

- Full single-process regression (`python scripts/run-tests.py regression --jobs 1`, head `6abca73`): backend 813 tests, 3 skipped (PowerShell and PyInstaller only), 0 failed; build with type check, documentation links, workflow contracts, Lucide catalog, whitespace and `pip check` passed; browser 634 tests with 3 failures, all caused by this round's changes: `enterprise` (Detect columns disabled after an early revert of the attempted path), `investigation-ux` (same cause) and `sod-catalogue` (the SoD preview dialog is now the inspection). The revert was removed, `sod-catalogue` was updated for the new dialog, and `enterprise`, `investigation-ux`, `sod-catalogue`, `data-source-browse`, `automatic-import` and `desktop` (50 tests) pass. The complete browser suite was not repeated after those fixes.
- Visual QA: submenu, Risk Matrix, Review Periods, Create and Delete dialogs and the SoD inspection in light and dark at 375, 800, 1280 and 1600 px loaded without horizontal page overflow (assertion on 40 captures). Screenshots inspected: Risk Matrix (800 dark), SoD inspection (375 light), the Settings data source and SAP Modules views (1280 and 375), the create and delete dialogs.
- Not run here: Windows/WebView2, Windows Service, installer, systemd, UNC and deployment package acceptance.

### Remaining limitations

- The navbar scrollbar could not be reproduced in Playwright's default headless Chromium (it hides scrollbars); the cause was established by measuring overflow and by running with scrollbars shown. Please confirm in the Windows desktop app.
- The SoD inspection dialog shows its data preview before the validation results, so at 375 px the validation section needs scrolling.
- A typed replacement path is imported when the field is left; there is no read-only pre-import preview for the SoD file.

## UI consistency and SoD refinements (Round 6)

Commits are on `origin/work`; no workflow was dispatched and no tag or release was created.

| Phase | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| 1 Shared UI | Shared Enabled, Disabled, Static and Dynamic badges with Lucide icons, `sentenceCase` for internal enum values, zero values always neutral in `Kpi` and `InfoRow`, one rounded token-driven focus ring | Implemented | `0c2d2ee`, `status-consistency-r6` |
| 2 SoD Risk Configuration | Amber New badge beside the Risk ID, separators instead of coloured rows, icons on Enabled and Disabled, no per-row Source details, Activities harmonized | Implemented | `ad9f64e`, `sod-risk-config-r6` |
| 3 SoD Matrix CSV | Verified against the checklist; no functional gap, two specs added | Verified | `854dd36`, `data-source-browse` |
| 4 Reviews and Review Periods | Work Queue and Remediation share the Kpi filter tiles, 8 px gap before Active period | Implemented | `ef1ff11`, `sod-reviews-r6` |
| 5 Tracker and regression | 14 R6 rows with implementation, automated validation, manual validation and remaining issues | Done | this commit |

### Findings worth knowing

- Most of the application already shared a token-based focus ring; the keyboard walk found only these outliers: tabs used a bottom bar instead of a ring, the navigation chevrons and matrix column buttons had square corners, and the heatmap scroll region had no ring. They now use the shared ring and `--focus-radius`.
- A generic `:where` rule would have changed the radius of pill-shaped controls while focused, so only the specific outliers were targeted.
- The R5 SoD inspection already satisfied the R6 checklist. A typed path is still imported when the field is left, so there is no pre-import preview of a SoD file.
- Row heights in the Risks and Activities tables share a minimum but still differ with content (risk rows have a third line).

### Validation (Round 6)

- Full single-process regression (`python scripts/run-tests.py regression --jobs 1`, head `ef1ff11`): backend 814 tests, 3 skipped (PowerShell and PyInstaller only), 0 failed; build with type check, documentation links, workflow contracts, Lucide catalog, whitespace and `pip check` passed; browser 649 tests with 2 failures, both in the new `sod-risk-config-r6` spec: whether a risk counts as new depends on review history left by earlier specs of the same run, so the spec now marks the list new through a route and passes (4 tests). The complete browser suite was not repeated after that fix.
- Visual QA after the regression: Work Queue, Remediation, Review Periods, SoD Risk Configuration (Risks and Activities) and Health and Diagnostics in light and dark at 375, 800, 1280 and 1600 px loaded without horizontal page overflow (assertion on 48 captures); the dark 1280 Remediation view was inspected, the others by the overflow assertion only.
- Not run here: Windows/WebView2, Windows Service, installer, systemd, UNC and deployment package acceptance.
- Keyboard focus: the new walk covers the SoD pages and Settings in both themes; Role Lookup, User Access and dialogs rely on the existing accessibility specs.

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

## Follow-up: SoD matrix Users per page

- Risk and Activity Matrix share one **Users per page** setting (10, 25, 50, 100, All; default 50) held in module state in `Sod/SodMatrices.tsx`, so it survives switching matrices within a session. The offset is remembered per matrix and clamped to page 1 when it no longer fits.
- The shared `Pagination` gained `unit` and `alwaysShow`; a range pager sits above the matrix and a second one below. *All* requests one page of up to `MATRIX_PAGE_MAX` (5000) users from `/api/sod/matrix/{risk,activity}`; a notice appears if more match. Rows are not virtualized: a 2000-user page rendered within the spec's 15 s budget, more than 5000 users is the documented limit.
- CSV exports use the Explorer export endpoints, which take only filters, so they ignore pagination.
- Tests: `frontend/tests/sod-matrix-paging.spec.ts`, `test_matrix_page_may_hold_every_user_but_not_more_than_the_ceiling`. Tracker rows SODM-014 and SODM-015 stay Not reviewed for manual acceptance.

## R6 correction batch (four outstanding items)

- **Account Review** (`381333e`): progress (1/3) and Review attention (2/3, two-column icon KPIs, compact AD disabled row) in one aligned row; the investigation notice is an info popover in the page header. The earlier rounds only compacted the progress card and kept the five-tile grid.
- **Shared KPI tones** (`c150eff`): `lib/kpiTone.ts` maps metric or review state to tone; pages no longer choose colors. Zero is neutral for warning, danger and success. Matrix Rejected and Removal tiles are now warning (were danger).
- **Access Explorer icons** (`304e9dc`): `ContentTabs` items now carry icons; tabs and secondary navigation reserve the bold label width (`.ui-tab-label`).
- **SoD CSV import** (`7dd0fec`): `sod_import` profile (delimiter, encoding, mapping) in `AppConfig`, used by imports and refreshes; read-only `POST /api/data-sources/sod/inspect`; `SodImportEditor` in the Data Sources tab. Inspection never stores anything.
- Tests: `account-review-refinement`, `kpi-semantic-tones`, `secondary-navigation-icons`, `sod-source-import` specs and `test_sod_inspection`. Tracker rows AR-008, UI-024, SODX-006 and DATA-013 are Not reviewed for manual acceptance.

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
