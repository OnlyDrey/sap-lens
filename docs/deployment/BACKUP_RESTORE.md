# Application Backup & Restore

Settings → **Backup & Restore** transfers full application data between Desktop
and server installations. It complements [stopped host maintenance](README.md#operations-health-and-diagnostics);
it does not merge independent histories. Server HTTP access requires individual
account authentication and an **administrator** account. Basic/shared-proxy/local
server deployments use host maintenance instead. Desktop uses its launch capability.

Application data also includes `functional-groups.json` (Functional Group catalogue, classifications and history; see [Functional Groups](../features/FUNCTIONAL_GROUPS.md#persistence-backup-and-migration)).

## Create a backup

1. Select **Create backup (restart required)**. Editing and scheduled refresh pause.
2. Desktop: explicitly **Exit SAP Lens**, then reopen. Closing to the tray is not
   an exit. Server: an administrator restarts the service/container/process.
3. Return to this Settings section and wait for **Ready**, then select **Download backup** to save the `.tar.gz` archive.
   Desktop uses a native Save dialog; browser clients download normally.

The archive contains application-owned imported snapshots, configuration, saved
filters, Account Review decisions, SoD decisions/history/evidence, review periods,
branding and retained application artifacts. Inventory is recursive, rather than a
short list of JSON files. Runtime tokens, logs, deployment credentials, certificates
and the backup operation store itself are excluded. Archives contain sensitive
personal and access data and **are not encrypted**. Restrict access and transfer
securely; do not commit them to Git or attach them to public issues/releases.

## Restore

1. Upload an application backup (`.tar.gz`, maximum **256 MiB compressed** through
   Settings). Larger archives require host maintenance. The engine's decompressed
   limit is **4 GiB / 100000 files**.
2. Read the source mode/version, creation time, data categories, files and snapshot
   counts. Validation checks version/schema compatibility, checksums, portable
   paths, duplicate/case collisions, member types, typed stores and active snapshot
   references. This preview does not replace active data.
3. Confirm **full replacement**, then select **Confirm restore on restart**.
4. Restart as above. Before replacement, SAP Lens creates a destination recovery
   backup. Replacement runs before configuration/cache initialization or HTTP
   startup, while holding the actual single-process storage lease.
5. Review the result and download the destination recovery backup when needed.

Destination binding, aliases, port, authentication accounts/credentials, TLS keys,
service registration, deployment marker and storage ownership stay on the destination.
The restored source's Desktop/server marker is not activated. IDs, event timestamps,
append-only history and frozen snapshots retain their original bytes.

Imported datasets remain in **Static** mode. Original source paths remain visible
for reference; they are not reread by Global Refresh. Reconfigure each path before
switching it to Dynamic. Scheduled refresh is disabled, and destination Desktop
preferences remain intact. Replacing sources later uses the usual complete-replacement
validation; restore never turns separate histories into one merged history.

## Recovery and storage

Private operation files live under `.application-backups` inside the configured
persistent data directory, so Docker volume persistence and existing service data
permissions apply. Operations use owner-only files/directories (Windows ACLs in
Desktop/service; Unix owner permissions). Unconfirmed upload previews are bounded
to three; completed/recovery backups remain private until the operator removes them
with the application stopped. Keep a separate protected copy of important backups.

Use **Cancel restore preview** to discard a validated inactive upload and its retention protection. Once confirmed or owned by recovery, only the protected pending-operation/restart workflow applies. Cancellation before restart preserves active data. Failed validation leaves it
untouched. Activation uses a journal and rollback; an interrupted activation is
rolled back on the next start. If rollback cannot complete, startup stops rather
than serving partially replaced data. Correct permissions/free space and restart,
or use stopped host maintenance with a retained recovery backup. A pending operation
also survives service/container restart in the persistent data volume.

The application never restarts the host or service automatically. In-flight edits
may finish before shutdown and are included in the automatic destination backup;
no requests or scheduled imports run during replacement because the listener has
not started. The first release requires a coordinated restart, not a live restore.

## Validation boundary

Synthetic Linux tests cover Desktop-to-server transfer, exact history/snapshot
preservation, durable CSV loading with former Windows paths, administrator and
capability checks, upload limits, checksum/preview integrity, cancellation,
automatic recovery backup, activation failure and interrupted rollback. Browser
checks cover Settings and light/dark layouts at 375, 800, 1280 and 1600 px.
Native Windows Save-dialog/ACL/WebView2 and real SCM/systemd restart acceptance
remain required; Linux unit/browser tests do not certify them.

## Why restart is still required

SAP Lens stores settings, immutable imported snapshots, review events, period indexes and
other application files using separate atomic replacements. There is no shared database
transaction or global writer barrier covering every file and scheduled refresh. The
canonical archive engine therefore uses the stopped-store/runtime lease before the listener
and scheduler start. Individual files being atomic does not make a live multi-file copy
transactionally consistent. This workflow deliberately retains restart rather than taking
an unsafe online copy. In-flight work may finish before shutdown; the archive captures the
final stopped state. No browser-accessible restart API is provided.

## Status, retry and recovery

- **Idle:** choose Create backup or select a restore archive.
- **Waiting for restart:** the request is persisted; new editing and scheduled runs pause.
  Cancel pending operation releases this restriction without replacing data. An already
  running refresh may finish; creation occurs only after restart, never alongside it.
- **Preparing / Creating:** host-owned work; cancellation cannot release an active operation.
  Archive creation/verification runs before the server becomes available. Reconnect and
  check this section after startup, rather than expecting a browser progress percentage.
- **Ready:** Download backup uses the Desktop Save dialog or a normal browser download.
  A download failure leaves the archive available; retry downloading.
- **Failed / Cancelled:** read the status, correct storage/permissions if necessary, then
  retry Create backup. Interrupted creation becomes Failed at next startup without changing
  application data. Legacy `pending` records display as Waiting for restart.

Malformed operation metadata without a restore journal is reported as Failed and does not
permanently freeze editing. If a restore journal remains, cancellation/new operations are
blocked; startup must finish rollback or stop for administrator recovery. Never delete that
journal to unlock the interface. Missing/corrupt metadata with a journal blocks startup.

Configuration is an independent GET: a waiting operation does not intentionally block it.
If configuration loading fails, use **Retry configuration**; Backup & Restore remains
accessible independently. This symptom alone does not establish corrupt settings or require
a restart. Archive upload is disabled only while another operation or local request owns
the workflow, not merely because configuration loading failed. **Check status** retries the
backup request; returning to the section or window refreshes retained operation status.

## Scheduling and retention

**Automatic backup scheduling** reuses Runtime & Scheduling's five-field cron,
minimum five-minute interval and Local/UTC/IANA timezone rules. Choose daily time or
advanced cron, retention (default **7**, range 1–100), then **Save backup schedule**.
It is disabled by default. Next requests, last success/failure and the last 50 request
outcomes are shown. Only the running, single leased backend evaluates schedules;
Desktop must stay running. Additional workers sharing storage are unsupported and
must not bypass the process lease. Missed downtime slots are not replayed.

**Important:** this release schedules **backup requests**, not unattended online
archives. A due request queues **Waiting for restart** and pauses new edits and
scheduled refresh until the administrator restarts the host or cancels the request.
Do not enable it unless this operational consequence is acceptable. Use deployment
maintenance scripts with an administrator-controlled service stop/start when fully
automated stopped-host backups are required. No browser can restart the host.

Concurrent duplicate occurrences are claimed once under the existing operation lock.
If import/refresh or another backup/restore is busy, the occurrence is recorded as
skipped, not retried invisibly. Archive creation still takes place only before the
listener/scheduler starts, so no import/refresh writes run during capture. Success
means archive verification completed; the filesystem/manifest engine is unchanged.
A conservative free-space check runs before archive and restore-recovery creation.

The **Backup history** table shows the latest 200 operations, source, timestamp,
archive size and verification result, with authenticated downloads and confirmed
deletion. Storage usage covers retained backup archives in the private application
backup area. Manual archives are never automatically removed. After successful
scheduled creation, only older verified scheduled archives beyond retention are
removed; active operations, restore recovery archives and originals matching a
staged restore are protected. Cleanup failure leaves the verified archive intact.
Schedules/history are destination-local operational metadata, excluded from exported
archives along with the operation store; restores do not activate another host's
backup schedule. Failed and deleted records remain traceable in history.

## Backup retention (three classes)

Backups are classified by explicit metadata written when they are created, never by file name or file time.

| Class | Metadata | Retention |
| --- | --- | --- |
| Automatic (scheduled) | `origin: scheduled` in the backup's `result.json` | Removed after **90 days** (configurable, 7 to 3650) counted from the **recorded** completion time, after a one-time administrator approval of the previewed set. The older count limit (`keep`, default 7) of the backup schedule still applies independently and needs no approval. |
| Manual | `origin: manual` | Kept until an administrator deletes it (the existing delete action requires confirmation and refuses while an operation is pending or a staged restore uses it). Never reclassified, never removed automatically. |
| Migration | `.application-backups/migration/<id>` | Kept until an administrator confirms the upgrade works; **confirming keeps it**, and it is deleted only by an explicit second step (*Delete pre-migration backup*). The automatic rule never applies to it. |

A backup without reliable metadata (no or unknown origin, unreadable or inconsistent `result.json`, no recorded time, not verified, archive missing or a link, digest mismatch, status other than ready) is protected. Cleanup refuses to run while a backup or restore is pending,
protects an archive that a staged restore uses, never follows links, and only acts on `backup.tar.gz` inside a numbered backup folder; a deleted backup keeps its small audit record (`status: deleted`). An interrupted cleanup (archive removed, record not yet updated) is completed by the next run.

#### Count limit and age limit together

Two independent rules can remove an automatic backup:

| Rule | Setting | Removes | Approval |
| --- | --- | --- | --- |
| Count limit | Backup schedule, *keep* (default 7) | Completed, verified automatic backups beyond the newest *keep*, as soon as a scheduled backup completes | None |
| Age limit | Data Retention, backup period (default 90 days) | Automatic backups older than the period | One-time administrator approval bound to the previewed set |

The period is a **maximum**, not a guaranteed minimum. With the defaults and one backup per day, only about the newest 7 backups exist, so a backup is normally gone after a week, long before 90 days. The age limit only matters when backups are less frequent than the count limit allows (for example weekly backups with *keep* 20) or when *keep* is large. Manual and migration backups are never removed by either rule.

Settings shows both rules above the cleanup preview. The preview names the rule behind every candidate (*Older than 90 days*, optionally *and beyond the newest 7 automatic backups*) and lists separately the younger backups that the count limit will remove at the next scheduled backup. The approval digest binds only the age-limit set and the period, so the informational count-limit list does not change an existing approval.

The policy and approval live in `.application-backups/retention.json`, next to the backups and outside the data a restore replaces, so a restore neither voids the backup approval nor brings an older copy back. Source and review retention work differently after a restore (their approvals are voided and cleanup pauses for 7 days; see
[Data retention](../data/IMPORT_AND_REFRESH.md#data-retention)). **Archives can contain historical records that source or review retention has already removed from the live installation**; restoring such an archive brings those records back.
