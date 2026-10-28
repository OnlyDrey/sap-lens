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
| Overview | Compact figure tiles for conflicts, reviews and remediation that link into filtered views, review period progress and last approval, evidence freshness and source coverage. |
| Risk Matrix | SAP users by risk. Cells show the risk-acceptance state; totals count distinct users and user-risk findings. Group rows by SAP user group. |
| Activity Matrix | SAP users by activity with review state and the number of supplying roles (overlap flagged). The main entry point for reviewing. |
| Access Explorer | Four modes: **Users** (grouped by risk or by activity), **Assignments**, **Roles** (role lookup with the users assigned to each role) and **Role conflicts** (catalogue roles). Identifiers are pills, evidence (roles, transactions, assigned users) expands per row, and CSV export covers the filtered rows. Trace user, risk, activity, transaction, role and assignment in both directions. |
| Reviews | Work queue with one row per SAP user and a unified review workspace (Activity Review, Role Assignment Review, Risk Acceptance), and Remediation tracking. |
| Review Periods | Frozen snapshots, workflow, a per-row action menu, comparison in a dialog and audited deletion. |
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
and freezes the snapshot with its decisions. Reports: PDF and DOCX formal review (executive summary, scope, sources,
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

## Deleting review periods

Every period status can be deleted from the row action menu or the period dialog. The delete dialog previews what is affected
(decisions, actions, reports, comparison baselines, snapshots) and always needs the exact period name and who is deleting.

- An empty draft is erased together with its captured snapshot. A deletion record remains.
- Anything else is tombstoned: hidden from active work, matrices, comparisons and report generation, while its snapshot, approval record,
  decisions, actions and report log stay on disk. It appears under "Show archived periods". Archiving needs an impact confirmation.
- Approved or closed periods, periods with issued reports, and periods used as a report baseline need a second history confirmation.
  Approved or closed periods also need a reason. The reason, actor and previous state are stored in the deletion record and the period history.
- Reports already issued outside SAP Lens stay valid; their log entries remain, but they cannot be regenerated afterwards. Findings first seen in a deleted
  approved period are classified as new instead of reopened in later comparisons. Other periods and current decisions are never changed (no cascade).

## Matrix cells and scope

- Cells show one status pill and one short count: for the Risk Matrix the acceptance status and reviewed/total activities, for the Activity Matrix the review status and ×roles supplying the activity (⧉ marks overlapping coverage). Full wording stays in each cell's accessible name. Criticality and type are in the column tooltip and the investigation, not in the grid.
- Column headers show the risk or activity pill, tinted with the color configured in Settings → SoD Risk Configuration. Row and column headers stay sticky.
- The Activity Matrix lists activities that contribute to at least one potential conflict (both sides of an enabled, supported risk are required). Other activities a role supplies are considered in Role Assignment Review, which shows the additional activities. Unavailable evidence is never shown as "no conflict".
- Page, row grouping, scroll position and filters survive opening a role or user page and returning with Back, within the session.

## Review workspace

- **Reviews → Work queue** lists one row per SAP user with overall progress and separate progress for activity review, role assignment review and risk acceptance. Filter by Needs review, Complete or Removal recommended. The queue CSV still exports every review item with its decision (`GET /api/sod/queue/users` feeds the table).
- **Open Review** (also from a matrix cell or Explorer row) opens one panel with three independent sections: **Activity Review**, **Role Assignment Review** and **Risk Acceptance**. Each row has its own decision button; tick several rows of one section and use **Review selected** for a batch with a single justification. Decision history opens on demand per item. The panel footer shows overall progress.
- Supporting evidence (transactions, supplying roles, removal impact, what-if simulation) sits in a collapsible section, open when the panel was opened from a specific risk or activity. Names stay self-reported, every decision keeps its evidence version, and no decision changes detection or SAP.

## Reports, branding and export notices

- **Report branding** (Settings → Organization & SAP System): an optional report-only logo. PNG or JPEG, up to 1 MB and 32 to 4096 pixels per side; SVG and WebP are rejected. Images are decoded, resized to at most 1024 px, stripped of metadata and stored privately with other branding assets (not in configuration packages or release artifacts). It is saved immediately, can be replaced or removed, and is used in PDF and DOCX reports (`GET/PUT/DELETE /api/sod/reports/branding`). Without it, reports use the application logo when one is set. The logo is not review evidence and is not part of a frozen period snapshot.
- **Formal report**: the executive summary and outstanding remediation sections keep the states apart. Review status separates *not reviewed*, *reviewed, no action required*, *reviewed, removal recommended* and *reviewed, risk rejected*. Removal follow-up separates *removal recommended*, *action completed (manually recorded, not proof of removal)* and *removal verified in later source evidence*.
- **Access remediation report** (CSV, DOCX, PDF): also lists role assignments *awaiting review* and adds the status tables, so it is useful before any decision or action exists, with an explicit note that no actions are recorded. Nothing in it claims that access was removed.
- The report forms show the essentials (period or context, title, status, handling groups) and keep people, roles, language, version, date and comments under "Document details".
- **Export notice**: every export reports through one notice fixed at the top of the application. It overlays the page, so nothing shifts. Success and cancel messages fade after a few seconds; errors stay until dismissed.
