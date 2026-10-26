# Directory, feature and investigation workflow validation

> Historical evidence: applies to the source/phase recorded below, not later
> commits. Use the [current documentation index](../../README.md) for instructions.

## Baseline and confirmed cause

Work started on clean `work` at `e1a945b15853619831bc30d96d5c72f5cfc9ce5d`.
Existing work was preserved; no reset, rebase, push, remote workflow, tag, release or
Windows build was performed.

The reported directory state was reproduced with synthetic data before editing:
a confirmed import had available records and a configured source, but the feature
remained disabled. That preference was working as designed; importing did not enable
it. The UI lacked clear confirmation feedback and a direct activation action.
There was also a genuine persistence defect: only the path was saved, while records
lived in memory. Restarting with the source missing lost access to the import.
Missing email values were already accepted, correctly, as data-quality warnings.

## Implemented behavior

- Selection, validation/preview, **Import directory**, and saved feature activation
  are explicit, distinct stages. Import commits immediately; other preferences use
  the existing **Apply settings** control. The Employee Directory source tab does
  not misleadingly label that global preference action “Save and load CSV”.
- Confirmed records use an atomic private per-user snapshot plus settings pointer.
  Source path, persisted records and operational/dependency state are independent.
  Failed replacements preserve the previous import; deleting the active import
  removes its snapshot without touching the original CSV.
- Features contains compact Employee Directory and User–Role Mapping switches,
  availability and configuration links. Detailed import history/data quality lives
  under the employee source tab; technical health remains under Diagnostics.
- User–Role Mapping defaults on for compatibility. Disabled mapping blocks all
  assignment APIs, including export reads, and unmounts assignment views. It retains
  data/configuration and cannot prevent catalogue startup when its source is missing.
  Employee Directory remains independently enabled; unmet email dependencies are
  explained without failing core health.
- SAP User Details uses a compact AD employee card and Reports to. Manager navigation
  requires a unique normalized exact `ManagerMail` match to an actual SAP username.
  Names and AD usernames never select a SAP identity. Missing/ambiguous matches have
  neutral explanations and no broken link. No new manager route or chart exists.
- Date filters belong in assignment toolbars, below profile/account information.
  They use a compact expandable control, Norwegian text/calendar entry, Apply/Clear,
  independent removable chips, ISO comparisons and explicit missing-end inclusion.
  SAP `31.12.9999` remains a real date. Exports, counts and release matrices share
  the backend predicate. Catalogue Role Details contains transaction mappings rather
  than an assignment table; its user investigation links lead to assignment views.
- User Access has one editable T-code state, seeded by incoming evidence, supporting
  live input, chips, AND across a user's relevant assignments, OR and scoped clear.
  Missing catalogue mappings leave ordinary directory filters usable with explanation.
- Dashboard owns the former Role Lookup KPIs and adds reliable access/data-quality
  summaries. Missing/disabled sources return null/Unavailable, not guessed zeroes.
  KPI links reset only their destination's filters and describe unfiltered destinations.
  Role Lookup search inputs share a compact desktop row; areas, sorting and reset remain.
- Shared notifications align with main content, use accessible Lucide X dismissal,
  and retain semantic variants without automatically hiding important feedback.

See [Employee Directory](../../data/EMPLOYEE_DIRECTORY.md),
[Investigation filters](../../features/FILTERS.md) and [Dashboard](../../features/DASHBOARD.md)
for persistence, API, filtering and metric definitions.

## Executed validation

| Command/check | Result |
| --- | --- |
| `npm ci --cache /workspace/.npm-cache` in frontend | Passed; manifests and lockfile unchanged |
| `npm run check:types` and `npm run build` | Passed |
| `python -W error::DeprecationWarning -m unittest discover -s backend/tests -v` with prepared Python/PowerShell PATH | 260 passed, no skips |
| `npm run test:browser` | 147 passed (4.5 minutes) |
| Final focused Employee Directory, assignment-filter and Dashboard browser suites after final labels/placement adjustments | 42 passed (1.0 minute) |
| `python -m pip check` | No broken requirements |
| `pip_audit -r backend/requirements-dev.txt -r backend/requirements-build.txt` | No known vulnerabilities in Linux-resolved runtime/dev/desktop/build requirements |
| `npm audit --omit=dev` | Zero production vulnerabilities |
| Full JavaScript audit | Three moderate development CSS-tool advisories: tailwindcss, postcss-nested, postcss-selector-parser; no upgrades or suppressions |
| `python scripts/check-workflows.py`, actionlint | Passed |
| `pwsh -NoProfile -File scripts/check-powershell.ps1` | All four scripts passed syntax/static guards |
| `node scripts/sync-lucide-catalog.mjs --check` | 1,447 icons verified |
| Updated documentation links and `git diff --check` | Passed |

