# SoD matrix source

The SoD matrix is an externally supplied CSV. SAP Lens does not query SAP or
schedule source extraction. The backend supports it as a fourth source through
the existing validated import, snapshot and refresh lifecycle. Settings → SoD Risk Configuration provides the imported catalogue and local
business guidance. The SoD area adds user/role evidence investigation. Persistent access review
and report interfaces are being implemented separately; investigation findings
are not review decisions or approvals.

## Schema and policy

Required headers are `RISK`, `CRITICITY`, `TYPE`, `TEXT`, `ACTVT1`, `ACTVT2`,
`ACTIVITY_SLOT`, `ACTIVITY`, `TCODE` and `TTEXT`. The shared importer detects
supported encoding and delimiter formats. `TTEXT` values may be empty, with a
warning. Other values are required. Identical records deduplicate; conflicting
risk definitions or activity/transaction descriptions reject the replacement.

`ACTIVITY_SLOT` must be literally `ACTVT1` or `ACTVT2`; `ACTIVITY` must equal the
corresponding activity identifier. Each risk requires two distinct, complete
activity sides. Transaction overlap between sides remains intact and generates
a definition-review warning.

`TYPE` is the source risk-type value. The named `sod-two-sided-v1` policy supports
observed `S` definitions with both sides; this is an explicit application policy,
not a claim that `S` universally defines two-sided SAP risk semantics. Other types
are retained and flagged as unsupported for evaluation. Criticality is preserved
as source data. No source `ACTIVE` field is present in this schema; activation
cannot be inferred from an unexported field.

Transaction mappings support potential conflict investigation. They do not prove
effective authorization or a confirmed security violation.

## Source lifecycle

Authenticated backend selection uses `/api/data-sources/sod/select`; preview uses
`/api/data-sources/sod/preview`. Server uploads use the existing bounded upload
endpoint with source `sod`, then validated selection. Uploaded client files are
Static inputs, not dynamic paths on the client's device.

Selecting a valid nonempty source atomically activates its complete replacement.
Invalid, interrupted or changing inputs preserve the last valid generation.
Static snapshots restore without the original CSV. Dynamic sources reread their
permitted server-visible path on Global Refresh. No filesystem watcher is added.

The source has its own import/check timestamps, separate from SAP dataset refresh
metadata. The CSV provides no explicit extraction-generation timestamp; import
time must not be represented as SAP extraction time.

Immutable source versions retain removed definitions. Version references are
bounded at 1,000; reaching the limit fails safely rather than silently deleting
history. Back up private application storage before recovery or migration.
Refresh reports retain the existing five-report limit and include bounded risk
change summaries plus the detailed authenticated record changes.

Original historical reference documents and matrix exports remain outside Git.
Committed tests use fully synthetic identities and definitions. Portable
configuration exports exclude source paths, snapshots and source history; full
private backups remain sensitive and follow the normal deployment backup rules.

See [Import and refresh](IMPORT_AND_REFRESH.md) and [data documentation](README.md).


## Local risk configuration

Under Settings → Data Sources → SoD Matrix, select a file to validate and import
it automatically. Preview inspects the active durable snapshot rather than
rereading the original. The same shared controls support permitted server paths,
browser uploads, explicit replacement and intentional clearing.

Settings → SoD Risk Configuration separates imported source values from local
metadata. Search/filter the catalogue, inspect both activity sides, and edit:

- Enabled preference, display name and business category.
- English/Norwegian explanation, consequences, mitigating controls and review guidance.
- Local notes and description-review status.

New risks are enabled by default and need description review. No business
explanation or control is fabricated from source codes. A source-definition
change invalidates the description's reviewed status without discarding local
text. Removed risks remain in historical source versions and retain local edits,
but are excluded from current analysis. Bulk disabling requires confirmation;
it does not delete history or approve descriptions.

Metadata uses a separate versioned private store with optimistic revision and
source-definition guards. Concurrent edits or refreshes require reloading before
saving. Invalid or unreadable storage is preserved and reported for recovery.
The store currently supports up to 5,000 annotated risks and 20 MiB; limits fail
safely without partially applying edits. Private deployment backups include this
store; portable appearance/configuration packages do not include it.

## Analysis methodology

The deterministic `sod-two-sided-v1` engine requires supporting mappings on both
activity sides. User evidence follows exact imported assignments through the
existing exact/unambiguous wildcard catalogue matching, single-role relationships
and transaction mappings. Matching transaction codes is case-insensitive and exact;
original matrix and catalogue spellings remain in the evidence.

Active assignments are the default. Expired, future and unknown intervals remain
separate investigation choices; missing dates never establish active access.
All-validity analysis does not prove that historical activity sides overlapped.
SAP account validity, lock state and reliably matched AD state remain separate
facts and do not silently suppress a potential finding.

Role analysis detects coverage within one catalogue role or an explicitly selected
combination of up to 25 known roles. It does not enumerate all possible role pairs
or claim assignment validity for unassigned catalogue mappings. Missing source
coverage is reported as unavailable, not proof of no access.

