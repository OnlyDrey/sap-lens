# Segregation of Duties (SoD)

SoD turns an externally supplied risk matrix into **potential conflict evidence** and a
documented review trail. It supports investigation: a transaction mapping does not prove
effective SAP authorization, a confirmed violation or license use. Methodology, schema and
limits: [SoD matrix reference](../data/SOD_MATRIX.md). Internals:
[SoD architecture](../architecture/SOD.md).

**Analyze → Investigate → Review activities → Review role assignments → Calculate risks →
Accept or reject → Approve → Remediate → Verify → Report**

## Views

| View | Purpose |
| --- | --- |
| Overview | Conflicts, review progress, accepted/rejected risks, remediation, open periods, changes since the last refresh and source coverage. Figures link into the matrices. |
| Risk Matrix | SAP users by risk. Cells show the risk-acceptance state; totals count distinct users and user-risk findings. Group rows by SAP user group. |
| Activity Matrix | SAP users by activity with review state and the number of supplying roles (overlap flagged). The main entry point for reviewing. |
| Access Explorer | User risk, user activity, access list, role lookup and role conflicts, with CSV export. Trace user, risk, activity, transaction, role and assignment in both directions. |
| Reviews | Work queue with status filters and batch review of selected rows, and Remediation tracking. |
| Review Periods | Frozen snapshots, workflow, comparison and deletion. |
| Reports | Formal review report and access remediation report. |

Business matrices (for example Finance or P2P) are **Saved Filters** on the two matrices,
not separate pages. The risk catalogue stays in Settings → SoD Risk Configuration.
Choose **Review context**: current evidence, or a review period (frozen after approval).

## Three separate decisions

1. **Activity review** (user + activity): Approved, Conditional (conditions required),
   Remove or Pending. Reviewed once per user across all risks the activity contributes to.
2. **Role assignment review** (the actual assignment): Keep, Remove or Pending. An approved
   activity does not mean every role supplying it is needed. The panel shows all
   contributing roles, duplicate coverage, other activities each role supplies, the risks it
   contributes to and the effect of removing it.
3. **Risk acceptance** (user + risk): Accepted, Rejected or Pending, with a named approver
   who differs from the reviewer, optional compensating controls and an optional expiry.

Decisions never change what is detected: an approved activity can still produce an active
risk, and an accepted risk stays visible. Evidence that changes materially marks a
decision **Outdated** for reassessment; history is kept. Select a matrix cell or queue row
to open the investigation panel with evidence, decisions, history, what-if removal and
remediation. Batch review applies one decision only to the rows you select.

## Remediation

Removal and investigation recommendations become tracked actions (owner, due date, status,
completion evidence). A completed action is a manual statement; only later source evidence,
with complete coverage, shows that access is gone. What-if analysis recalculates conflicts
on a copy of the evidence and never changes SAP or imported data. Several valid options
are shown rather than one recommendation.

## Periods and reports

Create a period (name, range, evaluation date) to freeze evidence, then
`Draft → In review → Ready for approval → Approved → Closed` (or `Rejected` with a reason).
Approval needs every activity and risk decision current, a different reviewer and approver,
and freezes the snapshot with its decisions. Deleting needs the exact period name: empty
drafts are removed, other open periods are archived, approved or report-referenced periods
are protected. Reports: PDF and DOCX formal review (executive summary, scope, sources,
risk overview, activity, assignment and acceptance results, controls, remediation, changes,
conclusion and signature lines, technical appendix) and an access remediation report with
CSV, DOCX and PDF. Generating a report never approves a review, and names and signature
lines are not verified digital signatures.

## Evidence rules

- Missing sources or coverage appear as unavailable or "Not observed", never as resolved or zero.
- Source criticality labels (for example C/H) are shown literally.
- Private backups must include the SoD stores. Portable configuration and diagnostics
  exports exclude them. Use only synthetic data in examples and tests.

Source import: [Data & CSV](../data/IMPORT_AND_REFRESH.md), synthetic example
[sod-matrix.example.csv](../../examples/sod-matrix.example.csv). API: [SoD API](../architecture/API.md#sod-api).
Validation and open native acceptance items: [SoD validation](../archive/validation/SOD_VALIDATION.md)
and [SoD 2.0 validation](../archive/validation/SOD2_VALIDATION.md).

## SoD Risk Configuration (Settings)

Settings → SoD Risk Configuration has two tabs, **Risks** and **Activities**, with compact tables and no copy buttons or code styling.

- Editable, English only: display name, business area, explanation, consequence, mitigating controls, review guidance, notes, and a per-ID color from a fixed named palette. Risks also keep the enabled flag and description review status. Earlier Norwegian text is retained in storage untouched but no longer shown or edited.
- Immutable (always from the import): risk and activity identifiers, risk/activity relationships, transaction mappings, criticality and type. Edit requests that include them are rejected.
- Overrides are keyed by risk ID and activity name in `sod-catalogue.json` (`activities` is optional, so earlier files still load). Imports never touch them, and they never affect conflict detection.
- Pills show the identifier text; the color only tints the pill. `GET /api/sod/appearance` supplies names and colors to the other SoD views. Activity endpoints: `GET /api/sod/catalogue-activities`, `POST /api/sod/catalogue-activities/{activity}` (optimistic `expected_revision`).
- Edit dialogs have a header close button and only Cancel and Save changes in the footer.

## SoD feature toggle (Settings → Features)

- Segregation of Duties has its own card in Settings → Features: a manual toggle, imported-data availability, an operational status and a **Configure SoD** link to the SoD Matrix source.
- It is never enabled automatically: importing or selecting a SoD matrix leaves it off. Installations that already had a SoD source when this setting was introduced are migrated as enabled, so existing behavior is unchanged; an explicit saved value always wins.
- Status: Operational (enabled, matrix loaded, User–Role Mapping enabled and user data present), Disabled in saved settings, Requires User–Role Mapping, Data required.
- While disabled the SoD entry is hidden from the main navigation (direct visits show a short notice), analysis reports coverage reason `sod_disabled`, and dynamic SoD refreshes are skipped. Matrices, risk and activity configuration, review decisions, periods and reports are retained untouched and return when it is re-enabled, without re-importing.
