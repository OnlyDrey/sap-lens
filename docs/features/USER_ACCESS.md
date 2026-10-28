# User Access

## Directory and profiles

Enable User–Role Mapping and import its [CSV](../data/CSV_SCHEMAS.md#userrole-mapping).
Search by SAP username, source name/email or group. Sort and paginate the directory;
open a user for SAP identity, Account Status and Organization. SAP CSV is authoritative
for SAP name/email. Optional [Employee Directory](../data/EMPLOYEE_DIRECTORY.md)
enriches title, department, AD status and an unambiguously resolved manager link.
Manager navigation uses exact normalized email, not AD username or name guesses.

User validity, SAP lock and AD state are independent. Missing/conflicting evidence
is Unknown, never implicitly Valid/Unlocked/Enabled. The profile shows source
observations without claiming effective access. Previous/Next spans the filtered,
sorted result set across pages; browser Back preserves investigation context.

## Filters and assignments

Directory search, SAP User Group, catalogue-backed role-name/description selection,
transaction chips, sort/direction and expired-assignment control share one panel.
The role selector preserves the existing single-role association; it does not add
new multi-role AND/OR semantics. Remove individual chips or use Clear filters to
reset the panel. T-codes default to AND across the same user's relevant evidence;
OR is explicit. Unmapped/ambiguous roles cannot supply transaction evidence.

User Details uses All Roles, Business Roles and Release Roles content tabs. All
is the union of supported ZC and ZO assignments, not every technical role.
Exact assigned identifiers remain copyable; catalogue patterns are not assignments.
Distinct validity intervals and groups remain distinct. Expired evidence is hidden
by default; future and unknown intervals are labeled separately. Missing bounds
never automatically mean active. Account validity/lock does not alter assignment dates.

[Assignment date controls](FILTERS.md#assignment-dates-and-tables) belong above the
assignment table and do not filter the profile. Missing ends differ from the real
SAP maximum 31.12.9999. Display is DD.MM.YYYY; API/export comparisons use date-only ISO.

## Investigation and export

Open a matched catalogue role for relationships and transactions. Role or T-code
investigations can return distinct assigned users while retaining all explaining
roles. No catalogue match is shown as Unmapped, not invented transaction access.
Export includes all matching pages with frozen generation/date/filter guards,
spreadsheet protection and original assignment evidence. Desktop uses its native
save bridge; hosted mode downloads through the browser.

Use [Compare Users](COMPARE_USERS.md), [Account Review](ACCOUNT_REVIEW.md) and
[Saved Filters](SAVED_FILTERS.md) for related investigations. Disabling mapping
preserves imports/settings but blocks assignment-dependent results and exports;
Role Lookup remains independently usable.

## Compact assignment investigation

User Details defaults to **Match all (AND)** for selected transaction codes within
each assigned role's aggregate catalogue mappings. Choose **Match any (OR)**
explicitly to broaden that role filter. Zero selected codes leaves assignments
unchanged; one code has identical AND/OR results. Status, role view and date bounds
compose with this filter; export uses exactly the same matching mode and all pages.
The result summary reports matching assignment records. Unresolved mappings remain
a compact warning; explaining source roles belong to each row's Transaction
mapping evidence disclosure. Export scope is available on the export button.

Directory match status opens a modal with actual method, candidates and source
inspection. Ambiguous/missing/unavailable evidence never becomes a confirmed
identity. The SAP Identity, Account Status and Organization profile groups remain
independent of assignment filters.

## Directory assignment CSV export

**Export CSV** beside the result count exports every imported assignment for every
user matching the current directory filters, across all pages. User search, SAP
User Group, role search, selected transactions, AND/OR mode and assignment-validity
settings select the users using the same logic as the directory. The export then
includes their other assignments and future intervals too. Expired assignments are excluded while
**Show expired assignments** is off (the result count and the exported row count follow the same rule); turn it on, or
filter by expired status, to include them. `MATCHED_FILTER`
is Yes only for assignment evidence contributing to the active selection; No
does not imply invalid or unauthorized access. AND transaction matching retains
the directory's existing aggregate role-evidence semantics.

Columns include SAP identity, exact assigned role, assignment dates/status and
release metadata where applicable. Distinct validity intervals are retained. The
file is UTF-8 with BOM, semicolon-separated, quote-escaped and protected against
spreadsheet formulas. Dates use DD.MM.YYYY. No source values are modified.
Catalogue wildcard patterns are never substituted for concrete assigned role
names; existing import validation of assignment names remains unchanged.

The button is disabled for zero assignments or unsettled filters. An in-flight
export is cancelled if filters change; source-generation/day mismatches require
a refresh. Exports remain local and user initiated, using the existing desktop
save dialog or browser download. Each export is bounded to 32 MiB; narrow filters
if this limit is reached.
