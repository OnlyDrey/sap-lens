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
