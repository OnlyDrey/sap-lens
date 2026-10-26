# SAP Account Review

Open **User Access → Account Review**. This is local investigation, not a SAP
administration connection. No account is disabled, no role is removed, and no
license savings or actual license entitlement is inferred.

## Sources and prerequisites

The existing User Access CSV supplies SAP identities, groups, account validity,
locks and user types. The optional Employee Directory supplies AD state through a
reliable exact email match. There is no additional CSV or direct SAP/AD connection.
User–Role Mapping must be enabled. Without Employee Directory, SAP-only findings
remain available; directory matching and AD status are explicitly unavailable.
An absent optional CSV never prevents Role Lookup or core application startup.

The review is per distinct SAP username, not assignment row or email. Shared SAP
email addresses, multiple/conflicting emails, duplicate directory emails and
missing emails never establish reliable AD-disabled evidence. Shared-email
ambiguity is now handled consistently in profile enrichment, coverage and review.
Manager navigation still requires exactly one matching SAP username and never
uses AD username or name-only inference.

## Account evidence and findings

Display terminology is consistent throughout the account views:

| Evidence | Presentation |
| --- | --- |
| All SAP source account intervals currently active | Valid |
| All intervals expired/future (none currently active) | Invalid |
| Missing/unknown or conflicting active/inactive intervals | Unknown |
| All source lock values true / false | Locked / Unlocked |
| Missing or conflicting lock values | Unknown |
| Reliably matched directory Enabled true / false | Enabled / Disabled |
| Missing, ambiguous, unavailable or unspecified AD state | Unknown |

The existing source interval calculation and raw API values remain unchanged.
Distinct account records remain inspectable in User Details. Account validity,
lock state, assignment validity and AD state are separate; none proves effective
SAP authorization. Friendly SAP user-type labels retain the technical code:
A Dialog, B System, C Communication, S Service, L Reference. Unknown codes remain
as imported.

Supported findings:

- Reliably AD-disabled, SAP-valid and unlocked: contextual profile warning and
  review finding. Unknown/ambiguous identities cannot produce it.
- Reliably AD-disabled and SAP-locked: separate investigation finding.
- Missing/ambiguous directory identity: only evaluated with a directory available.
- At least one expired SAP account interval: inspect conflicting source records.
- Technical/service/reference/communication accounts (B/C/S/L): separate review,
  not a claim that they are unnecessary.

Search, finding, license-group and decision filters compose. Sorting is stable by
selected field and SAP username; results are paginated. One in-memory review cache
reuses the current immutable source/directory snapshot across page and export reads.
Policy, annotations, source publication, directory and local evaluation-day changes
invalidate it; only one publication is retained. Export generation uses that same
local evaluation date, avoiding mixed-date results around midnight. User Details drill-down
retains the mounted review's filters, sort and pagination on Back. Review drill-down
does not invent Previous/Next positions from the independent User Directory order.

## Unlicensed group classification

Configure comma-separated group values under **Settings → Features → Unlicensed
SAP User Groups**, then **Apply settings**. The initial value is `UNLICENSED`.
Matching is trimmed, exact and case-insensitive, retaining the actual SAP group.
An empty list disables this classification. Built-in source mappings are unchanged.

This is an organization-specific classification, not a license entitlement check.
Include/exclude it independently of security findings. A valid/unlocked AD-disabled
account remains a security finding even if its group is classified as unlicensed.
Reliable licensing/contract data would be needed for future financial analysis.

## Local review annotations

For an account, select its decision button to open Review account. Inspect its
current findings and supporting SAP/AD evidence before entering a reviewer, rationale and
one of **Needs review**, **Investigating**, **Approved for deactivation**, or **No
action required**. This saves immediately through the explicit review action;
Settings' Apply button is unrelated. The reviewer is self-declared local metadata,
not an authenticated approval or an instruction to SAP.

Annotations are atomically written to `%LOCALAPPDATA%\SAP Lens\account-review.json`
(or the supported per-user configuration directory on other platforms). Keys are
hashed usernames; stored records contain decision, reviewer, rationale, timestamp
and an evidence fingerprint, not copied SAP rows. Review timestamps are stored and
exported in ISO UTC; the UI uses Norwegian dates and local 24-hour time. Reviewer/rationale can still
contain personal information and must be treated as private local data.

