# Access Insights feasibility and evidence inventory

## Decision

**Option D for a centralized Access Insights capability: no separate implementation.** Keep Dashboard and Account Review, and deliver the independently requested Data Health overview within Data Sources. Do not add an Access Insights page, risk score, new primary navigation or parallel review system. Existing Account Review already consolidates actionable account findings. Data Health belongs under Settings → Data Sources; two-user differences belong under User Access.

This assessment uses the actual `cache._CacheState`, `user_access.build_users`, `employee_directory.Directory`, `account_review` and existing routers. Role Comparison remains the existing two-to-five-role structural/T-code analysis and has not been rebuilt.

## Dataset evidence matrix

| Dataset | Fields, types and identity | Relationships and omissions | Publication / persistence |
| --- | --- | --- | --- |
| SAP users | Case-normalized username key, original username string; lists of name pairs, emails, groups and account observations | Username is required; one username may have conflicting names/emails/accounts. Email/name never merge users. No last logon, usage, contractual license or HR termination record | Validated User Access CSV; atomically published memory snapshot. Configured source reloads at startup; no durable SAP dataset copy |
| Account observations | ISO date-only valid_from/to or null; locked boolean/null; raw user_type and user_group | Validity, lock and user type are independent. Multiple observations retained. Unknown lock is never Unlocked | Same generation as SAP users; validity re-evaluated by local date |
| Assignments | Original exact role_name, username/key, group, scope, date bounds/null, source account evidence, match_status, catalogue_roles, T-code list | Distinct intervals/groups retained; exact duplicate rows deduplicated with import totals. Only ZC/ZO are primary investigation scope. Missing dates do not establish active access | Rebuilt against the same catalogue generation; failed refresh keeps previous publication |
| Role catalogue | AGR_NAME, optional TEXT, FUNCTION_KEY/module_name, alternate descriptions; child/effective/direct relationships; TCODE/TTEXT | Roles may be wildcard patterns. Most-specific unambiguous match required. CSV area evidence is authoritative; no arbitrary name inference | Validated catalogue CSV; atomic publication. Saved module preferences are separate local configuration |
| T-code mappings | Distinct role/code associations via single_roles, relationship provenance | Coverage evidence, not authorization objects, field values, effective authorization or usage. Missing mappings do not mean no access | Same catalogue generation |
| Employee Directory | Sixteen documented UTF-8 semicolon fields: Site, Name, SamAccountName, UserPrincipalName, Mail, Department, Title, Enabled, DistinguishedName, ManagerDN/Name/SamAccountName/Mail/Department/Title/LookupStatus | Exact normalized email enrichment. Duplicate directory/SAP email ownership is ambiguous. AD and SAP status remain separate. Manager email resolves SAP username only when unique | Explicit confirmed import creates private durable snapshot; legacy in-memory data has explicit snapshot recovery. Feature preference independent of retained data |
| Release roles | ZO assignment + parsed PR/PO, group, strategy; opaque scope/suffix | Confirmed MM PR/PO_REL_ST structure only; malformed names remain Unparsed. No independent release policy/strategy reference source, thresholds or authority semantics | Derived from User Access assignments; no third CSV |
| Review annotations | Hashed username key; state, reviewer, rationale, UTC timestamp, evidence fingerprint | Reviewer is self-declared. Changed identity/account/directory/policy evidence makes a decision stale; no SAP write capability | Private atomic account-review.json; restart-safe; not portable configuration/diagnostics |
| Saved filters | ID, name, view, filter_schema, scalar/list configuration, created/modified UTC timestamps | No result rows, selected comparison identities or transient UI state. Filters re-run against current datasets | Private atomic saved-filters.json; bounded; unsupported definitions retained |

Role CSV optional schema mappings and User Access's twelve-field schema are documented in [Access investigation](ACCESS_INVESTIGATION.md). Directory fields and snapshot recovery are documented in [Employee Directory](EMPLOYEE_DIRECTORY.md). Names/emails and source paths are never included in this document's examples.

## Candidate findings and value

