# Operational UI, settings and account-review validation

## Baseline and implementation

Started with clean `work` at `4501b961aeb31be6e9c96b9bca6dd5eba1c480db`, matching
fetched `origin/work`. Existing work was preserved; no reset/rebase or unrelated
packaging-format, workflow, version, branding or dependency changes were made.
The existing package privacy denylist and Git ignore rules explicitly exclude the
new private account-review annotation file.

- Dashboard retains grouping while prioritizing four operational KPIs. Assignment
  expiry/future totals are under Access Lifecycle; match count/percentage/progress
  are Data Quality. Review KPIs navigate to supported filtered account evidence.
- Role Lookup keeps role/T-code search adjacent, sorting with the secondary result
  count, and existing live multi-code/SAP-area behavior.
- User Details has a compact SAP-only name/email header and SAP Identity, Account
  Status and Organization groups. AD username/Site are not primary profile fields.
  Shared account pills use Valid/Invalid/Unknown independently of lock/AD state.
  Raw SAP calculations, distinct source records and assignment evidence remain.
- Unique manager SAP identities make the compact manager card navigable, preferring
  the unambiguous SAP name. Missing/ambiguous identities remain non-clickable.
  Conservative directory-only name formatting preserves compound/ambiguous names.
- Release sorting/direction returns to its four-column filters. The date control is
  outside that container with results/view controls. Advanced start/end intervals
  are grouped; filtering keys, inclusive bounds and missing/max dates are unchanged.
- The Norwegian calendar is a portal overlay with viewport positioning, measured
  height, outside/Escape dismissal, focus return, Monday-first labels and bounded
  keyboard navigation through years 0001–9999. It does not expand parent layout.
- Settings groups General, Data & Modules and Application, retaining internal IDs,
  draft/cancel/import behavior and direct source links. Health uses concise summaries
  plus expandable technical reports; About owns version/build/runtime information.
- Account Review is under User Access, not another primary page. It adds independent
  evidence findings, configurable unlicensed-group classification, filtered/sorted
  pagination, safe CSV export and private persistent review annotations with stale
  evidence detection. No automatic SAP modifications or license-savings estimates.

Details: [Account Review](ACCOUNT_REVIEW.md), [Settings and recovery](CONFIGURATION.md),
[Dashboard](DASHBOARD.md), [Employee Directory](EMPLOYEE_DIRECTORY.md),
[date/transaction filters](INVESTIGATION_FILTERS.md).

## Confirmed persistence and identity findings

“No durable records saved” describes legacy path-only settings. Selecting/applying
a CSV path can yield validated in-memory records without the explicit durable import
confirmation. This differs from feature activation and from source availability.
The existing snapshot mechanism is reused by **Save durable directory snapshot**,
which validates settings revision/digest, stages the snapshot, saves its ID atomically
and preserves accepted records/import time. It never requires rereading a missing
original CSV. Failed writes retain original settings and in-memory data.

Account Review and profiles require reliable directory evidence before showing AD
Disabled or mismatch warnings. Multiple SAP identities sharing an email now produce
ambiguous enrichment consistently across profile, coverage and review; no identity
is guessed from AD username or name. License-group classification remains independent
of security findings. Reviewer identity is explicitly self-declared local annotation,
not authenticated approval. Corrupt annotation storage is retained and reported;
core investigation and Dashboard remain available.

New backend tests cover missing-source recovery and review-file reads in fresh
Python subprocesses, as well as cleared-cache restoration. Existing subprocess
restart, snapshot integrity/privacy and migration suites also remain required.
These are Linux restart checks, not a claim of native Windows validation.

## Executed validation

Environment: Linux, Python 3.12.14, Node 24.19.0 and Chromium 154.0.8037.57.
Commands ran from the repository root unless specified. Backend PATH includes the
prepared virtualenv and portable PowerShell; writable XDG cache/config/data paths
were supplied for PowerShell checks.

