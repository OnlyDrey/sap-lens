# SoD matrix source

The SoD matrix is an externally supplied CSV. SAP Lens does not query SAP or
schedule source extraction. The backend supports it as a fourth source through
the existing validated import, snapshot and refresh lifecycle. The SoD catalogue,
analysis and review interfaces are being implemented separately; source support
alone is not a complete SoD investigation workflow.

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
