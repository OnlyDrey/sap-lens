# Catalogue and assignment investigation filters

This refinement follows the completed optional Employee Directory implementation.
It preserves the four independent CSV sources and feature/diagnostic behavior.
No additional data source, classification profile or SAP authorization inference
is introduced.

## Role Catalogue

The transaction input is the catalogue control that adds transaction
filters. Typing filters live; Enter commits a normalized uppercase chip. Duplicate
chips are prevented, individual chips remain removable, and empty-input Backspace
removes the last chip. Ordinary selected codes match exactly, case-insensitively and whitespace-trimmed.
Explicit `*` patterns match complete code fields as described below.

The default operator is **AND**: every selected transaction must exist in the
role's aggregate transaction mappings, even across different single roles/CSV
rows. **OR** matches at least one. With multiple codes, a compact operator switch
appears before the chips. No/single-code searches do not depend on the operator.
The operator is specific to the catalogue; existing User Details and sidebar
multi-code searches retain their established OR behavior.

Role search now examines only role name and role description. It does not search
transaction codes or module labels. Use the dedicated transaction control for
codes. The legacy singular `tcode` API prefix lookup remains available for API
compatibility, but is no longer used by catalogue text search.

SAP area pills are multi-select: selected areas combine with OR. Area, text and
transaction categories combine with AND. All clears specific areas. Module names,
icons, colors, counts and saved filter-availability preferences are preserved.

There is one **Clear all filters** action, including with only a live transaction
filter active or no matching results. It clears text, transactions and areas,
restores AND, resets pagination and restores **Name A to Z** sorting. Comparison
selections and independent User Access/Release filters remain untouched. Clearing
individual chips only removes those codes.

Catalogue detail Previous/Next uses the entire filtered/sorted role list already
loaded by the catalogue, crossing result-page boundaries without another large
fetch. Closing the sidebar preserves filters and the originating list page;
browser history preserves role identities. Removed/nonmatching roles show a
navigation warning instead of inventing neighbours.

## Assignment dates and tables

User Details and Release Roles share inclusive filters for:

- Valid from: earliest and latest dates.
- Valid to: earliest and latest dates.
- **Include assignments without end date** (checked by default).

A compact calendar/filter button lives in the assignment toolbar, below the unified user profile. The four optional bounds are inside collapsed
**Advanced interval filtering**; the missing-end checkbox remains a quick control.
The expandable controls use Norwegian
`DD.MM.YYYY` text entry and an integrated Norwegian calendar. Draft edits do not
filter until **Apply date filters**. Invalid dates/reversed ranges remain editable.
Cancel discards drafts; Clear resets date filters; applied date chips can each be
removed independently. The broader Clear action also works with date-only filters.

Start/end bounds are inclusive and compare source assignment dates, never account
validity or import timestamps. A missing start cannot satisfy an active start bound.
With the checkbox checked, genuinely missing ends are included even with end bounds;
unchecking excludes them, without turning them into active assignments. The real SAP
maximum `31.12.9999` obeys end bounds and is never treated as missing. No date bound
changes existing status interpretation. Filters apply before pagination/counts,
release facets and matrix cells; CSV exports freeze the same predicates.

The existing validity calculation is deliberately preserved: a known past end
proves expiry even if the start is missing, and a known future start proves a
future assignment even if the end is missing. Otherwise an incomplete interval
is unknown; it is never silently assumed active. Fully specified boundaries are
inclusive. Norwegian display dates use `DD.MM.YYYY`; API/CSV dates remain ISO and
filtering does not introduce timezone conversion.

Dates are applied on the backend before counts, pagination and navigation. Release
facets and matrix counts use the same predicate. Filtering does not modify source
records or diagnostic dataset-health metrics. User CSV export carries exactly the
same frozen date/transaction/status filters, retaining generation/count/date and
spreadsheet-formula protections.

User Details has separate business and release table structures. Only the release
tab shows Type, Release group and Release strategy; it omits Catalogue match.
Unknown/unparsed release roles remain visible. Business and combined-role views
retain meaningful catalogue mapping evidence. Both tables split Valid from and
Valid to.