Finding identities use subject, risk and policy. Relevant evidence fingerprints
retain distinct intervals/provenance and ignore row order, unrelated imports and
refresh timestamps. Unsupported and locally disabled risks are excluded from
current calculations. Source criticality codes remain literal; the historical
references did not establish an explicit C/H label mapping.


## Investigation and CSV export

Open SoD → User Conflicts or Role Conflicts. Filters and sorting are independent
between views and can be stored with the existing Saved Filters menu. User
investigation defaults to active assignments; the evaluation date uses Norwegian
manual date entry while internal values remain ISO dates. Role combinations are
explicit selections, not a global pairwise risk metric.

Inspect both activities to page through every supporting path. Actual assigned
role identifiers, matched catalogue patterns, single roles and transaction
provenance are distinct. Existing user/profile and catalogue drawers remain the
navigation targets. The generation guard rejects evidence requests after the
underlying analysis context changes.

Export CSV uses the same filters across all result pages and includes every
supporting path. Files use UTF-8 BOM, semicolons, quoted fields, Norwegian dates
and spreadsheet-formula protection without changing stored values. Columns cover
finding identity, subject, risk/type/criticality, activity slot, original
transaction spellings, actual/catalogue/single roles, assignment dates/status,
user group, matching status, evidence version, evaluation date/policy and source
snapshot versions. No filesystem paths are included.

Browser downloads and the guarded desktop Save dialog share the server-generated
CSV contract. The client/native size limit is 32 MiB; narrow filters for larger
exports. Native Windows Save-dialog behavior still requires acceptance testing;
Linux mocked bridge tests are not equivalent to native validation.

## Access Review

SoD → Access Review records justified decisions against current active assignment
evidence. Accepted-with-controls decisions require documented controls; completed
actions require completion notes. Reviewer names are explicitly self-reported,
not authenticated identities or verified signatures. SAP source data is never
modified by a review.

Each save appends an event referencing an immutable, integrity-checked finding
snapshot. History includes the original rationale, controls, actions and both
activity sides, even after source changes. Evidence fingerprints distinguish
outdated decisions from unrelated refresh changes. Snapshot staging and revision/
generation guards preserve the previous decision if a save fails.

Decision and lifecycle are separate. Missing sources, removed users, disabled
risks and changed matrix coverage do not establish resolution. A resolved
potential finding means complete current imported evidence no longer supports it;
it does not prove a SAP account was disabled or effective access removed.
Outstanding actions and filtered review records have local CSV exports.

## Review periods

SoD → Review Periods captures a named date range and explicit evaluation date.
Each snapshot retains source IDs/timestamps, risk definitions and enablement,
local guidance, findings, decisions, methodology and organization metadata.
Period-specific decisions do not overwrite current or other-period decisions.

Move Draft → In review → Ready for approval → Approved / closed. Pending/outdated
findings block approval preparation. Closure requires explicit confirmation,
self-reported reviewer/approver and an approval date. Closed snapshots cannot be
edited or recaptured. Open-period recapture is explicit and retains previous
snapshot references. Ordinary refresh never changes a period snapshot.

Comparisons distinguish new, changed, unchanged, reopened and resolved potential
findings. Lost users, disabled/changed risks or incomplete source coverage produce
“Not observed / coverage changed” rather than automatic resolution. Evaluation
at a past date uses the imported evidence retained in the snapshot; it is not a
reconstruction of unexported historical SAP access. Private backups must include
both the period/review indexes and their immutable snapshot files.

## DOCX and PDF reports

SoD → Reports uses one structured model from a selected period snapshot for both
formats. Choose title, date/version, prepared-by/reviewer/approver details,
management comments, sections, appendices and an optional closed previous period.
Preview the structured summary before exporting. Changed evidence invalidates the
preview. Approved status is allowed only for a closed period; recorded approval
identities cannot be overridden by report options.

DOCX is editable. PDF uses bundled Unicode fonts and needs no Office installation.
Both include organization metadata/logo when configured, source and methodology
versions, potential findings, decisions, controls, actions, signature lines and
integrity metadata. Names/signature lines are not verified digital signatures;
use an external signing solution. Import/check timestamps are labelled UTC;
dates use DD.MM.YYYY and 24-hour time.

The English template is complete. Norwegian headings and locally maintained
Norwegian business guidance are supported; supporting template prose remains
English. PDF font coverage includes the tested Nordic characters; unsupported
symbols fail explicitly instead of producing missing glyphs. Editable DOCX is
available for such content. Detailed reports are bounded at 20,000 rows, an
8 MiB structured model and 32 MiB output. Exclude appendices and use complete CSV
exports when limits are reached. Missing/corrupt frozen logos require backup
recovery rather than silently changing an approved report's branding.

New runtime dependencies are pinned: python-docx (MIT), ReportLab (BSD), lxml
(BSD-3-Clause) and charset-normalizer (MIT). Windows packaging includes DOCX
standard templates, ReportLab's Bitstream Vera fonts/font license and dependency
license metadata. Docker/native deployments install the same pinned packages and
resources. Native Word/WebView2/packaged Windows acceptance remains separate from
structural DOCX, Linux PDF and mocked native-dialog validation.