| Detection / exact evidence | Value and action | Existing overlap / navigation | False positives / refresh | Outcome |
| --- | --- | --- | --- | --- |
| AD Disabled + all SAP validity observations Valid + Unlocked; unique normalized email | Investigate account lifecycle mismatch; User Details | Account Review + contextual profile warning | Source timestamps can differ; never proves risk/usage. Review fingerprint changes with evidence | Already covered |
| Missing or ambiguous identity; SAP email owners + directory Mail index | Investigate enrichment reliability; User Details/directory source | Account Review, Dashboard coverage | Legitimate service/shared accounts; unavailable directory is not a missing-match finding | Already covered |
| Multiple names/emails/account observations per SAP key | Inspect source observations before deciding conflict | Data Health → existing User Details | Multiple accounts/groups/intervals can be legitimate; information only | Valuable, implemented |
| Duplicate directory email/DN/SamAccountName and unresolved managers | Repair enrichment source, inspect source quality | Existing Employee Directory source details/diagnostics | Shared identifiers and external managers can be legitimate | Already covered; no duplicate evaluator |
| Expired / future assignment dates | Review lifecycle records, not security findings | Dashboard lifecycle + Data Health → User Details | Historical/scheduled records expected; re-evaluated daily | Valuable informational drilldown |
| Missing assignment date bounds | Explain unknown evidence | Data Health → User Details | Open/missing source fields; SAP maximum date is explicit, not missing | Valuable warning |
| Assigned ZC/ZO role cannot resolve exact/wildcard catalogue match | Repair catalogue coverage, inspect assignment | Data Health → user; comparison marks unmapped | Export may intentionally omit releases/roles | Valuable warning |
| Ambiguous catalogue patterns | Resolve equally specific duplicate patterns | Data Health → user | No arbitrary winner or transaction inference | Valuable warning |
| Invalid/reversed dates, missing usernames/header | Prevent invalid publication | Existing importer atomic failure + diagnostics | Raw rejected rows unavailable in published cache | Already covered; do not fabricate counts |
| Identical raw rows | Explain deduplication, not duplicate role definitions | Existing import report totals surfaced in Data Health | Repeated catalogue rows commonly represent different T-code relationships | Valuable information; no blanket duplicate-role finding |
| Missing description/module or no T-codes | Understand catalogue completeness, open role | Data Health → Role Details | Optional fields and partial extracts are legitimate | Valuable information |
| High transaction/role counts | Descriptive investigation only | Existing role lookup/comparison | Large roles can be legitimate; no calibrated threshold | Low value as a finding; deferred |
| Unknown SAP user type | Explain unsupported account classification | Data Health → User Details, raw type preserved | Customer-specific source values; not automatically invalid | Valuable warning |
| Unparsed ZO role | Investigate unsupported naming | Data Health → user, existing Release Roles retains record | Naming can differ; no authority assumption | Valuable information |
| Release group/strategy inconsistencies or missing policy references | Cannot verify against an independent definition | No policy source exists | Role-name parsing alone cannot prove inconsistency | Requires more data |
| Effective access, SoD conflict, recent usage, license savings | Not established by imported data | No speculative UI | Requires authorization/security/usage/contract evidence | Unsupported |

All Data Health counts use the current validated publication. Cached source calculations invalidate on publication identity and date. Directory coverage reuses the existing exact-match implementation. Drilldown is paginated and uses existing record routes. Missing/disabled sources produce Unavailable rather than zero-quality claims. Saved review decisions carry independent evidence freshness.

## Concrete synthetic comparison

DEMO_A and DEMO_B both hold ZC:SHARED:ENP. The catalogue pattern ZC:SHARED:* maps to FB03. DEMO_A additionally holds ZC:ONLY_A mapping ME23N and FB03. With currently valid assignments selected: one shared role, one role only A; FB03 shared, ME23N only A. Both explanatory roles remain visible for A's FB03. Two distinct start-date intervals for ZC:SHARED:ENP remain two evidence records. An expired ZC:OLD is excluded by default and appears only in the appropriate validity view. None of these facts proves executable authorization.

## Account Review gap analysis

Already present before this iteration: persistent individual decisions, states, reviewer/timestamp/rationale, stale fingerprints, filters including stale, sorting, complete paginated CSV export, unlicensed-group policy, user navigation and privacy guards.

Targeted changes: visible outdated-review count/action, clearer stale option label, original reviewed fingerprint alongside current fingerprint in export, and shared saved investigations. Bulk approvals are deferred: they require explicit per-account evidence confirmation and conflict-aware atomic updates, and would add material review-error risk. Standard reason categories are deferred until administrators establish a useful taxonomy; free-text rationale already exists. No duplicate review workflow was added.

## Future gates

Add a dedicated Insights surface only after several distinct actionable findings require a common queue and administrators validate the workflow. Add policy/usage/security sources only with explicit schemas, privacy review and observed versus derived evidence labels. See [Authorization risk concept](AUTHORIZATION_RISK_ANALYSIS_CONCEPT.md).
