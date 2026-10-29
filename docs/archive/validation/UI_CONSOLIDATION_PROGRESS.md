# UI/UX consolidation and functional refinement: checklist and recovery record

Working record for the eight-phase consolidation (29 October 2026). A new session resumes from this
file and `git log origin/work`. Results apply to the recorded commits and the Linux environment only.

## Status

| Phase | Scope | State |
| --- | --- | --- |
| 1 | Module badge, role entry, focus tokens, DOM-order rules, Component Library | Implemented and validated on Linux |
| 2 | Dashboard order and lifecycle, SoD Overview, refresh lifecycle review | Implemented and validated on Linux |
| 3 | Filter sidebar, include/exclude ANY/ALL, Role Lookup, User Access, user navigation | Implemented and validated on Linux |
| 4 | Check state, floating package action, package panel, compare layouts, no package limit | Implemented and validated on Linux |
| 5 | SoD risk/activity editors, source details, colors, tables, activity review rows | Implemented and validated on Linux |
| Release Roles follow-ups | Release Area, multi-select filters, sidebar, package, bulk actions | Implemented and validated on Linux |
| 6 | Review periods table, position-change evidence, account review dialog, role evidence, distinct users | Implemented and validated on Linux |
| 7 | Reports, source health, features, Windows icon, theme grid | Implemented and validated on Linux |
| 8 | Full validation, QA, documentation, delivery | Linux validation recorded below; native Windows acceptance not run |

## Validation record (Linux)

- Backend: 741 tests, 3 skipped (PyInstaller and PowerShell not available), 0 failed.
- Browser: 485 tests; the complete run had two intermittent failures under three-shard load (`data-aware visual QA dark 1280`, `Windows tray settings use the parent draft`). Both pass when run alone, and both passed in the earlier complete run. They are recorded here, not hidden.
- Type check and production build, documentation links, workflow contracts, Lucide catalog, `git diff --check` and `pip check` pass.
- Specs were updated where the interface intentionally changed (filter sidebar and drawer, ALL/ANY groups, sort direction toggle, source health cards, role code blocks). No assertion about business behavior was weakened.
- Not run: Windows installer, WebView2, SCM, systemd and UNC acceptance; dependency audits and the manual build workflows.

## Registered follow-ups (Release Roles)

Belong to Phase 3 and Phase 4; implemented after Phase 5 and before Phase 6.

- Phase 3: Release Area (first character of the Release Group, derived dynamically); multi-select Release Area and Release Group (OR within, AND between categories); Release Group options narrow by selected areas; malformed values handled; Matrix and Table consistent; Release Roles filters in the shared sidebar with Saved Filters inside (external button removed, saved filters stay compatible).
- Phase 4: Plus/Check on release-role entries in Matrix and Table feeding the one shared Access Package (mixed with catalogue roles, source type preserved, no limit); release role names kept exactly, suffix only where a validated convention applies, generated names shown before copy or export.
- Phase 4: bulk actions on the Release Roles toolbar: Add filtered roles (distinct, confirmation when very large, added and already-selected counts), Copy role names (one per line, deterministic), Export CSV of distinct roles (ROLE_NAME, ROLE_DESCRIPTION, RELEASE_AREA, RELEASE_GROUP, RELEASE_STRATEGY, PR_PO) separate from the assignment-level export.
- Tests: area derivation, multi-select semantics, dynamic group options, Matrix/Table consistency, saved filters, mixed package, duplicates, suffix safety, bulk add/copy/export, validity and CSV correctness, keyboard and responsive checks. Run targeted now and in the final regression.

## Findings recorded during implementation

- Distinct users (6.5): the duplicated username in role evidence was a rendering effect of listing one row per assignment record. SoD role lookup, heatmaps and the lookup CSV already count distinct users; a backend test now locks this in (`test_repeated_role_assignments_count_one_distinct_user_in_lookup_and_exports`). Assignment records stay separate, with their validity intervals, in expandable details.
- Release roles: scope and suffix tokens are opaque, so a package suffix is never applied to them; they enter the package under their exact assigned names.

## Known blockers

None.
