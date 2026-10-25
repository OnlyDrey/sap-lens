# Catalogue and assignment investigation filters

This refinement follows the completed optional Employee Directory implementation.
It preserves the three independent CSV sources and feature/diagnostic behavior.
No additional data source, classification profile or SAP authorization inference
is introduced.

## Role Catalogue

The transaction input is the only catalogue control that adds exact transaction
filters. Typing filters live; Enter commits a normalized uppercase chip. Duplicate
chips are prevented, individual chips remain removable, and empty-input Backspace
removes the last chip. Matching is exact, case-insensitive and whitespace-trimmed.

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

Release list/table/matrix mode, filters, sort and pagination remain in the owning
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
hidden transaction filter. The active evidence toolbar has one clear action; it
clears role/T-code evidence while preserving search, group, sort and expiry controls.
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
all directory controls, including sort, direction and expiry; the narrower evidence
**Clear filter** still removes only role/T-code evidence, preserving the other
controls. Live typing, chip/AND/OR semantics and export evidence are unchanged.

Release Roles uses four-column classification and assignment controls with the same
responsive breakpoints. Status and the compact date button stay with assignment
filters. Sorting and Descending sit together in the primary filter container. The date button is outside it near result count and Table/Matrix controls. **Clear filters**
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

## Completed local validation — 2026-10-23

Recovered state: `work` at `b7e204e`, with the optional Employee Directory work
preserved and completed before these filter refinements. Its first stable local
commit is `465272a` (236 backend / 113 browser tests at that checkpoint).

Final combined implementation checks executed in the Linux workspace:

| Command / check | Actual result |
| --- | --- |
| `npm ci` in `frontend` | Passed; manifests and lockfile unchanged |
| `npm run check:types` | Passed |
| `npm run build` | Passed; production assets generated |
| `python -W error::DeprecationWarning -m unittest discover -s backend/tests -v` | 246 passed; no skips; includes API, persistence, migrations, repository/privacy, synthetic PE/archive and launcher-boundary regressions |
| `npm run test:browser` | 126 passed, approximately 4.2 minutes |
| Additional final light/dark visual cases | 4 passed; 12 filter/table screenshots recaptured with CSS transitions disabled |
| `python -m pip check` | No broken requirements |
| `pip_audit -r backend/requirements-dev.txt -r backend/requirements-build.txt` | No known vulnerabilities in Linux-resolved requirements, including desktop/build layers |
| `npm audit --omit=dev` | Zero production vulnerabilities |
| Full JavaScript audit | Seven unchanged development-tool advisories: five high, two moderate; no dependency upgrades or suppressions |
| `python scripts/check-workflows.py` and actionlint | Passed |
| `pwsh -NoProfile -File scripts/check-powershell.ps1` | Syntax/static guards passed; no Windows packaging executed |
| `node scripts/sync-lucide-catalog.mjs --check` | All 1,447 catalog entries verified |
| `git diff --check` / staged whitespace check | Passed |

Visual review covered Features/Data Sources and filtered catalogue, release tabs
and role details in light/dark themes at 800 and 1280 pixels. Tests additionally
verify keyboard horizontal table scrolling, focusable controls, filtered global
navigation across the 100-role page boundary, source isolation, matching exports,
unknown dates and unparsed release roles. Earlier assertions were scoped to the
same original behavior when controls/labels intentionally changed; no test was
removed or weakened to conceal a functional failure.

README branding, canonical assets, package/dependency manifests, application
versioning, packaging scripts and workflows are unchanged. No pushes, workflow
dispatches, tags, releases or Windows artifacts were created. Actual Windows EXE,
WebView2, file-picker and UNC validation remain pending; Linux unit/browser checks
are not substitutes. Windows-only dependency resolution/auditing also remains part
of that native validation.

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
