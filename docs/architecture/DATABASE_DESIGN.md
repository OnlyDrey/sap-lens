# Database design: SQLite as the system of record

One file, `sap-lens-v2.sqlite3`, in the data directory, for Desktop and Server. Schema in
`backend/src/SapLens.Persistence` (`SapLensDb`, `Entities.cs`, migration `Initial`, `ImmutabilitySql`).

## Tables

| Table | Purpose | Key constraints |
| --- | --- | --- |
| `Datasets` | One revision of one source (`roles`, `users`, `sod`): status Staged / Held / Active / Retired / Discarded / Failed, content hash, counts, import report and evaluation JSON, confirmation (who, when) | Unique `(Source, Revision)`; **unique filtered index `Source WHERE Status='Active'`**: one active revision per source, enforced by SQLite |
| `DatasetRecords` | Canonical mapped CSV rows as JSON, ordinal order | Unique `(DatasetId, Ordinal)`; FK cascade from dataset |
| `Jobs` | Persistent background jobs: status, attempts, lease owner and expiry, not-before, progress, cancel flag, result, error | Unique `IdempotencyKey`; index `(Status, NotBeforeUtc)` |
| `ReviewDecisions` | Append-only review decisions with the users revision they were made against and a SHA-256 hash chained to the previous row | Unique `Hash`; FK to dataset (restrict) |
| `ReviewInvalidations` | Append-only: an assignment key disappeared in an activated revision | FK to dataset (restrict) |
| `Backups` | Backup catalogue: kind (automatic, manual, migration), file, SHA-256, size, admin confirmation, deletion | Index `(Kind, CreatedUtc)` |

## Invariants enforced by the database (not only by code)

Triggers created by the migration (`ImmutabilitySql.Create`) abort:

- any `UPDATE` or `DELETE` on `ReviewDecisions` and `ReviewInvalidations`;
- any `UPDATE` on `DatasetRecords`;
- changes to `ContentHash`, `RecordCount`, `Source`, `Revision` of an Active or Retired dataset, and deletion of such a dataset.

Tests prove each trigger with raw SQL that bypasses EF Core [T]. Triggers stop accidental and application-level edits; they do not stop
someone with file access who drops a trigger first. For that case the review hash chain is verified by `GET /api/v1/admin/integrity`, and a
test drops the trigger, edits a decision and shows the chain reports the exact broken row [T].

## Connections and transactions

- Microsoft.Data.Sqlite, pooled, `Foreign Keys=True`, `Default Timeout` and an interceptor that sets `PRAGMA busy_timeout=15000` and
  `synchronous=NORMAL` on every opened connection; `journal_mode=WAL` is set once at initialization (persistent). [T]
- Short-lived `DbContext` per operation (`IDbContextFactory`, pooled).
- **A database file that is hashed, moved, replaced or deleted is opened without pooling.** A pooled connection keeps SQLite's file handle
  open after its `DbContext` is disposed. Linux allows hashing and renaming such a file; Windows refuses (`The process cannot access the file
  ... because it is being used by another process`). This broke every v1 migration run on Windows: the candidate was built and verified through
  pooled contexts and then hashed with `File.OpenRead`, whose `FileShare.Read` conflicts with the open read-write handle. The migration now uses
  `V1DataMigration.CandidateDb` (`Pooling=False`), so disposing the context closes the handle; `V1DataMigrationTests` assert through
  `/proc/self/fd` that no file of the migration folder stays open after a run. Integrity checks, backups, the account store and the
  maintenance commands already open their files without pooling or clear the pool first. Never use `SqliteConnection.ClearAllPools()` inside
  a running server for this: it also drops the server's own idle connections. [T]
- Explicit transactions for every write through `WriteCoordinator`: an in-process `SemaphoreSlim` (avoids busy-waiting between our own
  threads) **plus** a transaction that Microsoft.Data.Sqlite begins as `BEGIN IMMEDIATE`, so the cross-process guarantee comes from
  SQLite's file lock and never from the in-process lock alone.
