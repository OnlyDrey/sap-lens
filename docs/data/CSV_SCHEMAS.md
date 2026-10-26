# CSV schemas

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


## User–Role Mapping

| Field | Meaning |
| --- | --- |
| USERNAME | Required SAP user identifier; independent of name/email |
| ROLE_NAME | Exact assigned role; blank explicitly supports a directory-only row |
| USER_GROUP | SAP source user group, retained per assignment/account record |
| FIRST_NAME, LAST_NAME, EMAIL | Optional directory metadata; conflicting variants retained |
| USER_VALID_FROM, USER_VALID_TO | Account validity, separate from assignment validity |
| ROLE_VALID_FROM, ROLE_VALID_TO | Assignment interval |
| USER_LOCKED | X/true/yes/locked or nonzero SAP lock mask; 0/false/no/unlocked is unlocked; missing/unrecognized is unknown |
| USER_TYPE | Optional source value, without invented semantics |

UTF-8/BOM, UTF-16 BOM and Windows-1252 are supported. Auto detection uses a
bounded sample; delimiters include comma, semicolon, tab and pipe. Advanced
options override detection. Duplicate/empty headers, missing USERNAME, malformed
row widths, invalid dates and reversed intervals fail validation without publishing.
Files are bounded to 128 MiB and one million logical records and 100,000 distinct users; fields and role
identifiers are length-bounded. Full identical rows are deduplicated. Distinct
users are never joined by names/emails. Case-normalized SAP usernames identify a user (interior text is not removed);
assignment intervals, source groups and account evidence remain distinct.

Dates accept YYYY-MM-DD or YYYYMMDD, including 9999-12-31. Empty/00000000/0000-00-00
means unknown, not unrestricted access. Bounds are inclusive. An ended interval
is expired, a not-yet-started interval future, two enclosing bounds active;
otherwise unknown. Status is evaluated using the local backend calendar date.

## Employee Directory


Use these 16 headers, separated by semicolons (header order may vary):

```text
Site;Name;SamAccountName;UserPrincipalName;Mail;Department;Title;Enabled;DistinguishedName;ManagerDN;ManagerName;ManagerSamAccountName;ManagerMail;ManagerDepartment;ManagerTitle;ManagerLookupStatus
```

All headers are required, case-insensitively and without duplicates. Individual
values may be blank. Use UTF-8, optionally with a BOM. Quoted fields support
semicolons, quotes and line breaks. Leading/trailing whitespace is trimmed.
Blank rows are ignored; a header-only/empty file is rejected. Malformed rows,
invalid UTF-8 and missing/extra headers are rejected atomically. Limits: 50 MB,
100,000 records and 4,096 characters per field. No real employee fixtures belong
in the repository.

`Enabled` accepts `true`/`false` or `1`/`0`, case-insensitively. Other/missing values
remain **Unknown**, never implicitly enabled. AD account state is shown separately
from SAP lock and validity evidence. `UserPrincipalName` is not an email fallback;
`ManagerLookupStatus` is source information, not proof that SAP Lens resolved a
manager.


## Import formats and source modes

Built-in presets are protected. Create, rename, duplicate or delete custom presets
with confirmation; deleting the active preset restores a valid default. Deletion
does not delete a CSV or dataset. Mappings are independent for catalogue and user
sources. Directory uses the fixed format above. See [import and refresh](IMPORT_AND_REFRESH.md),
[identity enrichment](EMPLOYEE_DIRECTORY.md) and [synthetic datasets](../../examples/README.md).

## Role-name matching

Normalize surrounding whitespace and case for matching; preserve original exact
assignment identifiers for display/copy. Exact catalogue matches win, followed by
the longest literal-prefix pattern ending in one `*`. Equal winning candidates
are Ambiguous and supply no inferred transactions. Missing matches are Unmapped.
Anchored full-name matching supports `ZC:SYN:EN*` and broader `ZC:SYN:*`; three-character
suffixes may occur but are not mandatory. Interior/multiple stars, question marks,
character classes and backslashes are unsupported. Assigned names containing
wildcards are rejected; catalogue patterns never become actual assignments.

Resolved transactions retain catalogue child/effective/direct relationships.
Mapping coverage is not proof of effective authorization. See [User Access](../features/USER_ACCESS.md)
and [Release Roles](../features/RELEASE_ROLES.md) for scope and strict PR/PO parsing.
