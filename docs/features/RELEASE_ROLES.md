# Release Roles

## Source and parsing

Release Roles uses ZO assignments from [User–Role Mapping](../data/CSV_SCHEMAS.md#userrole-mapping);
no extra CSV is required. The strict full-name parser accepts
`ZO:MM:<opaque>:PR_REL_ST_<group>_<strategy>:<opaque>` and the corresponding PO form.
PR is Purchase Requisition; PO is Purchase Order. Group and strategy are alphanumeric;
opaque tokens can include underscore/hyphen. No business meaning is assigned to
opaque scope/suffix tokens. Unknown/malformed ZO identifiers remain visible as Unparsed.
These are configured naming conventions, not universal SAP authorization rules.

## Table and filters

All filters live in the shared filter sidebar (collapsible on wide screens, a drawer on
narrow ones) with [Saved Filters](SAVED_FILTERS.md) as its first section. Filter by SAP
User Group, PR/PO, **Release Area**, **Release Group**, strategy, username, exact role text,
assignment status and [assignment dates](FILTERS.md#assignment-dates-and-tables).
Sort, Descending, Clear filters and the Matrix/Table switch sit in the page toolbar.
Clear filters restores the ordinary currently-valid view.
Date bounds affect assignments before counts, facets and pagination, never user profiles.

**Release Area** is the first character of the Release Group (E2 and E3 give E, N1 gives N,
A2 gives A). It is derived from the loaded data, never configured, and is shown as plain
text (an area is not a SAP module and gets no module badge). Missing or malformed groups
have no area and are never matched by an area selection. Release Area and Release Group
are searchable multi-selects: values inside one filter combine with OR, different filters
combine with AND. The Release Group options narrow to the selected areas, and groups that
fall outside a changed area selection are removed. Matrix and Table share one predicate.
Saved filters store `releaseAreas` and `releaseGroups`; a filter saved with the former single
`releaseGroup` restores as a one-item selection.

Open a role for exact copyable identifier, parsed type/group/strategy and assigned
users with source groups, intervals and status. Navigate to the existing SAP user
profile. Unparsed roles keep their complete source name and evidence.

## Matrix

Rows are release groups, columns release strategies; PR and PO remain distinct.
Cells count distinct normalized SAP usernames, not duplicate rows. Each cell has a Plus/Check
toggle for the access package that adds or removes every distinct release role of that cell
(Check when all of them are already in the package). Filter by SAP
group and document type, then open a cell for matching assignments/users. Optional
SAP User Group comparison has its own secondary control; source assignment groups
are preserved. Multiple evidence rows do not double-count one user in a cell.

Currently-valid assignments are the default. Explicit filters recover expired,
future and unknown evidence. Missing dates do not establish active access;
31.12.9999 remains an explicit date obeying bounds. Table/Matrix, sorting and
filters retain context through role/user drilldowns. Use [Saved Filters](SAVED_FILTERS.md)
for repeat investigations. Parsed names do not establish release authority or effective SAP authorization.

The matrix uses compact content-sized columns, prominent group/strategy headers,
tabular counts and sticky headers inside a contained keyboard-focusable scroll
region. Restrained background intensity is relative to counts on the displayed
matrix, not an authorization or risk score. Complete matrices use contained scrolling without pagination. If a response is
incomplete, a dash represents missing supplied evidence rather than zero users. Group comparison remains in a stable secondary toolbar.

## Access package, bulk actions and role list export

Release roles join the same [access package](ROLE_LOOKUP.md#add-to-cart-proposed-access-package) as catalogue roles,
from the Plus/Check toggle on each Table row and Matrix cell or in bulk, and use the same
floating action. The package is mixed and unlimited, duplicates are prevented, and the state is
shared with Role Lookup. Release role names are kept exactly as assigned: their scope and suffix
tokens are opaque, so neither the package default suffix nor a per-role suffix is applied and
catalogue wildcard rules never touch them. The generated names are shown in the package panel
before copy or export.

Above the results, **Add filtered roles** adds every distinct role matching the filters, status
and dates (across pages, more than 500 asks for confirmation) and reports how many were added
versus already selected. **Copy role names** copies the same distinct roles, one name per line in
a deterministic order, without descriptions. **Export role list** downloads
`sap-lens-release-role-list-review-DATE.csv` with ROLE_NAME, ROLE_DESCRIPTION (only when the exact
role exists in the catalogue), RELEASE_AREA, RELEASE_GROUP, RELEASE_STRATEGY and PR_PO. It is
separate from the assignment export below, which is unchanged.

## Assignment CSV export

**Export CSV** beside the result count and Table/Matrix controls exports one row
per matching user–release-role assignment across every page. PR/PO, release group,
strategy, SAP User Group, username, role, assignment status and all assignment-date
bounds use the same predicate as the displayed results. Table and Matrix export
the same assignment set; matrix grouping does not change export scope.

The shared [assignment CSV format](USER_ACCESS.md#directory-assignment-csv-export)
includes exact role names, SAP identity, validity/status, PR_PO, RELEASE_GROUP,
RELEASE_STRATEGY and MATCHED_FILTER (Yes for every exported matching release row).
Separate validity intervals remain separate rows. UTF-8 BOM, semicolons, Norwegian
dates and spreadsheet-formula protection support Excel without changing stored
data. Zero-result exports are disabled. Source-generation, date, cancellation
and 32 MiB guards match User Directory exports. This exports assignment evidence,
not confirmed effective release authorization.