An exact release role's details place its full copyable name, server-parsed type,
group, strategy and filtered distinct-user/assignment counts in the header. The
assignment table shows copyable SAP usernames, group, separate dates, assignment
validity and user navigation. It omits repeated role metadata and account/lock
evidence. Matrix drill-down may span several roles, so it retains a role column
where needed to preserve attribution. Account and lock evidence remain in User
Details. Assignment badges explicitly say Active, Future or Expired assignment,
or Unknown validity; none proves effective SAP authorization.

Release list/table/matrix mode, filters and sort remain in the owning
view while details and user investigations are opened. Changing dates in release
details updates the same filtered navigation context used by the origin list.

## Editable User Access transactions and compact catalogue search

User Access uses the shared live transaction input with Enter-to-save chips,
case normalization, duplicate prevention, removable chips and AND by default.
AND requires every code to have retained evidence for the **same SAP user**; different
relevant assigned roles may explain different codes. OR needs any selected code.
Username search, group, role evidence and expiry rules are combined with this set
before counts, sorting, pagination and global detail navigation. Relevant-role counts
use assignment evidence for the selected codes. Identical users never count twice.
Unmapped or ambiguous catalogue links cannot supply transaction evidence.

Incoming single-code evidence seeds the same editable chip state, not a second
hidden transaction filter. Role and transaction evidence appears as individually removable filter chips.
Removing a chip preserves unrelated search, group and sort state; Clear filters
resets the whole directory panel.
Clearing all codes restores AND. The legacy `tcode` API query remains supported;
repeated `tcodes` and `transaction_mode=and|or` provide multi-code directory filtering.
When no catalogue is loaded, transaction filtering cannot be evaluated and is not
applied; the UI explains this while ordinary directory search/group filters remain
usable. Disabling User–Role Mapping blocks assignment APIs and unmounts their views.
Role-derived evidence remains distinct from effective SAP authorization.

Role Lookup places name/description search and exact transaction search in a shared
70/30 desktop row, retaining sorting. At 800 pixels and below they stack. Selected
chips sit below, with the shared AND/OR selector before them. SAP area multi-selection
and Clear all filters keep their previous semantics. Dashboard owns the former KPI
row; see [Dashboard and shared notifications](DASHBOARD.md).

## Responsive directory and release controls

User Access places search, SAP User Group, sorting (with Descending directly below)
and live transaction filtering in one four-column container. It becomes two columns
below 1100 pixels and one below 640. The explicit **Clear filters** action resets
all directory controls, including sort, direction and expiry; individual chips remove only their own filter. Live typing, chip/AND/OR semantics and export evidence are unchanged.

Release Roles uses four-column classification and assignment controls with the same
responsive breakpoints. Status and the compact date button stay with assignment
filters. Sorting and Descending sit together in the primary filter container. The date button is inside the main filter panel. **Clear filters**
restores the normal currently-valid view and resets advanced intervals/sort; no date
capability or missing/SAP-maximum-date distinction has been removed. Assignment
filters do not affect profile information or account status.

## API additions

`GET /api/roles` accepts repeated `function_keys` (OR) and
`transaction_mode=and|or` (default AND) with repeated exact `tcodes`.
The legacy `function_key` and `tcode` parameters remain supported.

`GET /api/access/users/{username}`, `/releases`, `/release-options` and
`/release-assignments` accept `valid_from_min`, `valid_from_max`, `valid_to_min`,
`valid_to_max` (ISO dates), plus `include_missing_end=false` to exclude missing ends (default true). Omit empty bounds. Legacy `open_ended=only|exclude` remains accepted by the API for compatibility but is no longer exposed in the UI.
Invalid ranges return 422. `/release-assignments` returns `role_info` from the
existing strict backend parser when an exact role is requested.

## Validation boundaries