New regression coverage includes new-process restart with the original directory
CSV removed; persisted feature preferences; import write/commit failures; corrupt
snapshots; legacy path-only failure recovery; missing-email warnings; portable-export
privacy; snapshot clearing/package exclusion; dependency isolation; manager uniqueness;
assignment scope/exports/date boundaries/missing ends; direct and incoming T-codes;
Dashboard metrics/KPI navigation; notifications and responsive controls.

Existing tests were preserved. Layout contracts were updated for four navigation
items and the scoped date controls. The compact grid's boxless semantic transaction
group is measured through its actual input-to-chip extent, retaining the compactness
limit. Existing one-row desktop toolbar alignment was preserved.

## Visual review and remaining limits

Synthetic Chromium screenshots were inspected and compared across light/dark themes
and desktop/narrow widths (375, 800, 1280). Reviewed surfaces include Features,
Employee Directory source status, employee profiles, Norwegian calendars, Role Lookup
search and Dashboard. Tests also verify focus, keyboard dismissal, navigation, table
scrolling and viewport boundaries. The narrow header wraps so its controls do not
obscure navigation. No screenshots or imported records are committed.

Fresh Python processes verify disk persistence on this Linux host. This is **not**
a native Windows application restart test. Actual Windows packaging/EXE smoke tests,
WebView2 rendering, native file dialogs, Unicode Windows paths and authorized UNC
access remain pending. Windows-only dependency resolution/auditing also remains
part of native validation. The package privacy guard was strengthened, not bypassed;
PE/archive integrity regression checks are synthetic and do not imply an EXE build.

No dependencies, README branding, canonical assets, application version, packaging
format, workflow triggers or code signing were changed. SAP role matching/classification
and account-state interpretation retain their existing semantics.

## Files changed

- `.gitignore`
- `backend/assignment_filters.py`
- `backend/cache.py`
- `backend/config_models.py`
- `backend/configuration_routes.py`
- `backend/diagnostics.py`
- `backend/employee_directory.py`
- `backend/main.py`
- `backend/portable_config.py`
- `backend/routers/access.py`
- `backend/routers/dashboard.py`
- `backend/routers/employees.py`
- `backend/tests/test_employee_directory.py`
- `backend/tests/test_investigation_filters.py`
- `backend/tests/test_windows_package.py`
- `docs/features/DASHBOARD.md`
- `docs/archive/validation/DIRECTORY_AND_DASHBOARD_VALIDATION.md`
- `docs/data/EMPLOYEE_DIRECTORY.md`
- `docs/features/FILTERS.md`
- `frontend/src/App.tsx`
- `frontend/src/api/configuration.ts`
- `frontend/src/components/Access/EmployeeEnrichment.tsx`
- `frontend/src/components/Access/MappingAvailability.tsx`
- `frontend/src/components/Access/ReleaseRoles.tsx`
- `frontend/src/components/Access/UserAccess.tsx`
- `frontend/src/components/Dashboard.tsx`
- `frontend/src/components/Layout/AppLayout.tsx`
- `frontend/src/components/RoleList/RoleList.tsx`
- `frontend/src/components/Settings/Diagnostics.tsx`
- `frontend/src/components/Settings/EmployeeDirectory.tsx`
- `frontend/src/components/Settings/SettingsView.tsx`
- `frontend/src/components/Shared/AssignmentDateFilters.tsx`
- `frontend/src/components/Shared/NorwegianDateInput.tsx`
- `frontend/src/components/Shared/Notification.tsx`
- `frontend/src/components/Shared/TransactionFilter.tsx`
- `frontend/src/hooks/useRecordNavigation.ts`
- `frontend/src/hooks/useViewHistory.tsx`
- `frontend/src/index.css`
- `frontend/tests/access-investigation.spec.ts`
- `frontend/tests/consolidated-role-ui.spec.ts`
- `frontend/tests/dashboard-user-transactions.spec.ts`
- `frontend/tests/employee-directory.spec.ts`
- `frontend/tests/investigation-filter-refinement.spec.ts`
- `frontend/tests/live-filters-polish.spec.ts`
- `scripts/verify-windows-package.py`
