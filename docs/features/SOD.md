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
| Overview | Dashboard-style sections with metric tiles for conflicts, reviews and remediation that link into filtered views, a SAP user group heatmap, review period progress and last approval, evidence freshness and source coverage. |
| Risk Matrix | SAP users by risk. Cells show the risk-acceptance state; totals count distinct users and user-risk findings. Group rows by SAP user group. |
| Activity Matrix | SAP users by activity with review state and the number of supplying roles (overlap flagged). The main entry point for reviewing. |
| Access Explorer | Four modes: **Users** (grouped by risk or by activity), **Assignments**, **Roles** (role lookup with the users assigned to each role) and **Role conflicts** (catalogue roles). Identifiers are pills, evidence (roles, transactions, assigned users) expands per row, and CSV export covers the filtered rows. Trace user, risk, activity, transaction, role and assignment in both directions. |
| Reviews | Work queue with one row per SAP user and a unified review workspace (Activity Review, Role Assignment Review, Risk Acceptance), and Remediation tracking. |
| Review Periods | Frozen snapshots, workflow, a per-row action menu, comparison in a dialog and audited deletion. |
| Reports | Formal review report and access remediation report. |

Business matrices (for example Finance or P2P) are **Saved Filters** on the two matrices,
not separate pages. The risk catalogue stays in Settings → SoD Risk Configuration.
One **review context bar** sits beneath the SoD navigation on every page: choose current evidence or a review period (frozen after approval) and see the evaluation date and whether the evidence is live or a frozen snapshot. Pages do not repeat this information.

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

- Segregation of Duties has its own card in Settings → Features: a manual toggle (**Enabled**, aligned to the right edge of the card), imported-data availability, an operational status and a **Configure source** button to the SoD Matrix source.
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

## SAP user group heatmap

The Overview heatmap shows distinct users per SAP user group and risk (or activity) over current evidence. Darker cells have more users; the Users column and the Distinct users row are distinct counts. A user in several groups counts in each group, so group counts can exceed the distinct total. The 25 most affected columns are shown; the matrix lists all of them. Sort by group, distinct users or number of risks/activities, select a cell to open the matrix for that group and item, and use Export CSV (long format: group, item, users with the item, users in the group with items). When SoD is enabled the [Dashboard](DASHBOARD.md) also summarizes conflicts, pending reviews and remediation.

## Filters, tiles and drawer

- Every SoD page (matrices, Access Explorer, Role Conflicts, User Conflicts) uses the same **Filters** sidebar: search, Saved Filters and all filters live there. The toolbar keeps only sort, direction, row mode, Export CSV and Reset.
- Risk, activity, group, user, role, transaction, business area and criticality fields suggest values taken from the imported evidence (searchable, bounded). A typed value that is not suggested still filters.
- Risk and Activity matrices show tiles for users, distinct user-risk or user-activity pairs and each review status (Pending, Accepted, Rejected, Outdated; Pending, Approved, Conditional, Removal required, Outdated). Counts cover the whole filtered matrix, not the visible page; a status tile toggles the matching filter.
- A matrix cell opens the investigation drawer for that one user-risk or user-activity: only the matching activities, role assignments and risk acceptance are listed, with **Show all review items** to widen it. A user row opens everything. The business area reuses the configured module icon and color when it names a module.
- CSV exports use exactly the filters shown, including assignment validity (active, expired, future, unknown, all).

## Matrix cells and scope

- Cells show one status pill and one short count: for the Risk Matrix the acceptance status and reviewed/total activities, for the Activity Matrix the review status and ×roles supplying the activity (⧉ marks overlapping coverage). Full wording stays in each cell's accessible name. Criticality and type are in the column tooltip and the investigation, not in the grid.
- Column headers show the risk or activity pill, tinted with the color configured in Settings → SoD Risk Configuration. Row and column headers stay sticky.
- The Activity Matrix lists activities that contribute to at least one potential conflict (both sides of an enabled, supported risk are required). Other activities a role supplies are considered in Role Assignment Review, which shows the additional activities. Unavailable evidence is never shown as "no conflict".
- Page, row grouping, scroll position and filters survive opening a role or user page and returning with Back, within the session.

## Review workspace