| Command/check | Actual final result |
| --- | --- |
| `npm --prefix frontend ci --cache /workspace/.npm-cache` | Passed; existing manifests/lockfile unchanged |
| `npm --prefix frontend run check:types` | Passed |
| `npm --prefix frontend run build` | Passed; final Vite production build completed in 2.38 seconds |
| `.venv/bin/python -W error::DeprecationWarning -m unittest discover -s backend/tests -v` | 281 passed, no skips, 15.7 seconds |
| `npm --prefix frontend run test:browser` | 175 passed, zero retries, approximately 5.5 minutes |
| Focused Account Review + Dashboard browser suites | 24 passed in 42.7 seconds; final visual recapture plus workflow regressions |
| `.venv/bin/python -m pip check` | No broken requirements |
| `pip_audit -r backend/requirements-dev.txt -r backend/requirements-build.txt` | No known vulnerabilities in Linux-resolved requirements |
| `npm --prefix frontend audit --omit=dev` | Zero production vulnerabilities |
| Full JavaScript audit | Three moderate development-only CSS-toolchain audit entries remain (postcss-selector-parser, postcss-nested, tailwindcss); no upgrades/suppressions |
| `.venv/bin/python scripts/check-workflows.py` and `actionlint` | Passed trigger, permissions, concurrency, graph and artifact contracts |
| `pwsh -NoProfile -File scripts/check-powershell.ps1` | Syntax/static checks passed; no Windows packaging executed |
| `node scripts/sync-lucide-catalog.mjs --check` | 1,447 catalog entries verified |
| Repository privacy and synthetic Windows package verifier tests | Passed, including rejection of the new private annotation filename |
| `git diff --check`, staged whitespace and local documentation links | Passed |

There are 17 new backend tests and 13 new browser cases. Existing tests were not
removed; intentional status/field/sidebar changes have explicit updated assertions.
The tests additionally cover filtered export across generations, native-save bridge
contract, review-editor focus/return, and manager Back navigation with pre-existing
role evidence and review filter/sort state. A calendar reopening focus regression
was reproduced before its fix, then passed along with cross-month keyboard traversal
and Back/Forward dismissal. Review cache tests verify page reuse, invalidation,
calendar-day evaluation and release of retired full SAP snapshots. Dashboard and
Account Review agree on counts including stale annotations; corrupt review storage
does not fail core lookup or the other Dashboard metrics.

Screenshots were captured in light/dark themes at 375, 800 and 1280 pixels and
manually reviewed across Dashboard, account review, unified profiles, compact release
filters, floating calendars and grouped Health settings. Existing catalogue/long-role,
combobox, theme and table visual suites also passed. Checks cover contained table
scrolling, viewport overflow, popup bounds, keyboard focus and Norwegian maximum
SAP dates. These are manual screenshot comparisons/geometry checks, not a claim
of comprehensive pixel-baseline regression coverage. Artifacts remain ignored under
`frontend/test-results`; no identity screenshots are committed or bundled.

Only synthetic SAP/employee data is used. No user data, runtime configuration,
screenshots, logs or review annotations are committed. Playwright emits the harmless
NO_COLOR/FORCE_COLOR environment notice. Dependency manifests and locks are unchanged.

Native Windows/WebView2, packaged EXE, real file-picker and UNC-share testing are
unavailable in this environment. Existing synthetic PE/archive/privacy and launcher
boundary tests run on Linux; they are not actual Windows package verification.
Windows-only dependency resolution/auditing remains pending on Windows.

The user's standing instruction requires `[skip ci]` until further notice. Delivery
uses that token on the completed commit. No workflow dispatch, Windows artifact,
tag, release, signing change or repository-setting modification is authorized here.

## Changed-file inventory

Repository and packaging privacy guards:

- [.gitignore](../.gitignore)
- [scripts/verify-windows-package.py](../scripts/verify-windows-package.py)

Backend models, review service, APIs, identity consistency, diagnostics and regressions:

- [backend/account_review.py](../backend/account_review.py)
- [backend/config_models.py](../backend/config_models.py)
- [backend/data_loader.py](../backend/data_loader.py)
- [backend/diagnostics.py](../backend/diagnostics.py)
- [backend/employee_directory.py](../backend/employee_directory.py)
- [backend/main.py](../backend/main.py)
- [backend/routers/account_review.py](../backend/routers/account_review.py)
- [backend/routers/dashboard.py](../backend/routers/dashboard.py)
- [backend/routers/employees.py](../backend/routers/employees.py)
- [backend/tests/test_account_review.py](../backend/tests/test_account_review.py)
- [backend/tests/test_repository_privacy.py](../backend/tests/test_repository_privacy.py)
- [backend/tests/test_windows_package.py](../backend/tests/test_windows_package.py)

Frontend shared components, layout, settings, review and navigation:

- [frontend/src/App.tsx](../frontend/src/App.tsx)
- [frontend/src/api/configuration.ts](../frontend/src/api/configuration.ts)
- [frontend/src/components/Access/AccountReview.tsx](../frontend/src/components/Access/AccountReview.tsx)
- [frontend/src/components/Access/EmployeeEnrichment.tsx](../frontend/src/components/Access/EmployeeEnrichment.tsx)
- [frontend/src/components/Access/ReleaseRoles.tsx](../frontend/src/components/Access/ReleaseRoles.tsx)
- [frontend/src/components/Access/UserAccess.tsx](../frontend/src/components/Access/UserAccess.tsx)
- [frontend/src/components/Access/UserProfile.tsx](../frontend/src/components/Access/UserProfile.tsx)
- [frontend/src/components/Dashboard.tsx](../frontend/src/components/Dashboard.tsx)
- [frontend/src/components/RoleList/RoleList.tsx](../frontend/src/components/RoleList/RoleList.tsx)
- [frontend/src/components/Settings/About.tsx](../frontend/src/components/Settings/About.tsx)
- [frontend/src/components/Settings/Diagnostics.tsx](../frontend/src/components/Settings/Diagnostics.tsx)
- [frontend/src/components/Settings/EmployeeDirectory.tsx](../frontend/src/components/Settings/EmployeeDirectory.tsx)
- [frontend/src/components/Settings/SettingsView.tsx](../frontend/src/components/Settings/SettingsView.tsx)
- [frontend/src/components/Shared/AccountStatus.tsx](../frontend/src/components/Shared/AccountStatus.tsx)
- [frontend/src/components/Shared/AssignmentDateFilters.tsx](../frontend/src/components/Shared/AssignmentDateFilters.tsx)
- [frontend/src/components/Shared/EmployeeInformation.tsx](../frontend/src/components/Shared/EmployeeInformation.tsx)
- [frontend/src/components/Shared/InvestigationNavigation.tsx](../frontend/src/components/Shared/InvestigationNavigation.tsx)
- [frontend/src/components/Shared/NorwegianDateInput.tsx](../frontend/src/components/Shared/NorwegianDateInput.tsx)
- [frontend/src/hooks/useViewHistory.tsx](../frontend/src/hooks/useViewHistory.tsx)
- [frontend/src/index.css](../frontend/src/index.css)
- [frontend/src/lib/directoryDisplayName.ts](../frontend/src/lib/directoryDisplayName.ts)
- [frontend/src/state/ApplicationData.tsx](../frontend/src/state/ApplicationData.tsx)

Browser regressions and intentional navigation/label updates:

- [frontend/tests/access-investigation.spec.ts](../frontend/tests/access-investigation.spec.ts)
- [frontend/tests/account-review-refinement.spec.ts](../frontend/tests/account-review-refinement.spec.ts)
- [frontend/tests/dashboard-user-transactions.spec.ts](../frontend/tests/dashboard-user-transactions.spec.ts)
- [frontend/tests/data-aware-ux.spec.ts](../frontend/tests/data-aware-ux.spec.ts)
- [frontend/tests/employee-directory.spec.ts](../frontend/tests/employee-directory.spec.ts)
- [frontend/tests/enterprise.spec.ts](../frontend/tests/enterprise.spec.ts)
- [frontend/tests/investigation-filter-refinement.spec.ts](../frontend/tests/investigation-filter-refinement.spec.ts)
- [frontend/tests/live-filters-polish.spec.ts](../frontend/tests/live-filters-polish.spec.ts)
- [frontend/tests/loading-consolidation.spec.ts](../frontend/tests/loading-consolidation.spec.ts)
- [frontend/tests/navigation-modules.spec.ts](../frontend/tests/navigation-modules.spec.ts)
- [frontend/tests/settings-refinement.spec.ts](../frontend/tests/settings-refinement.spec.ts)
- [frontend/tests/user-role-export.spec.ts](../frontend/tests/user-role-export.spec.ts)
- [frontend/tests/ux.spec.ts](../frontend/tests/ux.spec.ts)

Architecture and usage documentation:

- [docs/ACCESS_INVESTIGATION.md](../docs/ACCESS_INVESTIGATION.md)
- [docs/ACCOUNT_REVIEW.md](../docs/ACCOUNT_REVIEW.md)
- [docs/ACCOUNT_REVIEW_VALIDATION.md](../docs/ACCOUNT_REVIEW_VALIDATION.md)
- [docs/CONFIGURATION.md](../docs/CONFIGURATION.md)
- [docs/DASHBOARD.md](../docs/DASHBOARD.md)
- [docs/EMPLOYEE_DIRECTORY.md](../docs/EMPLOYEE_DIRECTORY.md)
- [docs/INVESTIGATION_FILTERS.md](../docs/INVESTIGATION_FILTERS.md)
