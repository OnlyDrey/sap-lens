# Storage, source revisions and data consistency

How SAP Lens stores imported data, decides what changed, publishes a new dataset and keeps every client consistent with it. Operational guides:
[import and refresh](../data/IMPORT_AND_REFRESH.md), [data retention](../operations/DATA_RETENTION.md), [backup and restore](../deployment/BACKUP_RESTORE.md).

## Principles

* **Immutable, content-addressed snapshots and the validated JSON stores are authoritative.** Everything else is derived and rebuildable.
* **Local only.** The server binds to loopback (desktop) or an administrator-configured address (server mode); there is no automatic third-party data-upload service. Authorized reports, CSV exports and backups can leave the directory and must be protected separately.
* **A dataset is published whole.** Readers see the previous dataset or the new one, never a mixture.
* **Evidence is never inferred.** Review decisions are tied to the evidence they were made on and are revalidated when it changes.

## Sources, Static and Dynamic mode

Four independent CSV sources (Role Catalogue, User-Role Mapping, Employee Directory, SoD Matrix) each have a mode. **Dynamic** sources are re-read on
every refresh (manual, scheduled or at start). **Static** sources are imported when a file is selected or uploaded and afterwards served from their private
snapshot, so Refresh never re-reads the original file and the original may be unavailable. Details: [CSV data lifecycle](../data/IMPORT_AND_REFRESH.md).

## Source fingerprints and the unchanged fast path

Every source has a fingerprint: the file digest, the parse settings that shape the records (delimiter, encoding, column mapping) and the digest of the
parser code. If the fingerprint equals the active revision's, the file is not parsed again: the stored records, and the derived model when its inputs are
unchanged, are reused. A changed source is parsed, compared against the active records (exact records cancel first, then the remainder is grouped by
identifier) and only the affected parts are recomputed. Employee Directory data has its own fingerprint and a shared SAP/AD identity matcher that is
rebuilt only when the SAP dataset or the directory changes; the previous pair is released when it is replaced.

## Staged activation

A load writes the new immutable snapshot, stages its rows in the store under an operation identifier (invisible to readers), commits the configuration
pointer with a compare-and-swap, and only then activates the staged revisions. A load that fails, is cancelled or loses the compare-and-swap discards
only its own staged revisions; an interrupted process leaves orphans that are removed at the next start. Suspicious imports (sharp reduction against
the active revision) are parsed and reported but not activated until an administrator confirms them.

## Assignment lifecycle memory

`assignment-lifecycle.json` records which assignments were seen in which dataset. An assignment that disappears and reappears is treated as a new
assignment: earlier decisions are shown as outdated and a new review is required. Applicability of a decision is fail-safe: when the evidence cannot be
established, the decision does not apply.

## SQLite store: source revisions and derived state

One database, `<data dir>/store/sap-lens.sqlite3`, is the only SQLite file (`backend/store_db.py`: connection, schema ladder, permissions, signing key). It is a **rebuildable,
optional** structure. The validated JSON stores and the immutable, content-addressed snapshots under `csv-data/snapshots` remain the authority and the format older versions read;
review decisions, periods, frozen evidence and settings never move. If the database is missing, damaged or from a newer version, SAP Lens reads the snapshots exactly as before.

| Table | Content | Authority |
| --- | --- | --- |
| `source_revisions`, `rows_roles`, `rows_users`, `rows_sod` | Typed (one column per field) copy of the records of a snapshot. A revision is keyed by the snapshot digest, carries a row count and a rows digest, and has a `sequence`. | Derived from the snapshot; `source_store.reconcile` makes it follow the committed configuration, never the other way round. |
| `derived` | Authenticated serialized model (catalogue, users, assignment indexes) keyed by snapshot digest, settings that shape the derivation, catalogue digest and code digest. Lists the revisions it depends on. | Rebuildable. |
| `migrations`, `meta` | Upgrade records and schema facts. | Mirror of `.application-backups/migration/<id>/record.json`. |

- **Revisions and atomic replacement.** Per (source, scope) exactly one revision is `active`; a partial unique index makes the database itself reject a second one. Replacing a source is
  one transaction: insert the new rows, flip the old revision to `superseded`, activate the new one. Readers see the old or the new revision, never a mixture. The latest two superseded
  revisions are kept (previous approved revision for comparison and rollback); pruning a revision deletes its rows and exactly the derived values that list it.
- **One representation of the raw records.** A derived entry does not contain the raw records; on a hit they are re-attached from the revision. The first derived cache (a separate
  `cache/derived.sqlite3` with whole-state pickles keyed by file hash) was folded into this store and is removed on upgrade.
- **Integrity.** Revision rows are verified against the recorded row count and digest on every read; a mismatch discards the revision and falls back to the snapshot. Derived entries carry an HMAC
  (`store/.key`, owner-only, 32 random bytes) that is verified *before* deserialization, and deserialization is additionally restricted to data containers and this application's own model
  classes, so even a validly signed payload cannot name `os`, `subprocess` or `builtins.eval`. The directory is created `0700` and the database `0600` (WAL files inherit it) on POSIX;
  on Windows the data directory's private ACL applies.
- **Concurrency.** WAL, `busy_timeout` 15 s, one short-lived connection per operation (never shared between threads), `BEGIN IMMEDIATE` for every write, a process-wide lock around the
  connection lifecycle. The storage lease keeps one application process per data directory (desktop and server alike); additional processes (maintenance CLI, tests) are safe because SQLite
  serializes writers and WAL lets readers proceed.
- **Schema versions.** `PRAGMA user_version` plus an ordered ladder of idempotent steps, each in its own transaction. A database written by a newer version is neither opened for writing nor
  modified or deleted; SAP Lens runs from the snapshots.