- **Reviews → Work queue** lists one row per SAP user with overall progress and separate progress for activity review, role assignment review and risk acceptance. Filter by Needs review, Complete or Removal recommended. The queue CSV still exports every review item with its decision (`GET /api/sod/queue/users` feeds the table).
- **Open Review** (also from a matrix cell or Explorer row) opens one panel with three independent sections: **Activity Review**, **Role Assignment Review** and **Risk Acceptance**. Each row has its own decision button; tick several rows of one section and use **Review selected** for a batch with a single justification. Decision history opens on demand per item. The panel footer shows overall progress.
- Supporting evidence (transactions, supplying roles, removal impact, what-if simulation) sits in a collapsible section, open when the panel was opened from a specific risk or activity. Names stay self-reported, every decision keeps its evidence version, and no decision changes detection or SAP.

## Assignment filters and bulk review (Access Explorer → Assignments)

- **Exact role suffix.** *Role suffix* matches the organizational suffix token of the **actual assigned role** (the text after its last `:`, `_` or `-`), case-insensitively and as a whole token, never as a substring and never through the matched catalogue pattern. Selecting `CDK` lists only assignments whose own role ends in `:CDK`; `EMS`, `ES2`, `ENO`, `ESH` or `ENP` assignments of the same catalogue role are excluded, and so is `XCDK`. Several suffixes combine with OR; they combine with every other filter with AND. The same assignment-level predicate (role, suffix, SAP User Group, activity, transaction and assignment review status) drives the Assignments rows, counts, pagination, selection, Roles lookup, work queue, remediation rows and CSV exports.
- **Multi-select SAP username and Role suffix.** The lists stay open while values are toggled and close on outside click, Escape, Tab or Close. Search inside the list never drops selections; *Select all N* acts on the values currently listed and says so (the options follow the other active filters), and *Clear selection* or *Clear all* empties it. Arrow keys move, Enter toggles, Backspace removes the last chip. The API accepts repeated `usernames` and `role_suffixes` query parameters.
- **Review queue.** The Assignments tab opens on *Needs attention (default)*: Pending, Investigate and Outdated assignments. The sidebar *Assignment review status* also offers *Pending review*, *Under investigation*, *Reviewed assignments* (completed Keep or Remove) and *All assignments*; Reset returns to the default and Saved Filters keep the choice. Filtering works on individual assignments (one user can have reviewed and unreviewed roles), and rows, counts, pages, selection and CSV follow it. A progress strip shows the assignments in scope, completed, pending, under investigation, outdated and remaining. Filtering never deletes decisions; completed ones stay in history, reports and the Reviewed and All views. The assignment CSV adds ASSIGNMENT_ID and ROLE_SUFFIX and keeps every individual decision.
- **Selection.** Each Assignments row has a checkbox keyed by the stable assignment identifier. The header checkbox selects the rows on the page; *Select all N matching* gathers every filtered assignment across pages (`GET /api/sod/explorer/access_list/selection`, up to 5,000). The toolbar shows the count and the scope (on this page, on other pages or outside the current filters, matching the filters). Changing filters never adds assignments to an existing selection.
- **Batch review.** *Keep*, *Recommend removal* (Remove) and *Investigate* open a confirmation with the number of assignments, SAP users, roles and suffixes, a self-declared reviewer and a rationale. Keep, Remove and Investigate each write one assignment review event per assignment through the same decision store as individual reviews, so every assignment keeps its own history and its own decision (a user can hold Keep, Remove, Investigate and Pending assignments at the same time). **Investigate is a review decision, not a final one**: the assignment stays outstanding until it is kept or recommended for removal, and the Investigate event stays in its history. Investigate can optionally also track one *Investigate assignment* remediation action (an open action is reused, never duplicated); decisions and action lifecycle stay separate. Completed Keep or Remove decisions are skipped unless the replacement is explicitly confirmed; earlier decisions stay in the history. Historical investigation actions are shown as actions only and are never treated as recorded decisions. Results are reported per assignment (saved, skipped, failed); success is reported only after the server persisted it, and failed or skipped assignments stay selected. `POST /api/sod/decisions/assignment/bulk` enforces evidence generation, revision and per-assignment evidence versions. Nothing is written to SAP or to imported data.

