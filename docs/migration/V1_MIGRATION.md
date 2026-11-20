# Migrating SAP Lens 1 data to AuthLens

The administrator procedure for `AuthLens.Api --migrate-v1`. The design, guarantees and what is imported are in
[MIGRATION_STRATEGY.md](MIGRATION_STRATEGY.md#implemented-procedure---migrate-v1).

**Validation status.** The PowerShell steps below were run verbatim with PowerShell 7 on Linux against the Linux build, using the synthetic fixture
`backend/tests/AuthLens.Tests/Fixtures/v1-data`. That fixture was written by the SAP Lens 1 application and backup engine and holds
SoD decisions, an approved review period, remediation, legacy reviews and Account Review history.

- `backend/scripts/tests/v1-migration-procedure.ps1 -Exe <AuthLens.Api> -Root <new folder>` repeats the procedure with 12 checks:
  host key, preview with the recovery key file, refusal of a wrong key, run, activation at the next start, HTTP check, status, rollback.
- The passphrase mode is covered by `V1DataMigrationTests` and a CLI run with the passphrase on standard input.
- **Not yet run:** on Windows (PowerShell 5.1 or 7, Windows paths and ACLs), or against a copy of a real installation. Run the script on the Windows
  test VM and rehearse on a copy before any production migration.

## What you need

| Item | Notes |
| --- | --- |
| The SAP Lens 1 backup | An application backup downloaded from SAP Lens 1 (Settings, Backup and restore): `SAP-Lens-backup-<id>.slbak`. A SAP Lens 1 data directory or a legacy `.tar.gz` backup works the same way. The archive is only read. |
| Its secret | Either the **backup passphrase** chosen when the backup was created, or, for a backup created without a passphrase, the SAP Lens 1 **recovery key** file: the escrowed copy of the host key, one line of base64. AuthLens reads the archive header and asks for the right one. |
| AuthLens release | `server\AuthLens.Api.exe` from a verified release folder (`scripts\verify-release.ps1`). Windows 10 1903 / Server 2019 or later. |
| A new data directory | An empty folder for AuthLens data, outside the release folder. Migrating into a directory that already holds AuthLens data needs `--replace-existing` and keeps the previous data for rollback. |
| Disk space | About four times the size of the SAP Lens 1 data: the unpacked preview, the verified copy, the migration backup and the new database. |

The AuthLens server must **not** run on the data directory while you activate or roll back; both take effect at its next start. Preview and run
can be done while it is stopped or running.

## Procedure (Windows PowerShell 5.1 or 7)

```powershell
$Exe      = 'C:\ProgramData\AuthLens\releases\AuthLens-2.0.0-alpha.1-<build>-win-x64\server\AuthLens.Api.exe'
$DataDir  = 'C:\ProgramData\AuthLens\data'
$Work     = 'C:\ProgramData\AuthLens\migration'                      # reports of this procedure
$V1Backup = 'C:\ProgramData\AuthLens\migration\SAP-Lens-backup-<id>.slbak'
New-Item -ItemType Directory -Force $Work | Out-Null
```

### 1. AuthLens backup key (once per installation)

The migration backup of the SAP Lens 1 data is encrypted with the AuthLens host backup key. Without one, the preview warns and the migration
backup is stored unencrypted in the private data directory.

```powershell
New-Item -ItemType Directory -Force 'C:\ProgramData\AuthLens\keys' | Out-Null
& $Exe --backup-key create 'C:\ProgramData\AuthLens\keys\backup.key' --data-dir $DataDir
& $Exe --backup-key export 'D:\Escrow\sap-lens-recovery.key' --data-dir $DataDir   # store separately; verify later in Settings, Backups
```

### 2. Preview (dry run)

Passphrase backup: the passphrase is asked for without echo.

```powershell
& $Exe --migrate-v1 preview --source $V1Backup --data-dir $DataDir | Out-File -Encoding utf8 "$Work\preview.json"
```

Backup created without a passphrase (host key): pass the SAP Lens 1 recovery key file. It is read, never printed.

```powershell
& $Exe --migrate-v1 preview --source $V1Backup --v1-key-file 'D:\Escrow\saplens1-recovery.key' --data-dir $DataDir |
    Out-File -Encoding utf8 "$Work\preview.json"
```

Check the exit code and read the preview:

```powershell
$LASTEXITCODE                                              # 0 = preview written; 3 = refused, reason on the line above
$Preview = Get-Content "$Work\preview.json" -Raw | ConvertFrom-Json
$Preview.status                                            # previewed (or blocked)
$Preview.blockers                                          # must be empty
$Preview.warnings
$Preview.source.archive                                    # SAP Lens 1 mode, version, creation time, file count
$Preview.stores | Format-Table store, handling, count, note -AutoSize
```

A wrong secret, a damaged or altered archive, a member not listed in the archive manifest or a checksum mismatch is refused with exit code 3, and
nothing is unpacked. Review every store row: these are the counts that will be verified after the run.

### 3. Approve and run

The preview digest is the approval. The run refuses a source that changed after the preview, builds the migrated data in a separate database,
writes the migration backup and verifies everything. The active data is not touched.

```powershell
& $Exe --migrate-v1 run --id $Preview.id --approve $Preview.digest --data-dir $DataDir | Out-File -Encoding utf8 "$Work\run.json"
$Run = Get-Content "$Work\run.json" -Raw | ConvertFrom-Json
$Run.status                                                # verified
$Run.verification                                          # integrity, revisions, evidence_snapshots, review_chain, sod_chain, counts
$Run.backup                                                # migration backup file, SHA-256, encrypted
```

### 4. Activate (at the next start)

Stop the AuthLens server or service that uses `$DataDir`, then:

```powershell
& $Exe --migrate-v1 activate --id $Preview.id --approve $Preview.digest --data-dir $DataDir
```

Start the server or service again with its usual options. Before the database opens, the start applies the activation and logs either:

- `SAP Lens 1 migration <id> activated; the previous .NET application files are kept in migration/<id>/previous`, or
- `... was NOT activated and the current data is unchanged: <reason>`.

### 5. Verify

```powershell
(& $Exe --migrate-v1 status --id $Preview.id --data-dir $DataDir | Out-String | ConvertFrom-Json).status   # activated
```

Then, signed in as an administrator:

- **Settings, Storage:** the SAP Lens 1 migration backup waits for confirmation.
- **SoD:** review periods with their states, the approved period's frozen matrix, decisions with history, remediation actions. Also check User
  Access, Account Review with its history, and saved filters.
- **Data Sources history:** the SAP Lens 1 import reports.

A Server keeps using its account store. A SAP Lens 1 Desktop backup carries no accounts, so a new Server installation shows setup. Issue the first
administrator code with `AuthLens.Cli accounts-code --data <data-dir>`, from a source checkout; see [SERVER_NETWORK_ACCESS.md](../deployment/SERVER_NETWORK_ACCESS.md).
Retention cleanup pauses for 7 days after activation.

### 6. Roll back (if needed)

Stop the server, request the rollback, start again. The previous AuthLens files return, and the migrated files are kept in
`migration/<id>/rolled-back`.

```powershell
& $Exe --migrate-v1 rollback --id $Preview.id --data-dir $DataDir
# start the server; then:
(& $Exe --migrate-v1 status --id $Preview.id --data-dir $DataDir | Out-String | ConvertFrom-Json).status   # rolled_back
```

### 7. Finish

Once AuthLens has been checked over a full review cycle, confirm the upgrade in Settings, Storage. The migration backup is kept until an
administrator deletes it there; no retention removes it. Keep the SAP Lens 1 installation stopped, not removed, until then.

## Files and privacy

Everything the migration writes stays in the private AuthLens data directory:

- `migration/<id>/`: the preview, the report, the verified copy of the SAP Lens 1 data, the candidate, and after activation the previous files. It
  is owner-only on Linux and inherits the data directory ACL on Windows.
- `backups/v1-migration-<id>.slbak`: the migration backup, encrypted with the host key when one is configured.

The unpacked archive from the preview is deleted after a verified run. Secrets are never written to these files or printed.

## Limits

- An encrypted SAP Lens 1 archive is authenticated in memory: one AES-GCM stream with the tag at its end. Up to 1 GiB is accepted. For a larger
  installation, migrate from a stopped copy of the SAP Lens 1 data directory instead.
- SAP Lens 1 member limits apply as in SAP Lens 1: 100,000 files and 4 GiB.
