# Functional Groups

A Functional Group is the business function a person performs (Purchasing, Logistics, Finance). It is maintained by SAP Lens reviewers and is
independent of Directory Department, Job Title, Manager, Site and SAP User Group. It never changes SAP access.

## Data model

One store, `functional-groups.json` (format 2) in the application data folder, included in application backups:

| Part | Content |
| --- | --- |
| `groups` | Global catalogue: stable id `fg_<12 hex>`, unique name, description, `active` or `archived`, created and modified timestamps. Groups are archived; an archived group that nothing refers to can be deleted (see Settings below). |
| `users` | At most one record per canonical SAP user (the upper-cased user name, hashed as in Account Review): `group_id`, status, revision, confirmation time and reviewer, rationale, open review, handled change ids. |
| `history` | Append-only events: assigned, changed, confirmed, removed, review_required, reconfirmed, manager_changed. Each keeps user, previous and new group and status, actor, time, reason and the related organizational change id. |
| `rules` | Advisory suggestion rules (see below). |

Classification states: `Unassigned` (no group), `Confirmed`, `Needs review` (a group is kept but needs reconfirmation). A user can belong to several groups: a user record holds `memberships`, one entry per group with its own status, confirmation time and reviewer, rationale and open review. Every write is validated (names unique after Unicode, case and spacing normalization,
references resolve, status agrees with group) and replaced atomically. Changes carry the revision the reviewer saw; a stale revision is rejected
with HTTP 409 and never overwrites newer data.

Users are linked by the SAP user name, never by display name. Directory enrichment (Department, Title, Manager) stays on the existing
SAP-to-Directory match, which already refuses missing, duplicate and ambiguous matches.

## API

`/api/functional-groups`: list, create, rename or edit (`PATCH`), `archive`, `restore`, `DELETE` (archived and unreferenced only, otherwise 409); `users/{username}` reads and writes one classification
(`group_id` null clears it, rationale required when clearing); `history/{username}`. A reviewer name is required unless the server supplies the
signed-in actor.

## Backup and restore

The store is validated before a restore is activated (format, uniqueness, broken group references, contradictory states). Older backups without
the file restore to an empty catalogue.

## Settings and User Details

- **Settings > Functional Groups:** searchable table (name, description, assigned users, Active or Archived), create, edit and archive or restore.
  Duplicate names (case, spacing and Unicode-normalized) are refused. Archived groups stay on existing users and in history but cannot be newly assigned.
  The section has two tabs, **Groups** and **Suggestion Rules**; search text and the status filter (All, Active, Archived) are kept when switching.
  **Permanent deletion** is offered only for an archived group with no members, no suggestion rules and no classification history event, after an
  explicit confirmation. Any of those references keeps the group archived (the button is disabled and names the reason, the API answers 409 and changes
  nothing), so memberships are never dropped and every history event keeps resolving to its group. A new group can be created inside the suggestion
  rule dialog; it is created active and without members, is selected at once, and the rule fields are kept. Nothing is ever assigned by creating a
  group or a rule.
  **Users count:** one definition everywhere a group is listed in Settings (`user_count`): distinct users with a stored membership in the group,
  whatever its status (Confirmed or Needs review) and whether or not the user is in the current SAP import; archived groups keep their members and
  their count. The members dialog lists exactly those users. Filter choices in User Access and SoD show a different, labelled number: SAP users of
  the current import in the group. Zero is shown as plain text, a positive count opens its list.
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

## Account Review integration

There is no second queue. Functional Group review extends the existing Account Review rows, filters and dialog:

- **Rows** carry `functional_group`, `classification` (status, revision, open review), `classification_review`, `manager` and `manager_change`.
  A classification in `Needs review` counts as requiring review but never changes the SAP role decision (`review_state`): a role decision does not
  confirm the classification and the reverse.
- **Table:** one compact *Functional Group* column (group, `Needs review` pill, manager as a small second line). Findings list manager changes and
  Functional Group reconfirmation. New findings for the Review finding filter: `manager_change`, `functional_group_review`.
- **Filters** (Organization section, multi-select, OR within a filter and AND between filters, evaluated server-side before pagination):
  `functional_groups` (group ids or `unassigned`) and `managers` (imported manager mail, or `none`). Both are part of Saved Filters.
- **Review dialog:** a *Functional Group review* section for classified users shows the current group and status, Directory Department, Job Title
  and Manager before and after, the detection date and any advisory suggestion, with the classification actions **Confirm current group**,
  **Change group** and **Clear group** (plus **Keep unassigned** for an unassigned outcome). They are classification actions, not Keep, Remove or
  Investigate. A reviewer name is required, clearing requires a rationale, the outcome carries the change id that triggered it, and a stale
  revision is rejected with HTTP 409.
- **History:** classification events live in the Functional Group history (User Details and API `history/{username}`); SAP role decisions stay in
  the existing Account Review history.