## Reports, branding and export notices

- **Report branding** (Settings → Organization & SAP System): an optional report-only logo. PNG or JPEG, up to 1 MB and 32 to 4096 pixels per side; SVG and WebP are rejected. Images are decoded, resized to at most 1024 px, stripped of metadata and stored privately with other branding assets (not in configuration packages or release artifacts). It is saved immediately, can be replaced or removed, and is used in PDF and DOCX reports (`GET/PUT/DELETE /api/sod/reports/branding`). Without it, reports use the application logo when one is set. The logo is not review evidence and is not part of a frozen period snapshot.
- **Formal report** (English only, written for management readers): sections follow the reading order Executive Summary, Scope and Evaluation Period, Overall Findings and Risk Exposure, Review Progress (activity, role assignment and risk acceptance decisions), Compensating Controls, Outstanding Risks and Actions, Remediation Responsibilities and Status, Evidence Freshness and Limitations, Changes, Conclusion and Approval, Technical Appendices. SAP terms are explained in a short glossary, the body stays free of transaction codes, and individual decisions, evidence paths and checksums are in the appendices. Section selection, document metadata, management comments and DOCX/PDF export are unchanged. The executive summary and outstanding sections keep the states apart. Review status separates *not reviewed*, *reviewed, no action required*, *reviewed, removal recommended* and *reviewed, risk rejected*. Removal follow-up separates *removal recommended*, *action completed (manually recorded, not proof of removal)* and *removal verified in later source evidence*.
- **Access remediation report** (CSV, DOCX, PDF): also lists role assignments *awaiting review* and adds the status tables, so it is useful before any decision or action exists, with an explicit note that no actions are recorded. Nothing in it claims that access was removed.
- The report forms show the essentials (period or context, title, status, handling groups) and keep people, roles, version, date and comments under "Document details". The Norwegian language option was removed; older API requests that send `language` remain accepted and produce the English report.
- **Report status** distinguishes four labels: *Draft* (not reviewed or approved), *Reviewed* (a reviewer is named; the name is not authenticated, so it is not an approval), *Approved* (the period has a recorded approval and is frozen; names are still typed locally) and *Externally signed* (the preparer states it was signed outside SAP Lens; the signature is not verified). Approved and Externally signed require a frozen period. Earlier values *For review* and *Approved snapshot* are read as Reviewed and Approved. The preview, DOCX and PDF show the same status statement.
- **Export notice**: every export reports through one notice fixed at the top of the application. It overlays the page, so nothing shifts. Success and cancel messages fade after a few seconds; errors stay until dismissed.

## Consolidated review workflows

- **Summary tiles** that filter are buttons: the matrix status and criticality tiles and the assignment queue tiles (In scope, Completed, Pending, Under investigation, Needs review, Removal recommended). The active tile is highlighted, clicking it again toggles it off, tiles combine with the sidebar filters and *Reset tile filters* clears them. Informational tiles (for example Outdated) stay flat and dashed.
- **Overview.** The heatmap title, Risks/Activities toggle, sort and Export CSV share one wrapping row. With no approved period and no open period the review card is a compact empty state with *Open review periods*.
- **Access Explorer.** Assignments show the SAP username and role as codeblocks with risk and activity pills; module labels, the Active assignment badge and validity dates are left out (non-active assignments keep their status badge, and the validity scope filter defaults to active assignments). Roles show the role codeblock, users, risks, activities and *Show users*. Role conflicts use the colored Risk ID pill.
- **Role Assignment Review rows** are one compact line: checkbox, copyable role, review status, Keep, Investigate and Remove icons and an expand control. Expanding shows SAP User Group, validity, activities, risks, transactions, decision history and further actions. *Select all visible* and *Review selected* ask for confirmation of the number of assignments; every assignment keeps its own history.
- **Reviewer name.** The self-reported name is remembered for the browser session and reused by quick decisions, forms, bulk review and report preparation; it can always be changed and is stored with each decision, never as an authenticated identity.
- **Work queue and periods.** The queue shows usernames as codeblocks, tile filters and an icon action. The period menu uses icons, a trigger as tall as the Open button and keeps Delete set apart behind its confirmation. Reports open with *Document details* expanded.