- Evidence [T]: four separate OS processes plus the test process enqueue 300 jobs concurrently with no lost write; four worker processes
  compete for 150 jobs and each job is claimed exactly once with `Attempts=1`.

## Concurrency evaluation

| Question | Answer |
| --- | --- |
| Do reads block on an import? | No. WAL readers never wait for the writer; read P95 stayed within 10 % of steady state during a 101 k row import [M]. |
| Do writes starve during an import? | No. Staging commits every 5,000 rows; review writes interleave. Measured review write P50 9 to 16 ms, P99 about 1.2 s during a large import on 4 vCPU with 15 clients [M]. |
| Did any request fail with SQLITE_BUSY? | No, across all benchmark runs (0 server errors) [M]. |
| Single writer guarantee across processes? | Yes, by `BEGIN IMMEDIATE` and fenced conditional updates [T]. |
| Where does this stop scaling? | One writer at a time is the design. Hundreds of concurrent writers or remote users would need a different database; that is out of the stated scope (SQLite mandatory). |

## Paths

`DatabaseOptions.ValidateLocal` refuses relative paths, UNC paths (`\\server\share`, `//server/share`, checked before normalization),
URLs and, on Windows, network drives. SQLite locking is unreliable on network file systems. [T for the path forms, U for the Windows drive
type check]

## Dataset states added by the migration work

- `Purged`: a superseded revision whose records data retention removed after approval; the row (content hash, revision, record count, times)
  stays as evidence because activated datasets are never deleted (trigger `Datasets_NoDeleteActivated`). [T]
- Revisions migrated from SAP Lens 1 keep the v1 snapshot id in `ReportJson.migrated_from_v1.snapshot`; retention treats a reference to
  either id as a reference to the revision. [T]
- The SAP Lens 1 migration builds a separate candidate database under `migration/<id>/candidate`, verifies it, and activates it at the
  next start by replacing the database files (the previous files are kept for rollback). [T]

## Migrations

- EF Core migrations generated with `dotnet ef`, applied by `DatabaseMaintenance.InitializeAsync` at startup, never by hand.
- Existing database with pending migrations: an **online backup of kind `migration` is taken and integrity-checked first**, then migrations
  run, then the backup is recorded. Migration backups are retained until an administrator confirms the upgrade
  (Settings, Storage: `POST /api/storage/migration/confirm`; also `POST /api/v1/admin/backups/{id}/confirm-upgrade`). [T]
- Database with migrations unknown to this build (written by a newer version): left byte-for-byte unchanged, readiness reports not ready,
  no backup is written. [T]
- After initialization `PRAGMA integrity_check` and `PRAGMA foreign_key_check` must pass, otherwise the service stays not ready.

## Backups and retention

- SQLite Online Backup API (`SqliteConnection.BackupDatabase`) into a `.partial` file, integrity-checked, then renamed and hashed. Readers
  and writers continue during the copy. [T]
- Retention (`DataRetention`, backup category): automatic backups older than the approved period (default 90 days) after a one-time
  administrator approval; manual backups until a person deletes them; migration backups until an administrator deletes them after confirming
  the upgrade (never by retention). [T]
- Application backups, their schedule and restore: encrypted SLBAK3 archives of the database, account store and branding (`ApplicationBackups`,
  `BackupCrypto`), restored at the next start with rollback. See [MIGRATION_MATRIX.md](../migration/MIGRATION_MATRIX.md) (MIG-005). [T]

## Storage cost

The prototype stores canonical records as JSON rows. For the large synthetic set (97 k role rows, 101 k user rows, 1.8 k SoD rows) the
database holds every revision; retired revisions are kept as evidence. A product needs a retention policy for retired revisions or a
content-addressed record store (many revisions share most rows). Not measured: database file growth over many revisions.
