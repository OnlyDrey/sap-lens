# Live transaction filters and evidence presentation

## Shared interaction

User Details, the Role Details sidebar and Role Lookup use the same
`TransactionFilter` component. Filtering follows typed text after a 180 ms debounce;
there is no Search button. Codes are trimmed and matched case-insensitively.

- Enter saves the current code as a removable chip and clears/refocuses the input.
- Duplicate chips are ignored regardless of case.
- Backspace in an empty input removes the final chip.
- The draft input remains active alongside saved chips.
- User Details/sidebar codes match with **OR**. The catalogue defaults to **AND**, with an explicit AND/OR switch for multiple codes. Empty filters restore normal results.
- User Details/sidebar Clear filter removes only transaction chips/draft text. The catalogue has one Clear all filters action; individual chips remain removable.
- Up to 20 saved chips plus one draft (128 characters each) are supported.

The shared secondary Clear filter button has a FilterX icon, a subtle danger hover
and a visible keyboard focus ring. Clear selection in the comparison bar reuses
that pattern and still clears only comparison selections.

## Scope and data correctness

User Details searches only the selected user's supported ZC/ZO assignments, with
its current role-family and validity filters. CSV export waits until live filters
have settled and exports all matching pages, including active uncommitted text.
Generation/count/date checks, formula protection and the native save contract are
unchanged. Source dates in CSV remain ISO, including `9999-12-31`.

Sidebar filters examine all single-role transaction mappings, including collapsed
sections. Every matching section is shown and opened; matching rows are highlighted.
Clearing restores normal expansion states. Changing the opened role resets chips
and draft text. No source relationship or effective authorization is invented.

Role Lookup filters catalogue summaries through the import-time exact transaction
index. Transaction codes default to AND across the full role, with optional OR. Selected SAP areas combine with OR; area, role-name/description text and transaction categories combine with AND. Text search no longer examines T-codes or module labels. Sorting, 100-role pagination and comparison
selections remain intact. Roles without supplied transaction mappings cannot be
confirmed as matches; the UI states that source completeness is unknown. The
existing `tcode` API retains its legacy behavior for compatible callers.

The authenticated existing user-detail and role-list APIs now accept repeated
`tcodes` query parameters. Requests are normalized/deduplicated and bounded to 21
values of at most 128 characters each. User assignment filtering happens before
pagination, preserving distinct intervals and groups. No new export/upload API,
direct SAP connection or remote data service is introduced.

## Active evidence in User Directory

Transaction-to-user and role-to-user drill-downs show an **Active evidence filter**
summary, with a Filter icon and a compact Transaction/Role badge. Clear filter is
aligned to the right and removes only role/T-code evidence. Directory text search,
SAP User Group, sort key/direction and Show expired assignments remain unchanged.
Pagination follows the existing reset behavior when the result set changes.
The summary disappears entirely when there is no evidence filter. Existing
investigation navigation and history behavior remain intact.

## Dates and status badges

Visible dates use `nb-NO`, `dd.MM.yyyy`. Timestamps use `dd.MM.yyyy HH:mm`, or
`HH:mm:ss` when explicitly requested by detailed diagnostics. Date-only SAP values
are validated and formatted in UTC without conversion to the machine's timezone.
Offset-bearing timestamps display in local time; unzoned local timestamps are not
silently marked UTC. Missing/invalid values have explicit neutral fallbacks.

API payloads, structured diagnostics, machine-readable logs, source configuration
and CSV export date contracts are unchanged. The visible formatting is shared by
User Details, validity tables, source metadata, diagnostics and refresh timestamps.

Data & storage uses a shared SourceBadge: successful loads are green, failures red,
loading informational, and unavailable/unloaded sources neutral. A last successful
load still does not prove current file availability; availability/last-attempt text
and retained-previous-data warnings remain separate and unchanged.

