# CSV profiles and preserved relationships

The importer supports nine canonical fields. Source columns can be reordered or renamed using a named, versioned CSV Import Format. Automatic matching normalizes header spelling; explicit mappings resolve custom names. Only `AGR_NAME` is required; absent optional fields produce warnings. Existing seven-field exports remain valid.

| Field | Meaning |
| --- | --- |
| FUNCTION_KEY | Explicit SAP area evidence; unknown/conflicting values remain Unclassified |
| AGR_NAME | Composite/root role identifier |
| TEXT | Root description |
| CHILD_AGR | Child/single role identifier |
| CHILD_AGR_TEXT | Child description |
| PARENT_AGR | Raw source parent identifier |
| Effective_Role | Raw effective assignment identifier |
| TCODE | Transaction identifier, including its original case |
| TTEXT | Transaction description |

UTF-8 (BOM accepted), BOM-marked UTF-16 and detected or explicitly selected Windows-1252 are supported. Delimiters are auto-detected or selected as comma, semicolon, tab or pipe. Quoted delimiters/newlines are supported. Detect columns before setting mappings, then Preview to inspect samples, row/duplicate counts, warnings and missing fields without changing active settings/data.

Empty/duplicate/ambiguous headers, unavailable mapped columns, invalid row widths and nonempty rows without a root are rejected. Whitespace is trimmed. Exact normalized duplicate records are counted and deduplicated. Alternate nonempty descriptions are retained with warnings rather than silently overwritten. Limits: 128 MiB input, one million logical rows and 512 characters per identifier. These are parsing safeguards, not a guarantee of low memory consumption.

Relationships preserve all supplied child, parent and effective identifiers, and transactions retain assignment sources. Display grouping uses child first, otherwise effective role, otherwise a clearly marked direct root assignment. This does not invent a SAP hierarchy. Role details show source relationships, alternate descriptions and analysis provenance; large relationship tables show an explicit display cap.

Counts distinguish unique transaction spellings, role/T-code pairs and distinct composite/child/parent/effective/T-code assignment tuples. Transaction spelling/case is preserved, while search is case-insensitive. The role list renders 100 cards per page; comparisons can retain selections across pages. Conflicting source area hints are disclosed; conflicts are shown as Unclassified.

Only absolute filesystem paths are accepted, including permitted Windows UNC paths; no URLs. The application reads, never modifies, the export. Failed loads preserve the prior cache/settings. Cancel invalidates a stalled worker before it can publish, allowing another source to load; at most two daemon CSV readers can remain alive. OS-level reads cannot forcibly be interrupted, but cannot prevent application exit. Use trusted shares only.

The independent User Access CSV has its own import formats and date handling. See the [exact user schema and investigation guide](ACCESS_INVESTIGATION.md).