Synthetic backend/browser regressions cover exact AND/OR role matching across
mapping rows, multi-area composition, text separation, scoped reset, date ranges,
missing/open-ended values, filtered counts/navigation/export, dedicated tables,
copy/navigation controls and light/dark responsive layouts. Existing CSV,
Employee Directory, feature and diagnostics suites remain required. Windows,
WebView2 and packaged-EXE verification must still run on Windows before release;
Linux checks do not establish native compatibility.

Employee Directory import/clear refreshes enrichment queries and settings only;
it does not reset catalogue filters, comparison selections or the SAP snapshot
generation. Its screenshot output uses Playwright's per-test directory on both
Windows and Linux rather than a hardcoded cloud path.

## Datepicker and grouped intervals

Advanced bounds are grouped into **Valid from — Assignment start date** (Start
date from/to) and **Valid to — Assignment end date** (End date from/to). Their
original API keys, inclusive comparisons, missing-end checkbox and SAP maximum-date
rules are unchanged. Apply/Clear/Cancel and individual active chips retain their
scope; only assignment records are affected.

The Norwegian calendar now renders in a floating portal above the application
rather than expanding the filter panel. It follows viewport scroll/resize and
chooses above/below placement, with bounded scrolling on short displays. It uses
Monday-first Norwegian month/weekday labels and DD.MM.YYYY manual entry. Arrow keys
navigate dates across month boundaries while staying inside years 0001–9999;
Enter/Space selects the focused day, Escape returns focus to the trigger, and an
outside click dismisses without stealing the new focus. Calendar controls keep
four-digit years visible, including the maximum SAP date.

Role Lookup places role/T-code search side by side and sorting beside the result
count below. Module pills remain below search. Release Roles uses four primary
classification controls plus username, role, status and sort in its second row;
direction stays below sort. Four/two/one layouts retain existing live transaction
chips, filter state, date semantics and contained table scrolling.


## Compact investigation controls

User Directory has a catalogue-backed role selector searchable by identifier or
description. It preserves the existing single-role exact/catalogue-pattern
association, combined with other directory controls. Multiple-role semantics are
not introduced. Role, user-group and user-search chips remove only their own
filter; transaction chips retain their existing AND/OR mode. Clear filters resets
the whole directory panel. Saved definitions retain the original `role` field.

Account Review sorting, direction and export belong to its filter panel. Compare
Users sorting belongs alongside its comparison filters. Release Roles keeps date
controls inside its primary filter panel and places optional user-group comparison
in a separate secondary toolbar. Date bounds and missing-date semantics are
unchanged.

## Shared transaction input interaction


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


## Live transaction scope


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

## Literal SAP wildcard search

Applicable user, role, description, employee, comparison and release text searches
accept `*` for zero or more characters. Patterns are case-insensitive and anchored
to a complete field: `ME*` starts with ME, `*23N` ends with 23N, `*ME*` contains ME,
and `ME*23*` requires ME before 23. Multiple stars are supported. Other regex or
shell metacharacters are literal; `?`, brackets and dots do not become operators.
Plain text retains contains search; selected transaction codes remain exact unless
an explicit star is present. Empty searches leave the dataset unrestricted.

Transaction AND/OR combines each selected pattern's matching role set. Expanding
`ME*` does not require every individual matching transaction in AND mode. Evidence
and exports use those same sets. A role-derived T-code remains mapping evidence,
not proof of effective SAP authorization. Internal role joins and identity/email
matching do not use this search matcher.

Saved Filters store the original search/pattern values and re-evaluate current
validated data. Sorting, pagination, individual removal and Clear filters remain
available. Dashboard assignment-count drilldowns add a removable count-band filter
(`0`, `1–5`, `6–20`, `21+`); it uses the same distinct currently-valid business/release
role calculation as the dashboard and is included in saved filters and exports.

The Release Roles list renders all matching role summaries without pagination,
from one validated backend snapshot. Matrix and assignment-detail semantics are
unchanged; local table scrolling remains available where needed.

Release Roles initially opens in Matrix view, followed by Table in the view
switcher. Changing filters preserves the selected view in the mounted investigation.
Both views export the same filtered assignment set.
