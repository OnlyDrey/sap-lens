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
| Decisions | `sod_decisions` | Private append-only events for activity, assignment, normal risk-review and independent formal-acceptance decisions, remediation actions and the report log. |
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

## Shared access-review coverage

`sod_governance.review_coverage` is a pure derivation over current evidence and
valid decision lifecycles. It does not write or reinterpret manual decisions.
Every relevant assignment needs a valid Keep/Remove decision to cover an activity
through roles. A risk's access assessment is covered by explicit risk review or
by coverage of all its relevant activities. Explicit risk review may cover those
activities, but this final propagation never feeds back into another risk.

The queue, subject panel, matrices and report status tables expose that same
coverage. Overall completion counts each role/activity/risk item once; formal
acceptance remains a separate explicit decision. Removal plans use the existing
what-if calculation, including overlapping providers. A plan never changes the
imported conflict or establishes verified remediation. Outdated evidence cannot
provide coverage. Period approval gates continue requiring explicit current
activity reviews and formal acceptance; access-review completion alone does not approve residual risk.

### Atomic queue assignment batches

The Work Queue calls the existing assignment selection endpoint and
`POST /api/sod/decisions/assignment/bulk` with `atomic=true`. Canonical scope filters
support explicit role matching modes independently of exact User Group selections.
The server revalidates each assignment, evidence generation/version, context and
revision. Atomic Keep/Remove batches (maximum 1000) perform one decision-index write
under the existing publication/period locks; validation failure writes no events.
The legacy Explorer's detailed partial-outcome behavior remains available by default.
Events carry `bulk_operation_id` and `previous_decision`, without changing identity,
source data, formal acceptance or remediation verification.

Period list and Overview progress use the same canonical assessment coverage as the
queue, including assignments. `blocking` remains the independent formal
activity/acceptance approval gate; reviewed coverage cannot bypass it. Frozen
assessment lifecycle is evaluated at the retained approval date, so later expiry
does not rewrite an approved period's completion counts.


## Configuration names and relationship navigation

Effective catalogue Display names share `sod_metadata.lookup` precedence; local fields
remain raw overrides. Exact-ID GET endpoints resolve details without fuzzy search or page
limits. Activity rows distinguish active related risks from retained history. The frontend
collects the originating filtered/sorted list in bounded pages, checking revision and source
identity before providing Previous/Next. Cross-entity navigation keeps a bounded history
and guards unsaved drafts; it never modifies mappings or evaluation policies.

Relationships are UI context, not descriptions: `frozen` excludes `activities`/`risk_ids`
from report metadata copies. Existing immutable snapshot contracts therefore remain intact.

## Measured request-local review state reuse

Normalized source snapshots and derived user/evidence indexes already have generation-keyed
reuse. Review decisions are a private, validated JSON store, not SQLite: no SQL index or
query-plan change applies. Profiling found repeated parsing of that store within one response.
`sod_scope` now captures it once per fresh request bundle and shares it between decision
state, remediation actions and response revision. Nothing is retained across requests.
A response therefore reports the revision belonging to its decision rows, even if another
request commits meanwhile. Live write/preview revision guards remain uncached and atomic.

Source publication/configuration continues to change the existing analysis generation;
failed refresh retains the previous valid source. A new request reads committed review
changes immediately. Approved/closed periods still use immutable decisions/actions and
approval-date lifecycle from their snapshot, independently of the live decision store.
No second prepared-data cache, database, frontend state store or dependency was introduced.
The existing shared subject query supplies all three review tabs; its save invalidation
remains responsible for refreshing affected progress/KPIs.

### Comparable synthetic measurements

Linux/Python 3.12, 200 synthetic users, 800 assignments, two risks, nine warm samples per
endpoint through in-process ASGI. The profiler imports real CSVs and seeds real decisions
in disposable isolated storage. Warm/cold JSON responses must agree. Values below are
before → after in milliseconds; p95 is the observed high sample, not a production SLA.

