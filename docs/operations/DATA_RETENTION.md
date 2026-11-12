# Data retention

Retention keeps the data directory from growing without bound and never touches current data. This is the administrator guide; the storage design is in
[Storage, source revisions and data consistency](../architecture/STORAGE_AND_REVISIONS.md).

Retention keeps the data directory from growing without bound and never touches current data. It has **three separate categories** (source, review and [backup retention](../deployment/BACKUP_RESTORE.md#scheduling-and-retention): automatic backups 90 days), each with its own period (default **24 months**, 6 to 120), its own preview and its own one-time
administrator approval, configured in *Settings > Backup & Restore > Data retention*. Source rules are never applied to review records, and review rules never remove source data. The check runs **daily**, does not run while a
load, refresh, backup or restore is in progress, and removes nothing until the category has been approved.

## Source retention

| Eligible when superseded, unreferenced and older than the period | Never removed |
| --- | --- |
| Role, user and SoD-matrix snapshots; their SQLite revisions and derived values | The active revision of each source, the newest two previous revisions, anything referenced |
| Employee Directory snapshots | Settings, backups, the pre-migration backup (explicit confirmation) |
| Quarantined SQLite stores; pre-re-baseline copies of the lifecycle memory | Anything younger than the period |

* **Logical timestamps.** A revision ages from the moment it was **superseded** (recorded in the SQLite store when the next revision is activated, `retired_snapshots`). Data that predates that record (older installations, directory
  snapshots) has no reliable moment: it is protected until retention first sees it unreferenced and then ages from that moment. File times are only an extra guard (nothing with a recent file time is removed), never the basis.
* **Protection by reference.** Any 64-hex identifier named anywhere in the JSON stores or in a non-source snapshot protects the file it names; unclassified files are protected; if references cannot be read, nothing is removed.
* **Consistency with SQLite.** Derived entries and store revisions of a retired snapshot are removed first, the authoritative file last, each step idempotent; store revisions whose snapshot is gone are removed on every run.

## Review retention

Only a **completed** review period (Approved, Closed, Approved / closed) whose **completion timestamp** (the latest recorded transition into a completed state) is older than the period can be removed, together with the records it owns
exclusively: its entry in the period index (a deletion record stays: id, name, state, counts, time, reason, `data-retention` as actor), its decision events, risk acceptances, remediation actions and legacy risk reviews, and the private
snapshot files only it references (frozen period snapshots, retained decision evidence, review finding snapshots). The report log (issued reports are audit evidence) and every other period are kept.

| Protected | Reason shown in the preview |
| --- | --- |
| Draft, In review, Ready for approval, Rejected | Active or incomplete review period |
| No recorded completion transition (the approval date is typed by a person and is not a reliable moment) | Protected until classified; aged from the day retention first classified it |
| Completed within the period; the newest completed period | Within the retention period / comparison baseline |
| Open or in-progress remediation actions; risk acceptances that have not expired | Open remediation actions / Risk acceptance has not expired |
| A snapshot that fails its integrity check | Snapshot integrity could not be verified |
| The comparison baseline of a report that belongs to a retained period | Baseline of a report belonging to a retained period |

* **Shared evidence is preserved.** After the stores are rewritten, the data directory is scanned for identifiers; only files that nothing names any more (and that are of an owned kind) are moved away.
* **Recoverable, journalled removal; no cross-store atomicity is claimed.** The period index, decision store, review store and snapshot files are separate files. A full copy of the removed records and a journal are written first; stores are
  rewritten by id (idempotent); files go to a trash folder instead of being deleted. An interrupted run is **rolled forward** by the next one (it reads the journal; an unreadable journal pauses review retention rather than guessing). While
  copy and trash are kept (**30 days**, judged by the time recorded in the copy) the cleanup can be **undone** (`POST /api/retention/review/undo`, administrator). Deletion records and the history (last 100 entries) remain.
* **After a restore** both approvals are void, no cleanup runs for 7 days and a journal carried in the archive is discarded, so a recovered period cannot be purged again before an administrator has reviewed it.
* **Approval** is bound to the previewed data (a changed preview must be reviewed again), to this installation (an approval inside a backup restored elsewhere is void) and to the period (shortening it needs a new approval). Approving one category never approves the other.
* Comparisons to a purged period are no longer possible; findings first seen in it are then classified as new (the same consequence as the manual archive of a completed period, which only hides it and keeps everything).

`data-retention.json` (validated, included in backups) holds the policy, both approvals, the first sightings and the bounded history.

## Backup retention

Backups are classified from explicit metadata, never from file names or file times.

| Class | Rule |
| --- | --- |
| Automatic (scheduled) | Eligible after the retention period (default 90 days, 7 to 3650) counted from the recorded completion time, after the same kind of one-time approval |
| Manual | Never removed automatically; removed only by an administrator with the confirmed delete action |
| Migration | The pre-migration backup is kept until an administrator confirms the upgrade, and then until it is deleted explicitly |
| Unreliable metadata (unknown origin, unreadable record, no timestamp, unverified, digest mismatch) | Protected |

A backup that a staged restore uses, one involved in an active operation, and anything that is a link are never removed. The policy and the approval live in
`.application-backups/retention.json`, next to the backups and outside the data a restore replaces. Archives can contain historical records that source or review retention
removed from the live installation; restoring one brings them back, which is why a restore voids the source and review approvals and pauses cleanup for 7 days.

### Count limit and age limit

Automatic backups follow the approved age policy (default 90 days). The legacy
schedule count preference is retained for configuration compatibility but does
not delete recent archives. Only eligible automatic backups older than the
configured period may be removed, after the installation-bound administrator
approval. Manual, migration, unclassified and restore-protected archives remain
protected. See [Backup and restore](../deployment/BACKUP_RESTORE.md#scheduling-and-retention).
