# Role Lookup and Role Details

Search catalogue role names/descriptions alongside exact transaction codes. SAP area
pills combine with OR; separate text/area/transaction categories combine with AND.
Multiple T-codes default to AND, with an explicit OR option. Enter creates a chip;
remove chips individually or Clear all filters. Sorting stays beside the result
count, below the primary searches.

## Exclude matching transactions

Role Lookup and User Access share one transaction filter: a single search input, compact removable chips, the AND/OR control for
several codes and an **Exclude matching transactions** checkbox. Unchecked (the default) is positive matching; checking it reverses the
filter and keeps the entered codes. **Clear all filters** restores positive matching.

| Selected codes A and B | AND | OR |
| --- | --- | --- |
| Positive | contains A and B | contains A or B |
| Exclude matching | does not contain A and B together | contains neither A nor B |

Exact codes and `*` wildcards work in every combination, and the filter combines with the text search, SAP area pills and other filters (AND).

- **Role Lookup**: reverse results are roles that hold at least one transaction mapping, so roles without any mapping never appear
  (`GET /api/roles?tcodes=...&transaction_mode=and|or&exclude_matching=true`).
- **User Access**: transactions are evaluated across the user's eligible role assignments (the same user group, role and validity rules
  as the directory). A user only appears in reverse results when every eligible assignment is mapped to a catalogue role; users with unmapped
  roles, with no eligible assignment, or without a loaded catalogue are not listed because absence cannot be confirmed
  (`GET /api/access/users?...&exclude_transactions=true`). Sorting, Saved Filters (`transactionExclude`) and CSV export use the same selection.
- Earlier saved filters that used `transactionOperator: not` or `notTcodes` still load as an exclusion with OR (none of them).
- A missing mapping is never proof that SAP authorization is absent.

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

## Add to cart: proposed access package

Each Role Lookup tile has two independent round toggles: **Add to cart** (shopping cart) and **Add to comparison** (scales). Comparison selection and the cart never affect each other. **Access package (N)** opens the panel; the cart is kept for the browser session only and holds role names, never user data.

The package turns catalogue roles into proposed SAP role names. It never assigns roles or changes SAP.

- **Suffixes.** A package default suffix applies to every role; a role-specific suffix overrides it, and changing the default never changes an override. The suffix replaces a catalogue wildcard (`ZC:MM:BUY:*` becomes `ZC:MM:BUY:ENP`) or the existing organizational suffix (`ZC:MM:BUY:ENP` becomes `ZC:MM:BUY:ENS`). Known organizational suffixes are detected from the imported role names (a final segment of business roles used under at least two stems, for example ENP, ENK, ENS, ENO); none is hard-coded.
- **Validation.** Syntax (A-Z, 0-9, underscore, hyphen, up to 16 characters), generated names (A-Z, 0-9, `_ : / . -`, up to 30 characters), duplicates (the first keeps the name), the catalogue match of each generated name (exists, covered by a pattern, ambiguous, or not in the catalogue) and ambiguous sources. A pattern with a partial segment (`ZC:SD:ORD:EN*`) only accepts a suffix that starts with that segment. A final segment that is not a known suffix is reported as ambiguous and is rewritten only when the role has an explicit suffix, with a warning. Ambiguous identifiers are never rewritten silently.
- **Copy and export.** Each generated name and the source role have a copy button; **Copy all names** copies the valid names. **Export CSV** has the columns Generated SAP Role Name, Role Description and Suffix, sorted by name, without duplicates or invalid rows, semicolon separated, UTF-8 with BOM and protected against spreadsheet formulas.

## Single-role comparison

Role Comparison keeps the high-level single-role and mapped-transaction similarity
metrics, with responsive Shared by all tiles (maximum three columns) and Exclusive per composite lists. A shared single role expands vertically inside its own tile, pushing later content down, and exclusive single roles are compact list rows that expand beneath the row. Every single-role entry (also in Role Details) shows the module icon and code with the transaction count below, the description beside them and the copyable role identifier last. Expand an entry to inspect transaction evidence. Search comparison
transactions accepts exact codes or explicit SAP `*` patterns and filters both
component tiles and transaction rows. Original totals remain unchanged; filtered
shared mappings retain their observed parent catalogue sources. The similarity
overview retains evidence drilldown without a second detailed overlap section.

Recognized source description prefixes appear as separate area labels; original
descriptions and canonical classification are unchanged. Unknown prefixes remain
intact. Role Details uses the same transaction matcher and restores manual
expansion state when its filter is cleared. Neither role nor transaction overlap
proves effective SAP authorization.