The fingerprint covers source identity/account/assignment evidence, reliable
directory evidence, group-classification configuration and derived validity/findings.
A changed fingerprint flags the previous annotation as stale, displays Needs review,
and requires fresh evidence before saving. An unrelated calendar day alone does
not stale a decision; a validity boundary changing the evidence does. No action or
annotation silently removes the underlying security finding.

Metrics describe the complete validated source, independent of table filters:
Accounts requiring review counts supported findings or stale decisions. Reviewed
accounts counts non-stale annotations other than Needs review. These counts can
overlap: annotating a finding does not establish that SAP has changed.

The file survives EXE replacement and application restart. It is intentionally not
part of portable settings/diagnostic exports. A corrupt or unreadable annotation
file is retained, and Account Review reports recovery instructions rather than
silently overwriting it. Other SAP investigation remains independent. Save failures
retain prior annotations. Storage is bounded to 20 MiB; large tables remain paginated.

## CSV export and privacy

**Export review CSV** exports the complete filtered/sorted result, including review
annotations. Export checks a generation covering SAP publication, directory,
classification policy, review annotations and evaluation date across all pages and
again before saving. Changed filters/evidence cancel export. Output is UTF-8/BOM,
spreadsheet-formula-safe, bounded to 32 MiB, and uses the existing authenticated
native CSV save dialog in desktop mode. Browser mode offers a local download.
CSV export contains identity data by design; diagnostic export remains redacted.

No source CSV, employee snapshot or review annotation is sent to GitHub, bundled
with the EXE or written into routine logs. All test records are synthetic.

See [Employee Directory persistence](../data/EMPLOYEE_DIRECTORY.md),
[Dashboard and loading](DASHBOARD.md), and [assignment date filters](FILTERS.md).

## Follow-up investigations

The **Outdated reviews** count and **Review changed evidence** action use the existing stale-evidence filter. CSV now includes both the current evidence fingerprint and the fingerprint retained with the original decision. A changed fingerprint does not rewrite reviewer metadata or rationale. [Saved Filters](SAVED_FILTERS.md) can retain a follow-up investigation, including finding, license-group classification, decision state and sorting. Bulk approvals and a mandatory reason taxonomy remain deferred; see the [gap analysis](../proposals/ACCESS_INSIGHTS.md#account-review-gap-analysis).

The compact summary gives each metric equal visual weight within its account,
finding or progress group. Search/finding/license/decision controls share the
first filter row; sorting and Descending stay together below. Clear filters is
right-aligned without stretching vertically. Export review CSV sits outside the
filter panel beside the result count; its complete filtered export semantics are
unchanged.

## Review history and source refresh

The modal shows current findings before the decision form, previous decision and
timestamp, and bounded pages of actual earlier decisions. Save is explicit; Cancel,
Escape and Close protect edited drafts. Findings remain after a decision until
source evidence changes; no SAP/AD records are modified.

Annotation storage format 2 reads existing format-1 files without rewriting them.
An explicit save retains the previous decision as a historical event and writes
atomically. No missing historical events are invented. Back up private application
storage before downgrading: older application versions may not read format 2.
Files are capped at 20 MiB, with at most 1000 retained events per account; a full or
unreadable store rejects replacement and preserves previous annotations.

New evidence fingerprints exclude CSV row order/IDs and unrelated directory fields.
Material identity, assignments, account validity/lock, AD status, matching and group
classification changes reassess currency. Legacy fingerprints remain supported for
unchanged evidence until the annotation is explicitly saved with the new schema.
A valid replacement that removes an account marks its retained annotation absent;
a reappearing username requires review even if its fields look unchanged. Missing
or disabled sources are not treated as confirmed account removals. Removed accounts
are not shown as active; their annotations/history remain in private storage.
Failure to update presence metadata is logged without private values and does not
erase annotations or block independent source loading.

Reviewed and pending filters use the full current SAP account population. Reviewed
means a non-stale decision other than Needs review; pending is its complement and
includes outdated decisions. This differs from the source-finding population.
