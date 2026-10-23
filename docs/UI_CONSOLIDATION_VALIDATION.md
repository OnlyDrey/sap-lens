# Dashboard, loading and profile consolidation

## Baseline and scope

Started on clean `work` at `313a12782a4808627ff58cedad1916ddaafecc43`, matching
`origin/work`. Existing work was preserved; no resets/rebases, dependency upgrades,
CSV schema changes or SAP interpretation changes were made. README branding,
canonical assets, versioning, desktop packaging and workflows remain unchanged.

## Confirmed loading failure and fix

The new startup browser regression failed before the implementation: Dashboard
could retain its initial unavailable metrics after the configured sources finished
loading. The backend already constructed and validated a full replacement before
publishing it. The missing boundary was frontend-wide invalidation: Settings owned
loading observation and refreshed only role/module queries, leaving other route
caches stale. A late request could also restore an older result.

Configuration now exposes a non-sensitive publication timestamp. An application
provider observes it independently of mounted routes, cancels obsolete dataset
query results and refetches active queries after publication; inactive caches become
stale and refetch when used. Shared loading indicators suppress false initial
empty/not-found states while preserving accepted data through failed CSV refreshes.
Dashboard is the default landing; saved explicit routes/detail navigation still work.
Role Lookup mounts only after it is visited, avoiding an unnecessary initial full
catalogue download. Dashboard's coverage/metrics read the same backend snapshot.

Backend regressions exercise automatic configured-source startup, delayed second
source publication, failed replacement plus recovery, and single-snapshot Dashboard
reads. Browser regressions cover route changes during loading/refresh, obsolete
responses, failed refresh recovery, restored detail navigation and Dashboard links.

## UI changes

- Compact Dashboard groups: Overview, User Access, Data Quality, Configuration.
  Source setup actions open their own Data Sources tabs. Counter destinations
  retain existing semantics; expired/future counts do not pretend to apply an
  unsupported directory-wide validity filter. Catalogue shortcuts leave comparison
  mode and preserve unrelated User Access state.
- User directory: search, group, sort/direction and transaction controls share a
  responsive four/two/one-column container. Global Clear filters and evidence-only
  Clear filter remain distinct, with tested scope.
- Unified SAP Identity / Account & Validity / Organization profile. SAP names and
  emails stay authoritative; directory title/department/AD username enrich it.
  AD state remains separate from SAP account/lock evidence. Site and redundant
  matching labels are absent from the primary profile. Technical matching outcomes
  remain in Data Sources/Diagnostics.
- Manager navigation uses the existing uniquely resolved SAP username and browser
  history. Missing, unavailable and ambiguous identities have non-clickable neutral
  status pills. Conservative directory-only name formatting preserves ambiguous
  structures and compound names; imported values are untouched.
- Release filters use four/two/one columns, compact status/date controls, collapsed
  advanced interval bounds, and a results toolbar with sort/direction together.
  Existing inclusive bounds, missing ends, SAP maximum dates and export semantics
  remain covered by regressions. Dates/time retain Norwegian presentation.

Behavior and maintenance details: [Dashboard/loading](DASHBOARD.md),
[profile and identity boundaries](EMPLOYEE_DIRECTORY.md),
[filters and dates](INVESTIGATION_FILTERS.md).

## Validation

Final checks executed in the Linux workspace (2026-10-23):

| Command / check | Result |
| --- | --- |
| `npm --prefix frontend ci --cache /workspace/.npm-cache` | Passed; 143 packages, lockfiles unchanged |
| `npm --prefix frontend run check:types` | Passed |
| `npm --prefix frontend run build` | Passed; production frontend generated |
| `.venv/bin/python -W error::DeprecationWarning -m unittest discover -s backend/tests -v` | 264 passed in 13.7 seconds; no skips; prepared PATH includes portable PowerShell |
| `npm --prefix frontend run test:browser` | 162 passed in approximately 5 minutes; Chromium, one worker, no retries |
| Additional light/dark visual recapture | Six cases, 375/800/1280 px; animations disabled and theme readiness checked |
| `.venv/bin/python -m pip check` | No broken requirements |
| `pip_audit -r backend/requirements-dev.txt -r backend/requirements-build.txt` | No known vulnerabilities in Linux-resolved requirements |
| `npm --prefix frontend audit --omit=dev` | Zero production vulnerabilities |
| Full JavaScript audit | Three moderate development-only CSS-toolchain advisories: postcss-nested, postcss-selector-parser, tailwindcss; unchanged dependencies |
| `.venv/bin/python scripts/check-workflows.py` and `actionlint` | Passed |
| `pwsh -NoProfile -File scripts/check-powershell.ps1` | Syntax/static guards passed; writable XDG cache/config/data directories supplied |
| `node scripts/sync-lucide-catalog.mjs --check` | 1,447 catalog entries verified |
| `git diff --check` and local documentation links | Passed |

The startup regression was first run against the original implementation and failed,
then passed after the fix. The initial broad browser run exposed older tests that
implicitly assumed Role Lookup as the root route; those now navigate explicitly.
Existing behavioral checks remain; the final full run passed with no retries.
There are four new backend and fifteen new browser regressions in total. Test output
also includes the harmless Playwright NO_COLOR/FORCE_COLOR environment notice.

