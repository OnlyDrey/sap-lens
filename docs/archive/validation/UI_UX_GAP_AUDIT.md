# UI/UX gap audit

> Archived (R8): a dated verification of the consolidated refinement. Current behavior is described in the [feature guides](../../features/README.md).

Verification of the consolidated refinement against its checklist (32 requirements, A01 to E07), starting from `a054d7c`.
Status values: **Implemented** (verified in code and behavior), **Partial**, **Missing**, **Regression**, **Not verified**.
Evidence is the code or behavior inspected in this run, not a commit message or the earlier handoff. Related guides:
[implementation handoff](../../development/IMPLEMENTATION_HANDOFF.md), [component APIs](../../architecture/COMPONENTS.md), [testing](../../development/TESTING.md).

## Counts

| Status | Before remediation | After remediation |
| --- | --- | --- |
| Implemented | 22 | 30 |
| Partial | 8 | 2 |
| Missing | 1 | 0 |
| Regression | 1 | 0 |
| Not verified | 0 | 0 |

Remaining Partial items are A04 and C04, with reasons below. No requirement is claimed complete on the strength of a test that was not run.

## Requirements matrix

Verification method: **code** (read the component and handler), **browser** (Playwright behavior), **visual** (screenshot inspected in the harness listed under Visual QA), **backend** (unit tests).

