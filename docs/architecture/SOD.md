# SoD architecture

Technical reference for the Segregation of Duties module. User workflow:
[SoD guide](../features/SOD.md). Source schema and evaluation policy:
[SoD matrix](../data/SOD_MATRIX.md). Routes: [API](API.md#sod-api).

## Layers and boundaries

| Layer | Modules | Responsibility |
| --- | --- | --- |
| Evidence | `sod_import`, `sod_analysis` | Matrix import; deterministic two-sided potential conflicts (`sod-two-sided-v1`) with full evidence paths. Never reads review data. |
| Derivation | `sod_governance` | Pure functions over user findings: assignments, activities, matrices, explorer rows, what-if, remediation rows. No I/O. |
| Context | `sod_scope` | Resolves one review context to evidence: `current` (live) or a period id (that period's snapshot). Shared filters, decision state, conservative "resolved" and verification checks. |
| Decisions | `sod_decisions` | Private append-only events for activity, assignment and risk-acceptance decisions, remediation actions and the report log. |
| Periods and reports | `sod_periods`, `sod_reports` | Frozen snapshots, workflow, deletion, formal and remediation report models and renderers. |
| Legacy | `sod_reviews` | Risk-level decisions recorded before SoD 2.0. Retained, read-only in the UI, never reinterpreted. |

Review decisions never alter the conflict calculation. A conflict stays detected after
approval or acceptance, and only later imported evidence can stop supporting it.

## Review population and identities

The population is derived from detected current user findings, so matrices, queue,
remediation and reports agree. Identities avoid labels and row positions:

| Item | Identity |
| --- | --- |
| Finding / risk acceptance | `finding_id` = digest(user, risk, policy) |
| Activity review | digest(`sod-activity`, user, activity) per context |
| Role assignment | digest(`sod-assignment`, user, assigned role, validity from/to, user group) |
| Remediation action | random id; references user, assignment, activity, risk |
| Period snapshot | SHA-256 of the immutable snapshot file |

Evidence versions decide when a decision needs reassessment: activity = user + activity +
matched matrix transactions; assignment = assignment + activities/transactions it supplies;
acceptance = the finding evidence version (also expires with its date). A changed version
marks the decision **Outdated**; history is never deleted. A decided item that disappears
from evidence is **Resolved** only when the user remains in a complete, mapped source and
the matrix version is unchanged, otherwise **Historical**.

## Stores (private, atomically written, backed up with the application data)

| File | Content |
| --- | --- |
| `sod-decisions.json` | Decision events per context and kind, actions with history, report log. Evidence at decision time is retained as content-addressed snapshots. |
| `sod-periods.json` | Period index, workflow history and deletion records. |
| `sod-reviews.json` | Legacy risk decisions (unchanged). |
| `sod-catalogue.json` | Local risk metadata and, in the optional `activities` map, local English-only activity metadata (display name, area, explanation, guidance, notes, color). Imports never modify it. |
| `report-branding.json` | Pointer to the optional report-only logo (a sanitized PNG under `branding/`). |
| `sod-observations.json` | Finding ids at the last observed source refresh, for "changes since refresh". Bounded; rebuilt on demand. |
| snapshot files | Immutable period snapshots and decision evidence; integrity-checked by SHA-256. |

Portable configuration and diagnostics exports exclude all of them. Names (reviewer,
approver, actor) are self-reported text, not authenticated identities or signatures.

## Workflow

`Draft → In review → Ready for approval → Approved → Closed`, with `Rejected` (reason
required) returning to `In review`. Gates: entering Ready/Approved requires every conflict
relevant activity and every risk acceptance to be decided and current. Role assignment
decisions are recommended but do not block approval. Approval needs a different reviewer
and approver, an approval date and confirmation, freezes the snapshot together with a copy
of the decisions, actions and verification, and cannot be undone. Closing is final.
Reopening an approved period is not supported; create a new period.

## Deletion

Every status can be deleted. An empty Draft is erased permanently with its snapshot. Anything
else is tombstoned: `deleted_at` is set and a `Archived` event is appended to the period history,
while the snapshot, approval record, decisions, actions and report log stay on disk. Tombstoned
periods are excluded from active work, matrices, comparisons, baselines and report generation.
All deletions require the exact period name, a recorded actor and a single atomic index write.
Archiving needs an impact confirmation; approved/closed periods, periods with issued reports
and periods used as a report baseline also need a history confirmation, and approved/closed
periods need a reason. The deletion record keeps reason, actor, previous state and counts.
Other periods and current decisions are never modified (no cascade). `deletion-impact`
previews counts and warnings and never changes state.

## Feature toggle

`features.sod` is a manual setting (default off, never enabled by importing a source). Settings
saved before it existed are migrated once: with a SoD source present it is enabled, otherwise off.
While disabled, `analyze()` runs with `sod_enabled=False` (coverage reason `sod_disabled`), dynamic
SoD refreshes are skipped and the UI hides the entry; stored data is untouched.

## Review workspace and queue

`/api/sod/queue/users` groups the review items by user with independent progress per review type.
`/api/sod/subject` returns the focused investigation plus an `overview` with every activity,
assignment and risk of the user, which feeds the three review sections of the workspace.

## Migration and compatibility

No data is rewritten. New stores are created on first use. Periods created before SoD 2.0
carry no model marker: they keep the legacy workflow (`Approved / closed`), legacy gating
and legacy review editor, and their reports state that activity, assignment and risk
acceptance decisions were not recorded. Legacy risk decisions appear in the investigation
panel as history and are not converted, because an activity approval or risk acceptance
cannot be inferred from them. Saved filters gain new views; existing ones are untouched.

## Performance limits

Matrices page 50 users at a time (max 200) and window columns above 48. Up to 500 columns
are returned (narrow with filters beyond that). Decision stores allow 100,000 subjects,
500 events each; batches are limited to 100 items. Reports are limited to 20,000 table rows.