Visual review compares light/dark screenshots and desktop/tablet/mobile layouts of
the Dashboard, directory filters, unified profiles (including matched directory
records and manager controls), and compact/expanded release controls. Tables retain
contained horizontal scrolling at narrow widths; there is no viewport overflow in
the new visual cases. These are manual screenshot comparisons and geometry checks,
not pixel-baseline regression assertions. The final six visual cases capture five
screens each, including both collapsed and expanded Release Roles filters.
Screenshots remain in ignored Playwright output and the external workspace directory
`/workspace/sap-lens-dev/consolidation-visual-final`; they are not shipped assets.

All data used is synthetic. No real SAP or employee records, local settings,
screenshots or logs are committed. Linux dependency auditing respects platform
markers; Windows-only dependency resolution/auditing remains pending on Windows.

Native Windows/WebView2, packaged EXE, real file-picker and UNC-share tests are
unavailable in this Linux environment. Chromium and synthetic packaging tests do
not establish native desktop compatibility. No remote Windows build, tag, release,
signing or repository-setting change is part of this task. The user explicitly
authorized pushing the completed commit with `[skip ci]`; no workflow dispatch is
authorized. Production code dependencies, desktop settings compatibility and
existing optional-feature boundaries are preserved.

## Changed files


Backend publication/status: configuration revision, consistent Dashboard source state, shared snapshot coverage and regression tests.

- [backend/configuration_routes.py](../backend/configuration_routes.py)
- [backend/routers/dashboard.py](../backend/routers/dashboard.py)
- [backend/routers/employees.py](../backend/routers/employees.py)
- [backend/tests/test_loading_publication.py](../backend/tests/test_loading_publication.py)

Frontend runtime, layout and navigation:

- [frontend/src/App.tsx](../frontend/src/App.tsx)
- [frontend/src/api/configuration.ts](../frontend/src/api/configuration.ts)
- [frontend/src/components/Access/EmployeeEnrichment.tsx](../frontend/src/components/Access/EmployeeEnrichment.tsx)
- [frontend/src/components/Access/ReleaseRoles.tsx](../frontend/src/components/Access/ReleaseRoles.tsx)
- [frontend/src/components/Access/UserAccess.tsx](../frontend/src/components/Access/UserAccess.tsx)
- [frontend/src/components/Access/UserProfile.tsx](../frontend/src/components/Access/UserProfile.tsx)
- [frontend/src/components/Dashboard.tsx](../frontend/src/components/Dashboard.tsx)
- [frontend/src/components/Layout/AppLayout.tsx](../frontend/src/components/Layout/AppLayout.tsx)
- [frontend/src/components/RoleDetail/RoleDetailPanel.tsx](../frontend/src/components/RoleDetail/RoleDetailPanel.tsx)
- [frontend/src/components/RoleList/RoleList.tsx](../frontend/src/components/RoleList/RoleList.tsx)
- [frontend/src/components/Settings/SettingsView.tsx](../frontend/src/components/Settings/SettingsView.tsx)
- [frontend/src/components/Shared/AssignmentDateFilters.tsx](../frontend/src/components/Shared/AssignmentDateFilters.tsx)
- [frontend/src/hooks/useRecordNavigation.ts](../frontend/src/hooks/useRecordNavigation.ts)
- [frontend/src/hooks/useViewHistory.tsx](../frontend/src/hooks/useViewHistory.tsx)
- [frontend/src/index.css](../frontend/src/index.css)
- [frontend/src/lib/directoryDisplayName.ts](../frontend/src/lib/directoryDisplayName.ts)
- [frontend/src/main.tsx](../frontend/src/main.tsx)
- [frontend/src/state/ApplicationData.tsx](../frontend/src/state/ApplicationData.tsx)

Browser regressions and explicit navigation/label updates for the new default and unified profile (no tests removed):

- [frontend/tests/consolidated-role-ui.spec.ts](../frontend/tests/consolidated-role-ui.spec.ts)
- [frontend/tests/dashboard-user-transactions.spec.ts](../frontend/tests/dashboard-user-transactions.spec.ts)
- [frontend/tests/data-aware-ux.spec.ts](../frontend/tests/data-aware-ux.spec.ts)
- [frontend/tests/desktop.spec.ts](../frontend/tests/desktop.spec.ts)
- [frontend/tests/employee-directory.spec.ts](../frontend/tests/employee-directory.spec.ts)
- [frontend/tests/enterprise.spec.ts](../frontend/tests/enterprise.spec.ts)
- [frontend/tests/investigation-filter-refinement.spec.ts](../frontend/tests/investigation-filter-refinement.spec.ts)
- [frontend/tests/investigation-ux.spec.ts](../frontend/tests/investigation-ux.spec.ts)
- [frontend/tests/live-filters-polish.spec.ts](../frontend/tests/live-filters-polish.spec.ts)
- [frontend/tests/loading-consolidation.spec.ts](../frontend/tests/loading-consolidation.spec.ts)
- [frontend/tests/role-visuals.spec.ts](../frontend/tests/role-visuals.spec.ts)
- [frontend/tests/user-role-export.spec.ts](../frontend/tests/user-role-export.spec.ts)
- [frontend/tests/ux.spec.ts](../frontend/tests/ux.spec.ts)

Documentation:

- [docs/DASHBOARD.md](../docs/DASHBOARD.md)
- [docs/EMPLOYEE_DIRECTORY.md](../docs/EMPLOYEE_DIRECTORY.md)
- [docs/INVESTIGATION_FILTERS.md](../docs/INVESTIGATION_FILTERS.md)
- [docs/UI_CONSOLIDATION_VALIDATION.md](../docs/UI_CONSOLIDATION_VALIDATION.md)