| ID | Expected behavior | Before | After | Source | Gap found and fix | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| A01 | Compact sidebar Clear with icon, header alignment, consistent layout | Implemented | Implemented | `Shared/FilterLayout` | None | code, visual, `consolidated-refinement` |
| A02 | Shared multi-select: open while toggling, search, checkboxes, Select all visible, Clear, keyboard, OR within and AND across | Implemented | Implemented | `Shared/MultiSelectFilter` | None | browser `sod-bulk-review`, visual |
| A03 | Primary color for active states, secondary for secondary actions, no icon hover rings, visible focus | Implemented | Implemented | `styles/components.css` | None | code, visual, `ui-polish-actions` |
| A04 | Consistent capitalization, headings, labels, terminology; SAP terms preserved | Partial | Partial | all pages | "SAP user group" was spelled two ways and one table header was Title Case: unified to the official "SAP User Group", header fixed; rule documented in the design system. Navigation, page, section and decision names keep Title Case by convention. Only an automated sweep (not a full copy edit) was run | automated text sweep over both page families |
| A05 | SAP usernames and role names are copyable codeblocks | Partial | Implemented | `Shared/MatrixGrid`, `Sod/SodExplorer` | SoD matrix user rows and Explorer Users tables showed plain text: now codeblocks with copy. The profile header keeps the username as a title | sweep for plain identifiers, visual, `ui-polish-actions` |
| A06 | Pill padding, centered icons, risk-specific colors across SoD | Implemented | Implemented | `Shared/IdPill`, `StatusPill` | Progress bars showed a solid gray bar at zero: all progress bars now render an empty track | visual |
| B01 | Role Lookup card alignment, independent columns, consistent spacing | Implemented | Implemented | `RoleList/RoleCard` | None | visual |
| B02 | Multi-select SAP roles and SAP User Groups, open while selecting | Implemented | Implemented | `Access/UserAccess` | None | browser `global-navigation` |
| B03 | Missing ANY/ALL, reverse transaction filter, coexistence | Implemented | Implemented | `Access/UserAccess`, `TransactionFilter` | None | backend and `access-package` |
| B04 | Clear selection, Remove role, Clear package are separate, package clear confirms | Implemented | Implemented | `RoleList/AccessPackagePanel` | None | browser `access-package` |
| B05 | Package drawer: compact header, role count, suffix configuration, compact cards, original and generated names, validation, copies, CSV, sticky footer, small screens | Partial | Implemented | `RoleList/AccessPackagePanel` | Header wrapped to four lines at 375 px, "Needs suffix" text was repeated per role, rows were tall: shorter subtitle and help text, icon-only Clear package on narrow screens, redundant hint removed, tighter rows | visual 1280 and 375, new browser test (header, sticky footer) |
| B06 | Suffix generation: wildcard and organizational suffix replacement, override precedence, preview, CSV | Implemented | Implemented | `backend/access_package.py` | None | backend, `access-package` |
| C01 | Account Review on the shared sidebar, Saved Filters, Clear, tiles filter and combine | Partial | Implemented | `Access/AccountReview` | Tiles replaced each other: they now toggle and combine (findings OR, classification AND) | browser `account-review-refinement` |
| C02 | Review finding, license classification, decision multi-select | Missing | Implemented | `Access/AccountReview`, `routers/account_review.py` | Were single selects. Now lists (OR within, AND between, both classifications do not narrow); singular API parameters and older saved filters still work | backend (new), browser (new), saved-filter migration |
| C03 | Compare users: shared sidebar, Saved Filters, multi-select where applicable, Clear, no same user on both sides | Partial | Implemented | `Access/UserComparison`, `routers/user_comparison.py` | SAP area was single: now multi-select (OR). Assignment validity and Comparison section stay single because they are mutually exclusive scopes | backend (new), browser, visual |
| C04 | Release filters multi-select (SAP User Group, Area, Group, Strategy, others); username and role search accept several values | Partial | Partial | `Access/ReleaseRoles`, `ReleaseFilter`, `routers/access.py` | SAP User Group is now multi-select; username and role name accept comma, semicolon or line separated values (partial text per value, OR). PR/PO (two values) and Release assignment status (mutually exclusive date scope) remain single choices | backend (new), browser (new), exports |
| C05 | Release users panel: clickable count, matching users, codeblocks, assignment info, navigation, export, respects filters | Implemented | Implemented | `Access/ReleaseRoles` | Verified with the multi-group scope | browser (new) |
| C06 | Add filtered roles, copy, export roles and assignments with correct scope | Implemented | Implemented | `Access/ReleaseRoles`, `routers/access.py` | Exports verified with multi-group and tokenized filters | backend (new), `release-roles` |
| D01 | Heatmap heading and controls on one row, responsive, sorting and export | Implemented | Implemented | `Sod/SodGroupHeatmap` | None | visual, `sod-overview-heatmap` |
| D02 | Compact approved-period empty state | Implemented | Implemented | `Sod/SodOverview` | At 800 px the third section sat alone in a half row: now spans the row | visual, browser (new) |
| D03 | Interactive tiles filter the table, combine, toggle, accurate counts | Implemented | Implemented | `Shared/InvestigationPatterns` | None | `sod-filters-tiles` |
| D04 | Matrix multi-select, pill padding, combined filters | Implemented | Implemented | `Sod/SodMatrices` | None | `sod-governance` |
| D05 | Assignments: no module, no Active badge, no dates, active by default, history on request, codeblocks, Investigate icon | Implemented | Implemented | `Sod/SodExplorer` | Default, historical scope and export now covered by a browser test | browser (new), visual |
| D06 | Roles table: no module or badge, users count, codeblocks, risk and activity pills | Implemented | Implemented | `Sod/SodExplorer` | None | visual |
| D07 | Role conflicts: colored Risk ID pill, evidence preserved | Implemented | Implemented | `Sod/SodConflicts` | Header wording ("Catalogue role / combination") | visual |
| E01 | Reviewer name remembered per session, reused across review screens, changeable, recorded per decision | Partial | Implemented | `lib/reviewer.ts`, `Sod/*` | Period approval started with an empty reviewer: it now reuses the session name. Not browser-tested for the period dialog | code, `consolidated-refinement` (quick review, bulk) |
| E02 | Compact assignment rows: checkbox, codeblock, description, status, Keep/Investigate/Remove, expandable evidence, no user group, validity or active badge collapsed | Regression | Implemented | `Sod/SodInvestigation`, `styles/components.css` | Expanded rows overflowed the panel at 375 px (status and icons clipped) and the description was missing: grid track fixed, evidence wraps, catalogue description shown | visual 375 and 1600, browser (new, both) |
| E03 | Batch review: row, page and matching selection, suffix and multi-user filters, Keep, Remove, confirmation, counts, history | Implemented | Implemented | `Sod/SodBulkReview`, `SodExplorer` | None | `sod-bulk-review`, `test_sod_bulk_review` |
| E04 | Compact Activity Review rows with status, Activity ID, Risk pill, role coverage, icon action, expandable evidence and history | Partial | Implemented | `Sod/SodInvestigation` | Rows showed the decision text and history permanently and the actions wrapped to a second line at drawer width: single-line row with an icon action and expand control; activity, risk acceptance and assignment decisions stay independent | visual, browser (new), `sod-governance` |
| E05 | Work queue codeblocks, filter tiles, consistent actions, progress | Implemented | Implemented | `Sod/SodReviews` | None | visual |
| E06 | Period menu icons, trigger size, alignment, archive, delete, compare | Implemented | Implemented | `Sod/SodPeriods` | None | visual (menu open), `sod-periods` |
| E07 | Document details expanded by default, fields, PDF/DOCX, approval and signing information | Implemented | Implemented | `Sod/SodReports` | None | visual, `sod-reports`, `test_sod_reports` |

