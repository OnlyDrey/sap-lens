# Backup and recovery

How AuthLens protects its data: encrypted application backups, the host recovery key, automatic backups, retention, restore, and the upgrade
confirmation that releases migration backups. Implementation: `backend/src/AuthLens.Application/Backups` and `backend/src/AuthLens.Api/V1Backups.cs`;
storage model: [database design](../architecture/DATABASE_DESIGN.md#backups-and-retention).

Status legend: **Verified** (automated tests; Linux historical results and Windows continuation results are recorded separately in [release status](../migration/RELEASE_STATUS.md)), **Awaiting Windows acceptance** (implemented and tested with mocks or on Linux; the native
Windows run in the [acceptance checklist](../deployment/WINDOWS_DEPLOYMENT.md#acceptance-checklist-windows-pending) is still open).

## Managed imports and portability

Successful imports now keep an immutable, content-addressed CSV under `data/sources/<source>-<SHA-256>.csv`. The dataset report stores its relative path, original display filename and checksum in the existing database; no schema or migration identifier changes. A valid held candidate keeps its own copy for confirmation, while invalid/cancelled imports never replace the active copy. Repeated identical bytes reuse the same file. Cleanup retains active/held references and removes unreferenced generated copies under the same database write-reservation order used by backups; cleanup failures are logged without changing a completed import's result.

The existing encrypted backup engine includes those referenced files from the same database snapshot, verifies their hashes and rejects traversal, links, missing copies, unreferenced archive source entries and mismatched metadata. Restore moves the source directory with the rest of the staged data and preserves it in rollback. Active source paths are rebound to the restored machine's own copies and made static. For sources without an archived managed copy, restore clears the old machine's absolute path and makes the source static while preserving its durable observations; external connections must be configured explicitly. TLS, host keys, service configuration and browser profiles do not travel in the archive. Historical SAP Lens archives without raw source copies remain restorable through their durable observations. Exact raw files cannot be reconstructed for imports made before this feature: a successful reimport is needed to add their managed copy.

Synthetic Windows tests cover portable restore after deleting the entire source fixture, wrong/corrupted archives and protective restore over existing data. A real private backup/recovery key and elevated installer/service acceptance remain separate prerequisites; synthetic passes are not real-data acceptance.

## Shared engine and update recovery

Administrative UI create/restore and CLI `--backup-local`, `--backup-verify` and `--restore` use `ApplicationBackups`, not separate archive
implementations. Its online SQLite snapshot includes persistent settings, all dataset revisions, Account Review history, immutable SoD decisions,
remediation history, periods and content-addressed evidence. Required external payloads are the referenced managed CSV copies, validated branding
PNG files and the account database with active sessions removed. Arbitrary unreferenced files next to the database are deliberately excluded.
Machine TLS, service arguments/credentials, host/recovery keys and WebView2 profiles remain outside the portable archive and must be preserved
separately. A passphrase archive still requires a protected destination host key before restore confirmation; this prerequisite is unchanged.

Permanent local-account deletion removes credentials, sessions and one-time codes from the live account store, and minimizes linked security-audit
names while retaining opaque accountability. It does not erase immutable business evidence or existing encrypted backup snapshots. In particular,
restoring a backup taken before deletion can restore the deleted account; review the restored account list and administrator access before
reopening network access. Keep the verified protective backup under the normal explicit retention policy; do not silently rewrite or delete it.

`V1DataMigrationTests` now round-trips the existing application-written synthetic v1 fixture through an AuthLens portable archive into fresh
canonical storage and rechecks its review history, SoD chain IDs, periods, remediation and frozen evidence through public routes. This is an
isolated fixture test, not another migration of an existing installation. `LegacyRestoreTests` verifies SAP Lens .NET archives and cross-machine
managed files without activating obsolete absolute source paths. Application backup route tests verify archives with the CLI maintenance engine.

Manual installer updates use this same engine before replacing programs. They preserve all private configuration and refuse schema-changing
updates because an older executable may not open migrated data. Failed readiness restores and probes the previous executable only when schema
history and recovery hashes still agree; it never automatically rewinds business data. Keep every incomplete journal, previous program and
verified archive until recovery is resolved. See [manual installer recovery](../deployment/WINDOWS_DEPLOYMENT.md#interrupted-setup-and-recovery).

## Who may do what

On a **Server**, backups, restore, storage, retention and key administration need a signed-in **administrator account**; a shared access token is
refused (403), so a token holder can never export or replace all data. On the **Desktop** the local user is the operator.

## Backup archives (Settings > Backup & Restore)

The page has four tabs: **Overview** (key status, last backup, create), **Backup History**, **Scheduling** and **Retention**.

| Action | Behaviour | Status |
| --- | --- | --- |
| Create | An online, consistent copy of the SQLite database and the private files next to it, packed and encrypted with the host key (format `SLBAK3`, AES-256-GCM in 1 MiB segments). An optional passphrase adds a second, portable secret. The archive is verified after writing | Verified |
| History | Every archive with origin (manual, automatic, recovery, migration), size, SHA-256 and verification state | Verified |
| Download | `AuthLens-<kind>-<id>.slbak`; refused when the file no longer matches its recorded SHA-256 (409) | Verified |
| Verify | Decrypts and validates an archive as a restore would, without changing anything | Verified |
| Delete | Manual and automatic archives only, with explicit confirmation; refused while a restore or another archive operation is pending. Migration and recovery backups are not deleted here | Verified |

From a command line (no running server needed): `AuthLens.Api --data-dir <dir> --backup-local <folder>` writes a verified archive and
`--backup-verify <file>` validates one. The deployment scripts use these before every service switch.

## Recovery key

Archives are encrypted with the **host backup key**, a file outside the data directory (`C:\ProgramData\AuthLens\backup` by convention). The data
directory records only its location (`backup-key-location.json`). Without the key, no archive can be restored, so a **recovery copy** must be kept
somewhere else and verified.

- **Status and fingerprint:** Settings > Backup & Restore > Overview, or `AuthLens.Api --data-dir <dir> --backup-key status`. The fingerprint
  identifies the key; the key itself is never shown or returned by any API.
- **Initial provisioning:** `--backup-key create <file>` (a new private key file, then used) or `--backup-key use <file>` (an existing key).
  An existing key is never replaced by these commands.
- **Recovery copy:** `--backup-key export <file>` writes a new private file only; then **verify** it (Overview > verify recovery copy, or
  `--backup-key verify <file>`). Automatic backups stay disabled until a recovery copy has been verified.
- **Windows Service Manager:** `backend\scripts\Service-Manager.ps1` (elevated) offers `Status`, `CreateKey`, `ExportKey`, `VerifyKey`,
  `ActivationCode` and `RecoveryCode` against the packaged `AuthLens.Api.exe`, without restarting the service. Key values never appear in its output
  or process arguments. Status: awaiting Windows acceptance.

## Automatic backups (Scheduling tab)

| Rule | Behaviour |
| --- | --- |
| Frequency | Daily at a time, or weekly on a weekday at a time |
| Time zone | Explicit: the machine's local zone, UTC or an IANA name; the next run is shown in that zone |
| Daylight saving | A slot inside the spring gap is skipped; a repeated autumn hour runs once (synthetic-clock tests) |
| Persistence | `backups/schedule.json` with an optimistic revision; survives restarts |
| Execution | Inside the server process, evaluated every 20 seconds. One evaluation at a time: an in-process lock and a cross-process lock file (`backups/schedule-execution.lock`), so two processes never run the same slot |
| Missed slots and crashes | Missed slots are skipped, never replayed after downtime. An attempt interrupted by a crash is reconciled at the next evaluation: completed when its archive exists and is verified, otherwise recorded as failed |
| Failures | Recorded with the reason and shown on the Scheduling tab |
| Prerequisite | A verified recovery-key copy |

Status: verified on Linux; a native run over a real schedule slot is part of the Windows acceptance checklist.

## Retention (Retention tab)

Retention never deletes without approval. A preview lists what a policy would remove; only an approved preview is applied, after its waiting
period. Defaults: automatic backups 90 days, manual backups until a person deletes them, migration backups until the upgrade is confirmed and then
deleted explicitly. Archives held by a pending restore and completed review periods (immutable audit evidence) are never removed.

## Restore

1. Upload an archive (Backup History > restore). It is decrypted and validated, and a preview shows what it contains. Nothing changes yet.
2. Confirm the restore. It is applied at the **next start** of the server or Desktop, after an encrypted **recovery backup** of the current data.
3. If applying fails at start, the previous data returns automatically and the failure is reported. A pending restore can be cancelled.

On a **fresh installation** (no data yet) there is nothing to protect, so the recovery backup is skipped; activation still rolls back to the
empty state if applying fails. Without the UI, a fresh Server installation restores offline (service stopped):
`AuthLens.Api --data-dir <dir> --restore <file.slbak> --replace-all-data`, with the host key already in place (`--backup-key use`) and, for a
passphrase-protected archive, `AUTHLENS_BACKUP_PASSPHRASE` set. The managed Windows path wraps this as `Deploy-AuthLens.ps1 -Action Restore`
([migrating from SAP Lens](../deployment/WINDOWS_DEPLOYMENT.md#migrating-from-sap-lens)).

SAP Lens 1 archives are not restored this way; they are imported with the [v1 data migration](../migration/V1_MIGRATION.md).

### Archive compatibility

| Archive written by | Read by AuthLens | Notes |
| --- | --- | --- |
| AuthLens (product `AuthLens`, entry `authlens.sqlite3`) | Yes | Current format `SLBAK3` |
| SAP Lens (.NET, products `SAP Lens 2`/`SAP Lens`, entry `sap-lens-v2.sqlite3`) | Yes, restore only | Verified under its original entry name, then staged as `authlens.sqlite3`; same schema and key derivation, so cross-machine restore needs only the archive and its key [T] |
| SAP Lens 1 (`SLBAK2`) | Through the v1 data migration | Not a restore |
| Unknown product, two database entries, legacy entry with an AuthLens manifest, newer schema | Refused | Nothing changes |

AuthLens archives are **not** readable by SAP Lens (forward compatibility only). The encryption labels inside the format keep their original
SAP Lens wording; they are part of the key derivation and are never renamed.

## Upgrade confirmation and migration backups

Before schema migrations, and when SAP Lens 1 data is migrated, AuthLens writes a protected migration backup. Settings > Storage shows the
integrity check separately from the **upgrade confirmation**: confirming that the upgraded installation works is an explicit administrator action
and does **not** delete the migration backup. Deleting it is a further, separate confirmation.

## Deployments

Every managed Windows deployment takes and verifies an encrypted pre-deployment backup with the running release before it stops the service, and
never restores an older database automatically ([Windows deployment](../deployment/WINDOWS_DEPLOYMENT.md#deployment-sequence)).
