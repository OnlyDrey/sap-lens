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

## Validation

- Full regression run (`python scripts/run-tests.py regression --jobs 3`): backend 769 tests, 3 skipped (PowerShell and PyInstaller
  only), 0 failed; build with type check, docs, workflow, Lucide, whitespace and `pip check` passed; browser 501 tests with 1 failure
  (`data-aware-ux` visual QA dark 800), which passed in 12 repeats and 24 repeats under CPU load. Its cause is not explained;
  it is not classified as harmless. An earlier full run had 2 failures: `sod-governance:203` (test pollution from the bulk spec, fixed) and
  `refinement-27:39` (an unawaited save in the spec, now polls).
- `npm audit --omit=dev`: 0 vulnerabilities. `pip-audit` on `backend/requirements.txt`: none.
- Visual QA: screens loaded without horizontal page overflow in light and dark at 375, 800, 1280 and 1600 px (SoD Overview, Assignments, Remediation, Risk Matrix,
  Role Assignment Review panel, Account Review and dialog, Compare users, Release Roles, Role Lookup, Settings tabs). Screenshots were
  inspected for SoD Overview, Assignments, Account Review, the review panel (a narrow-row defect was fixed) and the Component Library; the other combinations were checked
  by the overflow assertion only.
- Accessibility: existing audit and keyboard specs pass; keyboard coverage added for multi-select and bulk selection. No external audit tool was run.

## Not verified

Windows/WebView2 lifecycle, Windows Service, installer acceptance, Linux systemd and deployment packages were not run here.
Deployment workflows were not dispatched.

## Recommended next steps

1. Find the cause of the intermittent `data-aware-ux` dark 800 failure (capture the error with a retained trace in CI).
2. Audit remaining tables for empty states and the Component Library for scrollbar spacing, T-code sizing and popover details.
3. Add dedicated specs for the remediation grouping and the period action menu.
4. Run the native Windows and systemd acceptance checks before a release.
