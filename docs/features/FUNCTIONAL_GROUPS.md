# Functional Groups

A Functional Group is the business function a person performs (Purchasing, Logistics, Finance). It is maintained by SAP Lens reviewers and is
independent of Directory Department, Job Title, Manager, Site and SAP User Group. It never changes SAP access.

## Data model

One store, `functional-groups.json` (format 1) in the application data folder, included in application backups:

| Part | Content |
| --- | --- |
| `groups` | Global catalogue: stable id `fg_<12 hex>`, unique name, description, `active` or `archived`, created and modified timestamps. Groups are archived, never deleted. |
| `users` | At most one record per canonical SAP user (the upper-cased user name, hashed as in Account Review): `group_id`, status, revision, confirmation time and reviewer, rationale, open review, handled change ids. |
| `history` | Append-only events: assigned, changed, confirmed, removed, review_required, reconfirmed, manager_changed. Each keeps user, previous and new group and status, actor, time, reason and the related organizational change id. |
| `rules` | Advisory suggestion rules (see below). |

Classification states: `Unassigned` (no group), `Confirmed`, `Needs review` (a group is kept but needs reconfirmation). One group per user is
structural: a user record has a single `group_id`. Every write is validated (names unique after Unicode, case and spacing normalization,
references resolve, status agrees with group) and replaced atomically. Changes carry the revision the reviewer saw; a stale revision is rejected
with HTTP 409 and never overwrites newer data.

Users are linked by the SAP user name, never by display name. Directory enrichment (Department, Title, Manager) stays on the existing
SAP-to-Directory match, which already refuses missing, duplicate and ambiguous matches.

## API

`/api/functional-groups`: list, create, rename or edit (`PATCH`), `archive`, `restore`; `users/{username}` reads and writes one classification
(`group_id` null clears it, rationale required when clearing); `history/{username}`. A reviewer name is required unless the server supplies the
signed-in actor.

## Backup and restore

The store is validated before a restore is activated (format, uniqueness, broken group references, contradictory states). Older backups without
the file restore to an empty catalogue.

## Settings and User Details

- **Settings > Functional Groups:** searchable table (name, description, assigned users, Active or Archived), create, edit and archive or restore.
  Duplicate names (case, spacing and Unicode-normalized) are refused. Archived groups stay on existing users and in history but cannot be newly assigned.
- **User Details > Functional Group:** shows the group and classification separately from the imported Directory fields. A reviewer can assign,
  change, confirm or clear. Nothing is preselected, the action button names the outcome ("Assign Purchasing", "Change to Logistics", "Confirm
  Purchasing"), the reviewer name is required (the signed-in actor in server mode) and clearing requires a rationale.

## Suggestion rules

Advisory only. A rule has an optional Directory Department (equals, ignoring case, spacing and Unicode form) and an optional Job Title text
(contains); at least one is required, and when both are present both must match. There is no precedence: every matching rule on an active group is
listed with its reason (for example "Directory Department = Supply Chain and Job Title contains Purchaser"). A single suggestion is offered only
when all matching rules name the same group; otherwise the dialog says the match is ambiguous and the reviewer chooses. Suggestions never assign
a group and are only computed from an unambiguous Directory match.

## Organizational change handling

Employee Directory imports reuse the existing change detector (`position_changes.py`); there is no second detector. Imports never write
Functional Groups. Stored change events are applied to classified users when Account Review or User Details is read (idempotent, never failing the read):

| Directory change | Functional Group | Account Review |
| --- | --- | --- |
| Directory Department or Job Title (known value replaced by a different known value) | Group is kept. Status becomes `Needs review` with the reason and the change id. Only an explicit confirm, change or clear (with the change id) returns it to `Confirmed` or `Unassigned`. | Existing Position change priority review. |
| Manager (known manager replaced by a different known manager) | Group and status untouched. A `manager_changed` history event is added once. | `manager_change` signal on the row (organizational review, not a mandatory reconfirmation). The new manager gets no review permission. |

Idempotency: events are identified by identity and import digest. A change is applied only when detected after the user's last confirmation, and each
change id is applied once, so repeating an import or re-reading never resets a completed review; a genuinely new change creates a new requirement.
Missing values, formatting-only differences, ambiguous identities and suspiciously incomplete imports create no change. Users without a group are not
flagged. No SAP role is removed or granted by any of this. Reporting relationships are the imported direct-report links (manager mail, then account
name, then DN); they are never inferred from Department and there is no recursive hierarchy.
