# Authorization Risk Analysis — future concept

Status: specification only. No implementation, navigation entry, inactive controls or risk scores.

## Purpose and evidence boundary

A future capability could investigate risky SAP access combinations against reviewed rules. Current SAP Lens data establishes imported role assignments, assignment/account intervals, lock observations, catalogue relationships and mapped T-codes. Exact directory matching enriches identity and AD status; it does not verify SAP authorization.

These are different claims:

1. Role assignment: observed in a dated local export.
2. T-code mapping: derived catalogue coverage through a confidently matched role.
3. Effective authorization: requires evaluated authorization objects, field values, organizational scope, generated profiles and relevant SAP security configuration.
4. SoD conflict: requires a reviewed ruleset, rule scope and qualifying evidence; a transaction pair alone is insufficient.
5. Confirmed security risk: requires contextual validation, actual effective access, compensating controls and accountable review.

Current data cannot establish recent use, execution ability, license entitlement or monetary savings. Valid/unlocked accounts and large role counts are not risk scores.

## Additional evidence required

Evaluate authorized local exports of authorization objects and fields, effective user profiles, organizational values, validity and generation state, SAP configuration affecting checks, security-rule versions, business process scope and compensating controls. Usage history and licensing/contract evidence are independent optional sources; neither should be inferred from assignments. Define source freshness, provenance, sizes, permissions and stable identities before import development.

## Possible workflow

A reviewed versioned rule evaluates supported evidence at user and role level. Findings link every rule condition to source records, include organizational scope and source versions, and explicitly mark incomplete evidence. Analysts inspect false positives and conflicting source observations. Review/exception decisions retain reviewer, timestamp, rationale, rule version, evidence fingerprint, expiry and compensating-control references. Changed evidence reopens review rather than silently retaining an approval. Existing Account Review storage patterns may be reused, but account-lifecycle decisions are not authorization-risk approvals.

Rules must be deterministic, explainable, tested against synthetic positive/negative/ambiguous cases, and reviewed by SAP security specialists. No automatic account/role changes. No hidden cloud processing or personal data in diagnostic exports.

## Implementation prerequisites

Proceed only after a specific administrator workflow is validated, reliable effective-access exports are available, rule ownership and exceptions are defined, inference limitations are agreed, source/privacy controls are designed, and false-positive behavior is tested. Confirm how source refresh and rule changes invalidate results. Do not implement solely because role/T-code coverage already exists.
