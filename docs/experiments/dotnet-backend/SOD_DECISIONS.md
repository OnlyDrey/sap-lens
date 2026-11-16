# SoD decisions (MIG-014): v1 contract and .NET status

The Python v1 reference is `origin/work`: `backend/sod_decisions.py` (store), `backend/sod_governance.py` (pure model), `backend/sod_scope.py`
(context bundle, verification), `backend/assignment_lifecycle.py` (reappearance) and `backend/routers/sod_governance.py` (routes). This page records
the behavior the .NET port must keep; [MIGRATION_BACKLOG.md](MIGRATION_BACKLOG.md) tracks what remains.

## Review population and identities

- `derive(findings)` indexes the current-potential user findings into per-user **activities**, **assignments** and **findings**.
- Assignment key = SHA-256 of canonical JSON `["sod-assignment",1,user,role,valid_from or "",valid_to or "",user_group]`; activity key =
  `["sod-activity",1,user,activity]`; a risk item is keyed by its `finding_id`.
- Evidence versions: activity `["sod-activity-evidence",1,user,activity,sorted tcodes]`; assignment
  `["sod-assignment-evidence",1,id,sorted [activity,tcode] pairs]`; finding `evidence_version` from the analysis.
- Keys and versions must stay byte-identical to v1, or migrated decisions would read Outdated.

## Decisions

| Kind | Decisions | Extra rules |
| --- | --- | --- |
| `assignment` | Pending, Keep, Remove, Investigate | |
| `activity` | Pending, Approved, Conditional, Remove, Investigate | Conditional needs controls |
| `acceptance` | Pending, Accepted, Rejected | Non-Pending needs a named approver; optional expiry, not in the past |
| `risk` | Pending, Approved, Remove, Investigate | Approver and expiry only for acceptance |

- Every event: `event_id` (32 hex), `bulk_operation_id`, `previous_decision` (the subject's prior decision), `kind`, `context`, UTC `timestamp`, `key`,
  `user`, `ref`, `decision`, `reviewer`, `approver`, `justification` (required), `controls`, `expires`, `evidence_version`, `evidence_snapshot`
  (content address of the evidence the decision was made against), `source_versions`, optional `actor_identity`.
- Append-only history per (context, kind, key), at most 500 events per key, at most 100 items per call (1000 for bulk); text without control characters.
- One store-wide `revision`: every write needs `expected_revision` equal to it (409 "SoD decisions changed. Reload before saving." otherwise) and
  increases it by one. All items of a call are written or none.
- The context must be reviewable (live `current` with active validity, or a Draft/In review period) and the evidence `generation` unchanged (409).
- Each item must still be located in the current model with the same key and evidence version (409), otherwise nothing is written.

## Lifecycle and derived status

- `lifecycle`: no event → Pending; evidence gone → Historical; version changed, acceptance expired (before today) or decision older than the
  assignment's reappearance → Outdated; Remove → Removal required; otherwise the decision.
- Coverage (assignment → activity → risk): Keep/Removal required reviews an assignment; an activity is reviewed explicitly or when all its
  assignments are; a risk is reviewed by acceptance, risk review or all its activities; a formal acceptance covers its activities afterwards.
- `effective_decision`: an explicit current decision wins; an activity otherwise derives Approved (any Keep), Remove (all Removal required) or
  Investigate; a stale Remove stays visible; disagreement between explicit and derived activity decisions is reported. Acceptance is presented
  separately (`decision_summary`).
- Reappearance (`assignment_lifecycle`): an assignment with a decision that becomes verifiably absent and later returns, or whose user identity
  evidence (unshared e-mail, full name hashes) changes completely, makes earlier decisions Outdated until a new decision. Untrusted continuity
  data makes every assignment decision Outdated until an administrator re-baselines. Events are never modified.

## Attribution

v1 records `reviewer` (and `approver`) as given on Desktop and the signed-in username on a Server, plus `actor_identity`. The .NET port keeps the
Account Review rule: a decision needs an individual identity (Accounts-mode session or the Desktop reviewer profile); a shared access token is
refused (403), because it identifies no reviewer.

## .NET status

| Slice | Status | Evidence |
| --- | --- | --- |
| 1. Decision model: derive, lifecycle, states, coverage, effective decision | Done | `SodGovernanceTests`: Python v1 model of 90 users and 769 review items identical; the .NET analysis derives the same keys and versions |
| 2. Persistent store: events, revision, evidence snapshots, hash chain | Pending | |
| 3. Routes: decide, history, evidence; bulk; reappearance memory | Pending | |
