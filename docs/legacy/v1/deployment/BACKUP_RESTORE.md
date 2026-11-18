# Application Backup & Restore

Settings → **Backup & Restore** transfers complete logical application data between
Desktop and server installations. It replaces a dataset rather than merging
independent histories. Server access requires an administrator session. Desktop
uses its launch capability. Never commit private archives or keys to Git.

**Where to find it.** Settings, Backup & Restore has four tabs: **Overview** (encryption key, create a backup, restore), **Backup History**,
**Scheduling** and **Retention**. A pending migration approval and the state of a running or waiting operation, with its cancel action,
stay visible above the tabs on every tab. Text typed into the restore form is kept while switching tabs.

## Contents and protection

New portable archives use the versioned `.slbak` envelope: AES-256-GCM with a new
nonce and authenticated metadata for every archive. A separate passphrase uses
scrypt; unattended archives derive a unique archive key from the protected host
recovery key. Pending restart keys are wrapped, never stored as plaintext.

The encrypted canonical manifest records application/settings/account schema,
creation time, component inventory and SHA-256 checksums. It includes imported
snapshots, settings, saved filters, Functional Groups, Account Review, SoD periods,
decisions, approvals, audit history, immutable evidence, branding/logos, report
branding, the Desktop reviewer profile and provisioned account/password verifiers.
Account SQLite uses the database backup API, not a live database/WAL file copy.
Source settings and snapshots remain authoritative; the derived cache is rebuilt.

Excluded: active sessions, usable activation/reset/recovery codes, login throttles,
TLS private keys/certificates, shared host secrets, host bindings, OS registration,
service XML, logs, locks, caches, operation history and recovery keys. A pending
password reset stays required after restore, but its original code cannot work;
an administrator or local recovery must issue another code. Legacy reviewer
strings and frozen evidence retain their bytes; identities are not guessed.

## Configure and escrow a key

Configure a private key **outside** application data and archive directories.
Desktop offers **Create recovery key**, **Use existing key**, and **Export recovery
copy** through its guarded native picker. Service Manager provisions an external,
ACL-protected key when saving configuration; **Export backup recovery key** makes
a create-only private copy. Browser users never select server filesystem paths.

Equivalent local commands (run from the repository; choose private absolute paths):

```text
python backend/server.py --maintenance init-backup-key --data /srv/sap-lens/data --output /srv/sap-lens-private/backup.key
python backend/server.py --maintenance check-backup-key --data /srv/sap-lens/data --key-file /srv/sap-lens-private/backup.key
python backend/server.py --maintenance export-backup-key --data /srv/sap-lens/data --key-file /srv/sap-lens-private/backup.key --output /mnt/private-escrow/SAP-Lens-recovery.key
```

Directories must already be private and exist. Use the packaged `SAP-Lens.exe
--maintenance` equivalent on Windows. Configure `SAP_LENS_BACKUP_KEY_FILE` in the
service environment; Docker mounts this **separately** from the data/backup volume.
Keys are random, create-only and owner-private (or an explicitly configured
service-group read permission). Never print them or place them beside archives.
No browser API changes a host key path. For unattended scheduling, verify the
separately stored copy in Settings before enabling the schedule. Rotating a key
requires a new copy verification. Keep old keys needed by older archives.

An optional confirmed archive passphrase can be used for manual backups. Keep it
separately. There is no forgotten-passphrase recovery. The host key is still
required to protect the pending operation across restart. Recovery keys are not
part of any application archive; restore cannot overwrite the destination key.

## Create and download

1. Select **Create backup (restart required)**. New editing and refresh pause.
2. Desktop: explicitly **Exit SAP Lens**, then reopen. Closing to the tray is not
   exit. Server: an operator restarts the Windows service/systemd unit/container.
3. Return to this section. **Ready** means encrypted round-trip/archive verification
   succeeded. **Download backup** uses a native Save dialog or browser download.

Individual application files are atomic, but there is no global transaction over
JSON histories, snapshots and SQLite. SQLite's online backup alone cannot provide
this consistent multi-store snapshot. Creation runs under the stopped runtime
lease before the listener and scheduler start. There is no remote restart API.

## Restore

1. Upload `.slbak` (Settings limit **256 MiB**). Supply its passphrase or exported
   recovery key; leave blank only when this host has the matching key. Secrets are
   transient, not retained in browser storage or operation metadata.
2. Authentication precedes parsing/extraction. Preview validates versions,
   checksums, typed stores, database integrity, exact component inventory, source
   references and branding assets. Unsafe paths, links, member types, duplicates
   and case collisions are rejected. Canonical limit: 4 GiB / 100000 files;
   encrypted archive limit: 2 GiB. Preview does not replace active data.