| API view | p50 ms | p95 ms | Decision-store reads |
| --- | --- | --- | --- |
| overview | 66.2 → 51.0 | 168.1 → 137.1 | 2 → 1 |
| risk matrix | 49.0 → 31.2 | 62.9 → 42.0 | 2 → 1 |
| activity matrix | 54.1 → 34.7 | 62.7 → 77.8 | 2 → 1 |
| role assignment review | 44.0 → 22.3 | 82.7 → 31.7 | 2 → 1 |
| activity review | 54.0 → 20.4 | 174.9 → 31.3 | 2 → 1 |
| risk review | 45.4 → 24.4 | 80.7 → 41.4 | 2 → 1 |
| remediation | 82.5 → 35.2 | 260.1 → 60.0 | 3 → 1 |
| filtered page | 115.9 → 70.2 | 236.5 → 138.8 | 3 → 2 |

Both runs had 100% warm source-analysis/prepared-index hits and unchanged payload sizes.
Traced Python per-request peaks were approximately 64–68 MiB before and 64–67 MiB after;
this is allocated Python memory, not process RSS. Activity-matrix p95 increased despite a
lower median; small-sample tail timings are noisy. Filtered Explorer still reads twice
because its independent selection path resolves a second bundle; no cross-bundle cache
was added. Single assignment-save API median/p95 changed from 39.7/109.7 to 29.6/34.1 ms
(one measured POST, revision lookup outside the timer). Browser click/render latency and
production concurrency were not measured. This does not claim faster atomic disk writes.

The profiler records import timing, payload size, cold derived-cache latency and a
client-thread cProfile summary (not backend-thread CPU attribution). JSON history remains
bounded and reparsed once per request; larger real histories may still need investigation.
Run the isolated utility as described in [Testing](../development/TESTING.md#synthetic-sod-performance-profile).

## Effective access decisions (approved model revision)

`sod_governance.effective_decision` is the canonical pure four-status projection:
Approved (green), Remove (red), Investigate (amber), Pending (neutral). It never writes
synthetic events. Explicit current activity decisions take precedence over role-derived
results; disagreements and both results remain available in metadata. Conditional
activity events remain unchanged and map to Approved with their recorded conditions shown
as supporting metadata; the compatibility form option still requires those conditions.

For an activity without an explicit current decision, any current supplying Keep derives
Approved; otherwise all current suppliers Remove derives Remove; otherwise any Investigate
derives Investigate; otherwise Pending. No suppliers does not imply Remove. The full role
distribution is retained. Stale approvals derive nothing; retained Remove can remain visible
with stale-evidence guidance without counting as current review coverage.

Normal risk reviews use a separate `risk` kind in the existing append-only decision store,
with Approved/Remove/Investigate/Pending and the same finding identity, evidence guards,
review period, reviewer and justification. Old stores/snapshots remain readable without
rewriting them. Formal `acceptance` events and approval gates remain independent. A normal
risk decision does not alter role decisions, conflict detection or formal acceptance.
Normal Approved/Remove can contribute risk-review coverage, but never formal acceptance or
activity coverage. Source-derived indexes remain shared; all decision projections use the
request-local validated decision snapshot, so the next request sees committed changes.
The subject API exposes `risk_review_summary`, `risk_review` and `risk_review_event` beside
the existing formal fields; the UI migration uses those separate fields. Historical report
snapshots are not rewritten.

### Confirmed assignment feedback and write profiling

`profile-sod.py` now measures single and atomic bulk writes separately, including
JSON-store reads, serialization/atomic-write time and derived-state time. This
runtime uses private JSON stores, so SQL query count is zero. No global decision
cache or weaker persistence path was introduced.

On a successful assignment write the API returns the just-committed row's canonical
lifecycle, event, primary summary and coverage. The frontend patches only that
matching source generation/revision and row. It does not show a permanent choice
before persistence. Background subject/counter reads reconcile derived activities
and risks; those reads no longer keep the clicked action spinning. Errors leave
the confirmed state unchanged, and concurrent/stale decisions retain existing guards.

Synthetic local measurements (100 users, 400 assignments, 20 samples; not production
benchmarks): single-write p50/p95 was 21.43/32.15 ms before and 18.72/33.56 ms after;
100-assignment bulk was 172.70/285.53 ms before and 217.79/314.49 ms after. The bulk
write path was unchanged; timings vary and no backend speedup is claimed. Single
JSON writes used one decision-store read, bulk two; atomic validation/history were
retained. Browser DOM confirmation after request release improved from one sample
of 67.9 ms to 43.0 ms. A blocked-subject-read regression verifies confirmed row
feedback does not depend on that read finishing. These figures do not establish
Windows or production-dataset latency guarantees.
