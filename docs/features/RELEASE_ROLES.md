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

Filter by SAP User Group, PR/PO, release group, strategy, username, exact role text,
assignment status and [assignment dates](FILTERS.md#assignment-dates-and-tables).
Sort and Descending stay together in the primary panel, alongside the compact
date control. Clear filters restores the ordinary currently-valid view.
Date bounds affect assignments before counts, facets and pagination, never user profiles.

Open a role for exact copyable identifier, parsed type/group/strategy and assigned
users with source groups, intervals and status. Navigate to the existing SAP user
profile. Unparsed roles keep their complete source name and evidence.

## Matrix

Rows are release groups, columns release strategies; PR and PO remain distinct.
Cells count distinct normalized SAP usernames, not duplicate rows. Filter by SAP
group and document type, then open a cell for matching assignments/users. Optional
SAP User Group comparison has its own secondary control; source assignment groups
are preserved. Multiple evidence rows do not double-count one user in a cell.

Currently-valid assignments are the default. Explicit filters recover expired,
future and unknown evidence. Missing dates do not establish active access;
31.12.9999 remains an explicit date obeying bounds. Table/Matrix, sorting and
filters retain context through role/user drilldowns. Use [Saved Filters](SAVED_FILTERS.md)
for repeat investigations. Parsed names do not establish release authority or effective SAP authorization.
