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

`RoleMetadata` is shared with composite headers. It uses the canonical module
code supplied by the backend and the existing registry, icons and visual overrides.
A translated description never supplies or overrides classification. A role with
canonical BC evidence therefore retains the BC badge in both listing and details,
regardless of its description. Identifiers are not parsed to invent classifications.

The current catalogue supplies a canonical composite role area through FUNCTION_KEY.
Single-role relationships have no independent area field in this source schema;
those remain Unclassified rather than inheriting a possibly incorrect area from
the parent or description. Full source descriptions remain visible, including any
literal prefix. Update the source evidence rather than guessing from a screenshot.

Role identifiers stay on one monospace line, with complete title/copy values and
contained horizontal scrolling (including Arrow Left/Right while focused). Shared
transaction badges use the same lightning icon, token colors and count tooltip.
Zebra backgrounds do not change when hovering the row; the expansion toggle alone
provides hover feedback. Expansion and keyboard focus remain independent of copy.

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

Transaction search appears first visually and in keyboard order; role text search follows. Example T-codes are placeholders only. Cards constrain intrinsic identifier width and keep exact identifiers scrollable/copyable beside compact shared actions.

Role Comparison summaries use symmetric Jaccard similarity: shared / (A + B − shared), separately for single roles and mapped transactions. Empty unions display 0%, conveying no observed shared evidence. Matrix percentages remain explicitly directional (percent of the row role); the cell title includes both directions and Jaccard. Subsets can have 100% containment and less than 100% similarity. Most similar/distinct use the same symmetric metric, with deterministic identifier ordering for ties; equally scored pairs have equal similarity, not different risk. Exclusive panels size independently.

## Single-role comparison

Role Comparison keeps the high-level single-role and mapped-transaction similarity
metrics, with responsive Shared by all and Exclusive per composite tiles (maximum
three columns). Expand a tile to inspect transaction evidence. Search comparison
transactions accepts exact codes or explicit SAP `*` patterns and filters both
component tiles and transaction rows. Original totals remain unchanged; filtered
shared mappings retain their observed parent catalogue sources. The similarity
overview retains evidence drilldown without a second detailed overlap section.

Recognized source description prefixes appear as separate area labels; original
descriptions and canonical classification are unchanged. Unknown prefixes remain
intact. Role Details uses the same transaction matcher and restores manual
expansion state when its filter is cleared. Neither role nor transaction overlap
proves effective SAP authorization.
