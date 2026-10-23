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

UTF-8 (BOM accepted), BOM-marked UTF-16 and detected or explicitly selected Windows-1252 are supported. Delimiters are auto-detected or selected as comma, semicolon, tab or pipe. Quoted delimiters/newlines are supported. Data Sources has independent Role Catalogue, User Access and Employee Directory tabs; the first two retain their existing format presets. Columns and previews are inspected automatically when an accessible source is opened or its path, format or mappings change; manual Detect columns remains a retry action. Searchable mapping fields support keyboard selection and Automatic mapping. Delimiter and encoding remain under Advanced CSV options. Preview inspects samples, row/duplicate counts, warnings and missing fields without changing active settings/data. Manual mappings are retained when a file changes; missing mapped columns produce a warning/error for explicit correction rather than being silently discarded.

Empty/duplicate/ambiguous headers, unavailable mapped columns, invalid row widths and nonempty rows without a root are rejected. Whitespace is trimmed. Exact normalized duplicate records are counted and deduplicated. Alternate nonempty descriptions are retained with warnings rather than silently overwritten. Limits: 128 MiB input, one million logical rows and 512 characters per identifier. These are parsing safeguards, not a guarantee of low memory consumption.

Relationships preserve all supplied child, parent and effective identifiers, and transactions retain assignment sources. Display grouping uses child first, otherwise effective role, otherwise a clearly marked direct root assignment. This does not invent a SAP hierarchy. Role details show source relationships, alternate descriptions and analysis provenance; large relationship tables show an explicit display cap.

Counts distinguish unique transaction spellings, role/T-code pairs and distinct composite/child/parent/effective/T-code assignment tuples. Transaction spelling/case is preserved, while search is case-insensitive. The role list renders 100 cards per page; comparisons can retain selections across pages. Conflicting source area hints are disclosed; conflicts are shown as Unclassified.

Only absolute filesystem paths are accepted, including permitted Windows UNC paths; no URLs. The application reads, never modifies, the export. Failed loads preserve the prior cache/settings. Cancel invalidates a stalled worker before it can publish, allowing another source to load; at most two daemon CSV readers can remain alive. OS-level reads cannot forcibly be interrupted, but cannot prevent application exit. Use trusted shares only.

The independent User Access CSV has its own import formats and date handling. See the [exact user schema and investigation guide](ACCESS_INVESTIGATION.md).

## Optional Employee Directory source

The independent Active Directory CSV uses a fixed UTF-8 semicolon schema and exact SAP email enrichment. It does not replace either SAP CSV or their import presets. See [Employee Directory format, preview and recovery](EMPLOYEE_DIRECTORY.md).
