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

## Storage (.NET)

- `SodDecisionEvents`: one row per event, the v1 event as canonical JSON, append-only (SQLite triggers) and hash-chained in insertion order
  (`SHA-256(previous hash + "\n" + event JSON)`); `SodDecisionStore.VerifyChainAsync` reports the first broken link.
- `SodEvidenceSnapshots`: content-addressed evidence (SHA-256 of the canonical JSON of `{version, source, kind, evidence}`, the same address v1
  gives its private snapshot), verified on every read.
- The store revision is the `sod-decisions` row of `SodDocuments`. Every call runs in one SQLite write transaction: revision check, per-item
  validation, history cap, capacity, events, evidence and the new revision commit together or not at all.
- v1 additions not adopted: none. Addition over v1: the hash chain and database-enforced immutability (v1 keeps a JSON file).
- Messages: where v1 raises its own text (revision, items, expiry, context, capacity, evidence) .NET returns the same text; pydantic validation
  failures are 422 in both, with .NET's own wording.

## Remediation actions and bulk review (.NET)

- Actions live in the `sod-remediation-actions` SoD document and share the decision store revision: every create or update needs the current
  revision and increases it, in one transaction with the action. Each change appends a history entry with v1's change note
  (`field: old → new`, "-" for empty); completing requires completion evidence; the actor is the attributed individual (Desktop profile or
  account), as v1 `actor()`.
- Bulk review follows v1 exactly, including its partial-success shape: items are checked one by one (not located, changed evidence → failed;
  already under investigation, or a current Keep/Removal required without `replace_existing` → skipped); non-atomic runs commit chunks of 100,
  a failing chunk is reported as failed (never skipped) while earlier chunks stay recorded; a stale revision on the first chunk refuses the call
  (409). Atomic runs refuse everything (409, nothing saved) when any item is skipped or failed. With `track_action`, an Investigate run tracks one
  open "Investigate assignment" action per assignment, never a duplicate.
- v1 behavior kept as is: when an action fails after its chunk's decisions committed (`track_action`), v1 reports the chunk as failed although its
  decisions are recorded; .NET does the same.

## Reappearance memory (.NET)

- `AssignmentLifecycle` (Application) is the port of `assignment_lifecycle.py`: per decided assignment key the state (present/absent), when it
  became absent, when it reappeared and why (reappeared, identity) and hashed identity evidence (unshared e-mail, full names). It is the
  `assignment-lifecycle` SoD document, sealed with a SHA-256 digest; the newest written revision is kept separately (`assignment-lifecycle-meta`)
  so a missing or older document is detected (fail-safe: every assignment decision reads Outdated with the "unavailable" reason).
- `ObserveAsync` runs after every committed import (job worker, held-import confirmation; best effort, like v1) and before review reads. It is
  idempotent per users+catalogue content hash (v1 uses the same snapshot identities). Absence is recorded only when verifiable: the user is fully
  mapped and the catalogue has no invalid patterns, or the user is gone. Failed, held or unconfirmed imports never change the active data, so
  they change nothing here.
- `RebaselineAsync` (administrator acknowledgement) keeps the previous document aside. Its route (`/api/storage/lifecycle/rebaseline`) and the
  Data Health findings (`lifecycle_integrity`, `reappeared_assignments`) are not migrated yet.

## Attribution

v1 records `reviewer` (and `approver`) as given on Desktop and the signed-in username on a Server, plus `actor_identity`. The .NET port keeps the
Account Review rule: a decision needs an individual identity (Accounts-mode session or the Desktop reviewer profile); a shared access token is
refused (403), because it identifies no reviewer.

## .NET status

| Slice | Status | Evidence |
| --- | --- | --- |
| 1. Decision model: derive, lifecycle, states, coverage, effective decision | Done | `SodGovernanceTests`: Python v1 model of 90 users and 769 review items identical; the .NET analysis derives the same keys and versions |
| 2. Persistent store: events, revision, evidence snapshots, hash chain | Done (no routes yet) | `SodDecisionStoreTests`: a 20-call v1 sequence (successes, stale revision, every validator, limits, expiry, control characters, contexts, bulk tag) gives the same status, revision, previous decisions and evidence addresses; histories and evidence equal v1 after a restart; concurrent writers commit once; a failing item writes nothing; triggers refuse edits; tampering breaks the chain |
| 3a. Decision targets: review model (every imported assignment), assignment and activity evidence, item location | Done | `SodGovernanceTests`: 83 v1 items of all four kinds located with the same key and evidence version; assignment and activity evidence have v1's content address; the review population (234 users) equals v1 |
| 3b. Routes: `POST /api/sod/decisions/{kind}`, `GET .../history` (removal verification), `GET .../evidence`, live context | Done | `SodDecisionRoutesTests`: decisions of all four kinds store evidence with v1's content address; Desktop attribution as v1 `actor()`; history newest first with previous decisions after a restart; removal verification; stale generation, revision, evidence and items, every validator, periods (501) refused with nothing written; shared token refused (403). Permission map equals v1 `session_boundary` |
| 3c. Reappearance memory (`assignment_lifecycle`) and `GET /api/sod/subject` | Done | `SodLifecycleTests`: v1's multi-import sequence (review, removal, reappearance, new review, second cycle, identity change, validity change) gives the same subject overview (assignment, activity and risk lifecycle, derived status, coverage) at every step; a restart, a failed import and a held import change nothing; history and evidence stay complete; a tampered memory makes every assignment decision Outdated (reason "unavailable") until re-baseline. Mutation check: without the memory the sequence test fails |
| 3d. Remediation actions (`POST /api/sod/remediation/actions`) and bulk assignment review (`POST /api/sod/decisions/assignment/bulk`) | Done | `SodBulkReviewTests`: a 17-call v1 sequence (mixed recorded/skipped/failed, protected decisions, replace, investigation with tracked actions and no duplicates, atomic refusal and replacement, stale revision and generation, validation, action create/update/complete, unknown action, foreign user, stale revision) gives v1's outcome for every call; after a restart the histories, bulk tags, actions, revision and chain equal v1; a shared token is refused |
| 3e. Review subjects, simulate, legacy risk decisions, lifecycle re-baseline route and Data Health findings, v1 data migration | Pending | |