3. Confirm full replacement. An account-bearing archive requires a **separate
   acknowledgement of account/password rollback and session invalidation**.
4. Restart. An encrypted destination recovery backup is verified first. Journalled
   activation and post-restore checks run before application initialization.
5. Review the result and download the recovery backup when needed.

Destination service registration, TLS, key provider, bindings, deployment ownership
and Desktop host preferences are preserved. Account state changes only with the
explicit account acknowledgement. Sessions are invalidated. Sources become
Static, data refresh and the restored backup schedule are disabled. Review original
source paths before enabling Dynamic mode. Backup scheduling configuration is
portable; its operation history, retention approval and key escrow verification
remain installation-local. Source/review retention approvals are void and cleanup
pauses for seven days. Histories and immutable snapshots are not merged/relabelled.

Legacy unencrypted `.tar.gz` import requires explicit acknowledgement. Destination
accounts are preserved; legacy hosting credentials are never activated. New
backups are always encrypted.

## Stopped-host maintenance

`--maintenance backup --data ABS --output ABS.slbak --mode server` uses the same
complete encryption/snapshot pipeline. The runtime must be stopped; output is
create-only and separate from data and keys. `--maintenance verify --archive ABS
--data ABS --mode server` authenticates and verifies it. Add `--secret-stdin` to
read an original passphrase/exported key without placing secrets in arguments.

`--maintenance restore --archive ABS --data EMPTY_ABS --mode server
--confirm-restore` only accepts an empty destination. Add `--confirm-accounts` for
account-bearing archives; `--allow-legacy` explicitly permits legacy input. The
destination host key must already be configured. Host configuration directories
are intentionally excluded; preserve service XML/TLS configuration separately.
No existing installation is switched automatically. Service script actions reuse
the installed key environment. Native SCM acceptance remains a separate gate.

## Status and recovery

- **Idle:** prepare a backup or upload an archive.
- **Waiting for restart:** cancel safely or restart the host. Closing a browser
  does not restart a server; closing a Desktop window may leave its backend alive.
- **Preparing / Creating:** host-owned work cannot be cancelled by clearing a lock.
- **Ready:** download; failed downloads leave the archive available to retry.
- **Failed / Cancelled:** correct storage/key/compatibility issues, then retry.
  Interrupted creation becomes Failed at startup without changing active data.

Operations are private under `.application-backups`. Upload previews are bounded;
**Cancel restore preview** removes an inactive preview and its retention protection.
Corrupt operation metadata without a journal does not permanently freeze editing.
An interrupted activation rolls back on the next start. If rollback cannot finish,
startup stops and preserves the journal/evidence; never delete it to unlock editing.
Old pending unencrypted creations must be cancelled/reprepared rather than silently
creating another plaintext archive. Configuration loading and backup status are
independent requests with Retry actions.

## Scheduling and retention

Scheduling reuses validated five-field cron, minimum five-minute intervals and
Local/UTC/IANA zones. It schedules **restart-dependent requests**, not online
archives or automatic host restarts. Keep the runtime running; missed slots are
not replayed. Busy imports/other operations record a skipped occurrence. A verified
escrow copy is required to enable and execute a request.

| Class | Policy |
| --- | --- |
| Automatic | Default 90 days from recorded completion, with existing installation-bound administrator approval. The legacy count preference never deletes recent archives early. |
| Manual | Retained until explicitly deleted. |
| Migration | Retained until upgrade confirmation; confirmation retains it, deletion is a separate explicit action. |

Unreadable metadata, unknown origins, links, failed verification, pending operations,
recovery archives and archives used by restore previews stay protected. Deletion
retains the audit record. Data retention remains default 24 months and protects
active periods/evidence; see [Data retention](../operations/DATA_RETENTION.md).

## Validation boundary

Synthetic Linux tests cover encryption/tampering, wrong secrets, complete branding,
account UUID/verifier recovery, pending resets, session exclusion, rollback, exact
review history and snapshot transfer, source loading, scheduling and retention.
Browser tests cover encrypted/legacy upload, confirmations, cancellation and
responsive layouts. A restore into an empty target that is refused (wrong key, modified
archive) leaves the target empty, so it can be repeated. Docker backup, upgrade and
keyed recovery into a second installation were run against a real Linux Docker engine.
Native Windows Save dialogs/ACLs/WebView2, newly built SCM packages and real systemd
require their own acceptance. Prior
package acceptance does not certify this implementation.
