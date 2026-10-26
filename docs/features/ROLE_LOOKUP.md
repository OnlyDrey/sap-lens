# Role Lookup and Role Details

Search catalogue role names/descriptions alongside exact transaction codes. SAP area
pills combine with OR; separate text/area/transaction categories combine with AND.
Multiple T-codes default to AND, with an explicit OR option. Enter creates a chip;
remove chips individually or Clear all filters. Sorting stays beside the result
count, below the primary searches.

Open a role for its relationships and transactions. Previous/Next spans the full
filtered/sorted result set and preserves the originating list. The compact back
action closes the drawer. Copy uses the exact identifier. Existing Role Comparison
compares selected catalogue roles; it is separate from [Compare Users](COMPARE_USERS.md).

## Single-role metadata

Single-role headers align module icon/badge, title, copyable identifier and
transaction count horizontally when space permits, stacking at narrow widths.

The source description is no longer repeated underneath the identifier. Expansion,
transaction counts and direct/effective-assignment provenance remain available.

`RoleMetadata` is shared with composite headers. It uses the existing SAP module
registry, aliases, icon mapping and saved visual overrides. Explicit single-role
module metadata takes precedence. Otherwise, a leading, delimited module token in
the imported **description** can supply a display label only when it resolves
unambiguously through that registry. No role identifier fragments are parsed.

Examples:

| Imported description | Header badge | Header title |
|---|---|---|
| `CA - Master Data - Materials Display & Reporting` | CA | Master Data · Materials Display & Reporting |
| `CA - Master Data - Batch Display` | CA | Master Data · Batch Display |
| `SD - Master Data - InfoRecord` | SD | Master Data · InfoRecord |
| Meaningful text without a recognized prefix | None; neutral icon | Full source description |
| No description and no module metadata | None; neutral icon | Unclassified |

Whitespace-delimited hyphens, en dashes and em dashes are supported. Unknown or
ambiguous prefixes remain literal source text. A conflicting description prefix
does not override explicit module metadata. This is presentation of source text,
not another classification engine: backend module IDs, module filters, catalogue
matching and transaction relationships are unchanged. A child can therefore retain
a backend Unclassified ID while its header displays a recognized description
prefix. This distinction is explained in the existing provenance disclosure.

## Role Details: Find transaction code

The sidebar search sits below **Relationships & analysis provenance**, immediately
above **Single Roles**. Live search trims surrounding whitespace and uses exact,
case-insensitive OR matching across chips and draft text. It searches all imported single-role transaction
mappings, including collapsed sections; it does not contact SAP.

Active codes hide nonmatching sections, expands every matching section and
shows the matching count. Matching transaction rows have a theme-token background
and underlined, heavier code text. Transaction descriptions and Investigate users
buttons remain intact. Other transaction rows in each matching section remain
available as context. Users can collapse sections during search. Clear restores
the full list and its previous normal expansion state. Changing the opened role
resets the search and its temporary expansion state.

Live transaction matching uses the shared debounced input and memoized role data. Memoized single-role rows avoid rerendering their full
transaction tables for every input keystroke. Hidden sections retain their normal
expansion state and are excluded from keyboard navigation by the HTML hidden
attribute.

## Catalogue diagnostics and source limitations

These conditions are independent:

| Imported evidence | Interpretation / UI |
|---|---|
| No resolved catalogue record for the assignment | Unmapped/unavailable catalogue evidence; no transaction access is invented |
| Matching catalogue record with an empty description | Match remains valid; provenance reports the missing description |
| Catalogue record without explicit child/parent/effective fields | Provenance reports absent relationship fields; existing direct source mappings are preserved |
| Role or single role without transaction rows | Mapping evidence is unavailable, not proof of no SAP permissions |
| Some transaction mappings are supplied | Matches are confirmed within those mappings; completeness of the external export cannot be established |

An exact match depends on the catalogue identifier, not on whether description,
relationship or transaction fields are populated. If the catalogue export later
contains a previously absent role, refresh can legitimately change an Unmapped
assignment into a confirmed match. The application cannot determine why an SQL
export omitted a record. No SQL query or missing role record is created here.

Search reports no match **in the imported mappings** separately from a role with
no mappings. Zero-mapping single roles trigger a completeness warning. Imported
mapping evidence never proves effective SAP authorization or the absence of
permissions. Review the upstream export separately when evidence is incomplete.


See [filter semantics](FILTERS.md), [CSV schemas](../data/CSV_SCHEMAS.md) and [SAP areas](../data/CLASSIFICATION.md).