### Upgrade of an existing installation

`backend/storage_migration.py` runs at startup under the storage lease (desktop and server), before requests are served, and never blocks startup.

1. Detect: no `store/` and an installation with settings or `csv-data` present, otherwise a fresh install (empty store, no backup).
2. **Verified backup first**, with the same archive engine as manual backups (`maintenance.backup` + `verify`, SHA-256 per file and for the archive), stored at
   `.application-backups/migration/<id>/pre-migration.tar.gz` with a JSON `record.json`. If it cannot be created and verified (space, permissions), the migration does not run and is retried at the next start.
3. Mirror every active snapshot into the store and prove each revision reads back with a valid digest. Any failure leaves the record `migrating`; the next start resumes with the same backup.
4. **Retention until confirmed.** The archive is kept until an administrator confirms in *Settings > Backup & Restore* (or `POST /api/storage/migration/confirm`). Confirmation re-checks the store and then releases
   the archive. Nothing deletes it by age; scheduled-backup retention only manages numbered operation folders.
5. Recovery: a damaged database is moved aside as `sap-lens.sqlite3.corrupt-<time>` and rebuilt from the snapshots; the pre-migration archive restores the previous installation byte-for-byte
   with the existing `maintenance.py restore` (tested). Because the JSON stores are never modified, an older SAP Lens can also be started on the upgraded directory.

### How SQLite and the JSON stores stay consistent

Every authoritative record has exactly one home; SQLite holds derived, verifiable copies.

| Event | Authoritative (JSON / snapshots) | SQLite store |
| --- | --- | --- |
| Import | Validated records are staged as an immutable snapshot; one compare-and-swap save of `settings.json` activates the new revision (or nothing changes). | After the commit, `reconcile` ingests that snapshot as the active revision (one transaction). A failure only means the snapshot is read next time. |
| Held (suspicious) import | Nothing is written; the active revision stays. | Unaffected. |
| Migration / upgrade | No conversion of review decisions, periods or evidence; formats unchanged. | Built from the snapshots after a verified backup; resumable; see above. |
| Backup | Archived with the snapshots, as before. Automatic backups expire after 90 days, manual and migration backups are protected ([backup retention](../deployment/BACKUP_RESTORE.md#scheduling-and-retention)). | Excluded (`store/`, `cache/`), so an archive never carries a second copy of source data. |
| Restore | The archive replaces the JSON stores atomically. | The destination's store is kept; it is reconciled to the restored configuration at the next start (new snapshot digests are ingested, a damaged store is rebuilt). |
| Cleanup / retention | Two categories, daily check, one-time approval each (see [Data retention](../operations/DATA_RETENTION.md)). Source: superseded, unreferenced snapshots aged from the logical *superseded* moment. Review: completed review periods aged from their completion timestamp, with journalled, recoverable removal; shared evidence, the report log and anything referenced stay. No cross-store atomicity is claimed. | Derived entries and revisions of a retired snapshot are removed first; orphans are removed on every run; superseded revisions beyond the kept two are pruned as before. |
| Concurrent server use | Existing locks and revision checks serialize writers. | WAL, short immediate transactions, busy timeout; reads never block on writers. |

## Data revision and client consistency

Every `/api/` response carries `X-Data-Revision: <boot>.<publication>.<directory>` and `GET /api/configuration` repeats it as `data_generation`.

* `boot` is random per process, so a restarted server is always newer; `publication` counts published SAP datasets; `directory` is the Employee Directory generation.
* The token is captured **before** the handler runs, so it can only be older than the data a response was built from, never newer. An old label on newer data costs one
  extra refetch; a new label on old data cannot happen.
* The frontend compares tokens per response (`frontend/src/lib/dataRevision.ts`, used by `frontend/src/api/client.ts`). A GET answered with an older revision than the
  application already knows is discarded and repeated once; a newer revision cancels and invalidates the dataset queries and re-reads the configuration at once instead of
  waiting for the 3-second configuration poll. Responses without the header (older servers) are ignored by the client.
* Filters, sorting, pagination and selection are client state and survive a revision change; a page that no longer exists is clamped, a record that disappeared shows
  the "missing or no longer matches" state.

## Review decision integrity

* **Account Review.** A decision is accepted only if the user's identity evidence version still matches (`evidence_version`), no other user saved a decision since it was
  loaded (`expected_decision`, enforced for authenticated users and for any client that sends it), and no new dataset was published between validation and write (checked
  under the load lock). Otherwise the answer is `409` and nothing is written.
* **SoD.** Decisions carry the evidence revision and generation they were made on (`expected_revision`, `expected_generation`) and are written under a publication guard.
  Snapshots, frozen periods and decisions are immutable private data; review decisions never change conflict detection.
* Older clients that do not send the newer fields keep working with the checks that applied before.

## Where to look

| Topic | Code | Tests |
| --- | --- | --- |
| Store, schema, signing | `backend/store_db.py`, `source_store.py`, `persistent_cache.py` | `test_source_store`, `test_persistent_cache`, `test_storage_migration` |
| Fingerprints, fast paths, diff | `backend/csv_lifecycle.py` | `test_csv_lifecycle` |
| Directory cache and matcher | `backend/employee_directory.py` | `test_directory_cache` |
| Revision token | `backend/cache.py`, `main.py` | `test_data_revision`, `frontend/tests/unit/data-revision.test.ts`, `frontend/tests/revision-consistency.spec.ts` |
| Measurements | `scripts/benchmarks/data_benchmark.py` | [Performance](../development/PERFORMANCE.md) |