Shared native select presentation reuses the existing Settings chevron and padding
rules. Role cards use secondary View details buttons; action clicks retain event
isolation and the existing role-detail destination. No packaging or build
prerequisite changes are part of this work.

## Validation

Synthetic regression tests cover multi-code OR semantics, chips and keyboard
interaction, draft-inclusive CSV export, scope/status interactions, catalogue
filters, evidence clearing without losing other controls, status transitions,
Norwegian dates/sentinel years/local timezones, source availability distinctions,
and responsive light/dark screenshots. Existing regression scenarios remain and
have been updated for live interaction rather than removed.

Actual Windows/WebView2, UNC access and packaged-EXE validation require a Windows
machine. Browser tests and native bridge mocks do not replace those checks.

## Implementation inventory

| Area | Modified or added files |
|---|---|
| API filtering and regression tests | `backend/transaction_filters.py`, `backend/routers/access.py`, `backend/routers/roles.py`, `backend/tests/test_user_access.py` |
| Client requests and export | `frontend/src/api/access.ts`, `frontend/src/lib/accessExport.ts` |
| Shared controls and formatting | `frontend/src/components/Shared/TransactionFilter.tsx`, `frontend/src/components/Shared/ClearFilterButton.tsx`, `frontend/src/components/Shared/Select.tsx`, `frontend/src/components/Shared/SourceBadge.tsx`, `frontend/src/lib/dateFormat.ts` |
| User/release investigation | `frontend/src/components/Access/UserAccess.tsx`, `frontend/src/components/Access/ReleaseRoles.tsx`, `frontend/src/components/Access/Shared.tsx` |
| Catalogue and role sidebar | `frontend/src/components/RoleList/RoleList.tsx`, `frontend/src/components/RoleList/RoleCard.tsx`, `frontend/src/components/RoleDetail/RoleDetailPanel.tsx` |
| Settings and refresh display | `frontend/src/components/Settings/Controls.tsx`, `frontend/src/components/Settings/Diagnostics.tsx`, `frontend/src/components/Settings/SourceStatus.tsx`, `frontend/src/components/Layout/AppLayout.tsx` |
| Styles | `frontend/src/index.css` |
| Browser coverage | `frontend/tests/live-filters-polish.spec.ts`, `frontend/tests/access-investigation.spec.ts`, `frontend/tests/consolidated-role-ui.spec.ts`, `frontend/tests/user-role-export.spec.ts` |
| Documentation | `docs/LIVE_FILTERS.md`, `docs/API_REFERENCE.md`, `docs/ACCESS_INVESTIGATION.md`, `docs/ROLE_PRESENTATION.md` |

## Local validation results (2026-10-23)

- `npm ci`, `npm run check:types`, and `npm run build`: passed.
- Backend tests with deprecations treated as errors: **216 passed**, no skips,
  with the prepared Python environment and portable PowerShell on PATH.
- Full browser regression suite: **105 passed**. After the final scoped compact-
  layout adjustment, all **18 targeted live-filter and toolbar tests passed**.
- `python -m pip check`: passed. Python requirements audit and production npm
  audit found no known vulnerabilities. Seven existing JavaScript development-
  tooling advisories remain (five high, two moderate); no dependencies changed.
- Workflow contracts, actionlint, PowerShell syntax/static guards, Lucide catalogue
  verification and `git diff --check`: passed.
- Twenty synthetic-data screenshots cover User Details, active evidence summaries,
  Role Lookup/card/comparison buttons, sidebar chips and source-status cards in
  light/dark themes at 800/1280 pixels. Screenshots were visually inspected.
- No native Windows/WebView2 or UNC validation was performed. Windows packaging,
  README branding, application version, release settings and build prerequisites
  were not changed. No push, workflow dispatch, Windows build or release occurred.

For current catalogue reset, assignment dates, dedicated release tables and navigation contracts, see [investigation filters](INVESTIGATION_FILTERS.md).
