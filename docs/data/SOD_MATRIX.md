# SoD matrix source

The SoD matrix is an externally supplied CSV. SAP Lens does not query SAP or
schedule source extraction. The backend supports it as a fourth source through
the existing validated import, snapshot and refresh lifecycle. Settings → SoD Risk Configuration provides the imported catalogue and local
business guidance. The SoD area adds matrices and investigation, activity, role-assignment and
risk-acceptance review, frozen Review Periods and DOCX/PDF reports (see the
[SoD guide](../features/SOD.md)). Investigation findings are not review decisions
or approvals.

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

## Optional descriptive columns

The ten documented columns above are the only required ones and keep their meaning. A file may also carry any of these optional columns, which
SAP Lens maps automatically by name (or by hand under *Advanced import format and column mapping*): `RISK_NAME`, `RISK_DESCRIPTION`, `RISK_IMPACT`,
`BUSINESS_PROCESS`, `ACTIVITY_NAME`, `ACTIVITY_DESCRIPTION`, `ACTIVITY_TYPE`, `ACTIVITY_BUSINESS_PROCESS`, `RULESET_ID`, `RULESET_VERSION`,
`SOURCE_SYSTEM`, `LANGUAGE` and `LAST_CHANGED`. These are proposed export fields, **not verified SAP columns**; nothing is generated from identifiers.

- **Compatibility.** Existing files import without modification and keep the same content identity. A missing optional column is neither an error nor
  a warning; unknown extra columns are ignored with the existing notice. Optional values never change a record, a duplicate, a risk definition, the
  `ACTVT1`/`ACTVT2` distinction or any detection result.
- **Storage.** Optional values are kept apart from the records, in the import report of the private snapshot. Per risk and per activity the first value in
  file order is kept (a conflict is counted in a warning); values longer than 4096 characters or with control characters are skipped and counted, never fatal.
  A change that touches only these descriptions is staged as a new snapshot so refreshes do not ignore it.
- **Priority and provenance.** SAP Lens shows the imported value when it is populated, otherwise the locally maintained business text (Settings → SoD Risk
  Configuration), otherwise "No description available". Both stores stay separate: a refresh or import never overwrites local text, and local text never edits
  the import. Where they differ both are kept and the popover and Settings name the origin of each. One resolver (`backend/sod_metadata.py`) serves pills,
  popovers, Settings and the diagnostics.
- **Coverage.** The SoD source inspection and the pre-import validation list, for risk names and descriptions, activity names and descriptions and transaction
  descriptions, the available and total counts, the percentage, the missing count, imported versus local-fallback counts and a status: *Complete*,
  *Values missing* (column present) or *Column not in CSV*. Counts use distinct risks, activities and transaction codes, not CSV rows. Detected and missing
  optional columns, source facts such as `RULESET_ID` and a small sample of resolved metadata are shown beside it.

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

SoD → Risk Matrix, Activity Matrix and Access Explorer share one filter set (search, user
group, risk, activity, role, role suffix, transaction, business area, criticality, assignment
validity, review decisions) that Saved Filters can store. Evidence defaults to active
assignments; expired, future and unknown intervals are separate investigation choices and
read-only for review. Evaluation dates use Norwegian manual entry; internal values stay ISO.
Role combinations (Access Explorer → Role conflicts) are explicit selections, not a global
pairwise risk metric.

Matrix exports and explorer tables use UTF-8 BOM, semicolons, quoted fields, Norwegian dates
and spreadsheet-formula protection without changing stored values. They never contain
filesystem paths. The evidence export lists every supporting path (actual and catalogue
role, single role, transaction, validity, source versions). Browser downloads and the guarded
desktop Save dialog share the server-generated CSV; the limit is 32 MiB, so narrow the
filters for larger exports. Native Save-dialog behavior requires Windows acceptance testing.

## Reviews

Decisions are recorded in three independent layers (activity, role assignment, risk
acceptance); see the [SoD guide](../features/SOD.md) and
[architecture](../architecture/SOD.md). Reviewer and approver names are self-reported, not
authenticated identities or verified signatures. SAP source data is never modified.
Each save appends an event referencing an immutable evidence snapshot, so history keeps the
original rationale, conditions and both supporting paths after source changes. Missing
sources, removed users, disabled risks and changed coverage do not establish resolution.
A resolved item means complete current imported evidence no longer supports it, not that an
account was disabled or access removed. Risk-level decisions recorded before SoD 2.0 are
retained as legacy history and are not converted into activity or acceptance decisions.

## Review periods

A period captures a named range and an explicit evaluation date: source versions and
timestamps, risk definitions and enablement, local guidance, findings, methodology and
organization metadata. Decisions in a period never overwrite current or other-period
decisions. Workflow: Draft, In review, Ready for approval, Approved, Closed, with Rejected
returning to In review. Pending or outdated activity and risk decisions block approval; the
reviewer and approver must differ. Approval freezes the snapshot together with its decisions,
actions and removal verification and cannot be edited or recaptured; ordinary refresh never
changes a snapshot. Comparisons classify new, changed, unchanged, reopened and resolved
findings and list decision changes. Lost users, changed risks or incomplete coverage give
"Not observed / coverage changed", never automatic resolution. Periods can be deleted only
under the guarded rules in [architecture](../architecture/SOD.md#deletion). Private backups
must include the period and decision stores and their immutable snapshot files.

## DOCX and PDF reports

SoD → Reports builds one structured model from a period snapshot for both formats: cover,
executive summary, scope and methodology, sources and limitations, risk overview, activity,
role assignment and risk acceptance results, compensating controls, outstanding
remediation, changes, conclusion with signature lines and a technical appendix. Counts
distinguish users, user-risk findings, activities and assignments. Preview before exporting;
changed evidence invalidates the preview. Approved status requires an approved period and
recorded approval identities cannot be overridden by report options. The separate access
remediation report (CSV, DOCX, PDF) lists recommended handling per assignment and never
treats a proposal as completed work. Long hashes and source versions are in the technical
appendix and the document-integrity block.

DOCX is editable. PDF uses bundled Unicode fonts and needs no Office installation. Both
include organization metadata/logo when configured. Names and signature lines are not
verified digital signatures; use an external signing solution. Timestamps are labelled UTC;
dates use DD.MM.YYYY. Reports are English only. Unsupported PDF symbols fail explicitly (use DOCX).
Reports are bounded at 20,000 rows, an 8 MiB model and 32 MiB output. Exported reports are
recorded in a private log; reports issued for review or approval protect their period from
deletion. A missing frozen logo needs backup recovery rather than silently changing branding.

New runtime dependencies are pinned: python-docx (MIT), ReportLab (BSD), lxml
(BSD-3-Clause) and charset-normalizer (MIT). Windows packaging includes DOCX standard
templates, ReportLab's Bitstream Vera fonts/font license and dependency license metadata.
Docker/native deployments install the same pinned packages and resources. Native
Word/WebView2/packaged Windows acceptance remains separate from structural DOCX, Linux PDF
and mocked native-dialog validation.

## Overview and source refresh

The SoD Overview reuses current analysis and decision counts. Unavailable evidence is
labelled unavailable, not zero. Criticality labels keep their raw source values. Source
import and check timestamps remain separate from the SAP refresh timestamp, and the
Overview reports findings newly detected or no longer detected since the previous refresh.
The risk catalogue (including its CSV export, both activity mappings and local
English/Norwegian guidance) lives only in Settings → SoD Risk Configuration. A
[synthetic matrix](../../examples/sod-matrix.example.csv) is provided for the linked example
catalogue; its invented pairs are not production risk guidance.
