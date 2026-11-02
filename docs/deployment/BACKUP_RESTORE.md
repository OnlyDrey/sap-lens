# Application Backup & Restore

Settings → **Backup & Restore** transfers full application data between Desktop
and server installations. It complements [stopped host maintenance](README.md#operations-health-and-diagnostics);
it does not merge independent histories. Server HTTP access requires individual
account authentication and an **administrator** account. Basic/shared-proxy/local
server deployments use host maintenance instead. Desktop uses its launch capability.

## Create a backup

1. Select **Prepare backup on restart**. Editing and scheduled refresh pause.
2. Desktop: explicitly **Exit SAP Lens**, then reopen. Closing to the tray is not
   an exit. Server: an administrator restarts the service/container/process.
3. Return to this Settings section and download the completed `.tar.gz` archive.
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

Cancellation before restart preserves active data. Failed validation leaves it
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