## Test results

- Full regression, single process as in CI (`python scripts/run-tests.py regression --jobs 1`, head `1933f67`): backend 779 tests, 3 skipped (PowerShell and PyInstaller only), 0 failed; browser 521 tests, 0 skipped, 0 failed; build with type check, documentation links, workflow contracts, Lucide catalog, whitespace and `pip check` passed.
- An earlier three-shard run (`--jobs 3`, same code apart from the test hardening below) had 3 browser failures that all passed in isolation: `data-aware-ux` light 800, `investigation-ux` combobox keyboard and `ux` startup connection failure (a route mock whose response was disposed by `page.reload()`). The two mock handlers were hardened. The `investigation-ux` failure was not reproduced in 25 loaded repeats and its cause is unknown; four cores were running three browsers and three servers at that moment, so CPU contention is the likely trigger, not a proven cause.
- `npm audit` and `pip-audit` were not re-run in this pass.

## Visual QA

A temporary harness (not committed) drove the Access family (dashboard, Role Lookup with filters, package drawer, User Access, user details,
Account Review with an open multi-select, Compare users, Release Roles matrix, table and users panel) and the SoD family (Overview, both matrices,
the four Explorer tabs with an open dropdown and a bulk selection, work queue, remediation, the review panel collapsed, expanded and with a decision form,
Review Periods with the action menu open, Reports) in light and dark at 375, 800, 1280 and 1600 px with long role identifiers and a long period name.
All 16 theme and width runs passed a polled "no horizontal page scroll" assertion (216 screenshots). About 20 screenshots were inspected by eye
across both families, both themes and all four widths; defects found that way (narrow expanded assignment rows, wrapping activity actions,
half-empty Overview row, solid progress track, wrapping package header) are fixed above. The remaining screenshots were checked by the overflow assertion only.

## data-aware-ux dark 800 failure

- The earlier failure was never reproduced in a single worker. This run instrumented the test (polled overflow check; offending elements and a screenshot are attached on failure; `retain-on-failure` traces were already on).
- Under heavy CPU load (6 busy loops on 4 cores, single worker, 30 repeats) both the original and the hardened test passed 30 of 30.
- With two workers sharing one backend (an unsupported stress configuration), 2 of 25 runs of the original test hung on the disabled Refresh button, and the test's own mocking order was a second race: it faked `loading: true` before clicking Refresh, so any application configuration poll in between disabled the button. The mock now activates only after the refresh request.
- **Root cause of the single historic failure: not proven.** The two races above are plausible mechanisms and are removed; the overflow assertion that was not polled is now polled and self-documenting. If it recurs, the attached JSON and screenshot identify the element.

## Remaining gaps

- C04: PR/PO and Release assignment status are not multi-select (two values and a mutually exclusive scope).
- A04: Title Case remains for navigation, page, section and decision names; no complete copy edit was performed.
- Visual inspection covered a representative subset (see above), not every screenshot.
- E01 period approval reuse of the reviewer name has no dedicated browser test.

## Manual acceptance still required

Windows/WebView2 lifecycle, Windows Service, installer, systemd, UNC paths and deployment packages were not run in this Linux environment and
no workflow was dispatched. Check on Windows: native save dialogs for CSV, DOCX and PDF exports, and sidebar drawers in WebView2.