## Filters in User Access and SoD

Functional Group and Manager filters (multi-select, server-side, so pagination and totals stay correct) are available in Account Review, User Access
and the SoD views that filter users (matrices, explorer, work queue, remediation). Group values are group ids or `unassigned`; manager values are the
imported manager mail or `none` (unmatched user or unknown manager). OR applies within a filter and AND with every other filter. `GET
/api/functional-groups/options` lists the choices with SAP user counts. User Access adds a compact *Functional Group* column.

In SoD the selection is translated into the existing username filter, so it only scopes what is shown and exported: conflict evaluation, risk and
activity definitions, decisions and approval gates are untouched. SoD subjects without a User Access record count as Unassigned (manager `none`)
unless classified. Frozen review periods are filtered by the current classification. The simplified Remediation CSV keeps its four-column contract;
adding Functional Group to an export would be a separate, optional enhancement.

## Access analysis (advisory)

Settings > Functional Groups > *Analyze access* (or `GET /api/functional-groups/analysis/{id}`) compares SAP access inside one group. It is read-only
and never grants, removes or approves access, creates accepted risks or changes review decisions; follow-up uses the existing workflows.

- **Data:** unique, currently active (user, role) pairs from the SAP user import; repeated intervals, activity rows and risk rows never count twice.
  Expired and future assignments are ignored.
- **Calculation:** frequency = members holding the role / compared members. *Common* is at least 60%, *uncommon* at most 25%, otherwise *shared*.
  A user's *additional uncommon roles* and *missing common roles* are the differences to prompt investigation, not violations.
- **Limitations shown instead of conclusions:** fewer than 3 comparable members, and classified members missing from the SAP user import.
- The dialog links to User Details and Compare users.

## Persistence, backup and migration

- `functional-groups.json` is written atomically after validation and survives restarts. It is part of the application data folder, so the existing
  [backup and restore](../deployment/BACKUP_RESTORE.md) carries it byte for byte (stable group ids, revisions, history and open reviews). A restore
  validates it first and rejects broken group references, contradictory states, duplicate names and unparsable files; an older backup without the
  file restores to an empty catalogue (restore replaces, it never merges).
- No migration is needed: databases without the file start with no groups and every user `Unassigned`. SAP, Directory and review data are never
  rewritten. The format is versioned (`format: 1`).
- Employee Directory imports never write classifications. Repeating an import is idempotent (change events are keyed by identity and import digest).

## Bulk assignment

`POST /api/functional-groups/bulk/preview` and `POST /api/functional-groups/bulk` (administrators, same mapping requirement as single classification) take stable usernames, never display names. The bulk write is one store write with history events and a repeated operation id is refused (409). Users already in the target group are `unchanged`; users in another group are only replaced with explicit confirmation (`replace_existing`); a classification that changed since the preview is a conflict; usernames outside the active dataset are rejected. Any skipped user makes the status `partial`, and the User Directory dialog retries only those. Imported SAP and AD data are never modified. The profile's *Assign group* uses the same classification model.


## Multiple memberships, suggestion rules and member management

- **Format 2 migration:** format 1 data (one `group_id` per user) is migrated losslessly on first read: each assignment becomes one membership with its status, confirmation metadata and history preserved, and existing rules become `department_mode: equals`. A one-time `functional-groups.json.format1.bak` is kept. Format 2 is not downgraded; older backups (format 1) are accepted on restore and migrated.
- **Writes:** `POST /memberships` adds one, `POST /memberships/remove` removes one (both idempotent, revision-checked), bulk assignment takes `group_ids` and only adds (`replace_existing=true` is rejected). The legacy `PUT users/{username}` still replaces all memberships. An organizational change (manager or department) marks every Confirmed membership `Needs review`.
- **Exports and filters:** existing columns are kept and join values with `; `; a `memberships` list is added. Singular `group`/`group_id` are present only when exactly one membership exists. Filters match any membership and counts are unique users.
- **Suggestion rules:** advisory only. Directory Department is matched case-insensitively by "contains" (legacy rules keep exact matching and show "Exact match (existing rule)", convertible in Edit), Job Title by contains; both stated conditions must hold (AND), at least one is required, and a missing Directory attribute never satisfies a condition. Matching users are SAP users uniquely linked to a Directory employee; ambiguous or unmatched users are never assigned.
- **Rules UI:** table with matching-user counts, View Matches (search, select all for the filtered set, pagination, already-assigned flag) and assignment through the bulk add flow with explicit confirmation and audit.
- **Members and analysis:** Settings "View Members" lists status, last confirmation and supports add and bulk removal; Access Analysis shows KPI tiles (Members, Compared, Distinct roles, Common roles, Potential deviations) and a Has role / Missing role drilldown over exactly the compared users. Patterns are labelled Common, Shared and Uncommon.
- **Validation:** Linux only (backend unit and Playwright); native Windows behaviour is unverified.
