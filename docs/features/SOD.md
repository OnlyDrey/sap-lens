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
| Reviews | Work queue with one row per SAP user and a unified review workspace (Activity Review, Role Assignment Review, Risk Review with separate formal acceptance), and Remediation tracking. |
| Review Periods | Frozen snapshots, workflow, a per-row action menu, comparison in a dialog and audited deletion. |
| Reports | Formal review report and access remediation report. |

Business matrices (for example Finance or P2P) are **Saved Filters** on the two matrices,
not separate pages. The risk catalogue stays in Settings → SoD Risk Configuration.
One **review context bar** sits beneath the SoD navigation on every page: choose current evidence or a review period (frozen after approval) and see the evaluation date and whether the evidence is live or a frozen snapshot. Pages do not repeat this information.

## Access decisions and formal acceptance

1. **Role assignment review** (user + exact assignment + period): Keep, Remove,
   Investigate or Pending; Keep displays as Approved. One approved supplier can derive
   Activity Approved without approving every other role supplying that activity.
2. **Activity review** (user + activity): Approved, Remove, Investigate or Pending,
   with the existing Approved with conditions option retained as a Conditional event.
   The primary badge remains Approved and the recorded conditions remain visible.
   Explicit current review takes precedence over derived supplier decisions.
3. **Normal risk review** (user + risk + period): Approved, Remove, Investigate or
   Pending. Risk Approved means acceptable for this review; it is not formal acceptance.
   Risk Remove requires a specific remediation plan and never removes roles automatically.
4. **Formal risk acceptance** (user + risk): Accepted, Rejected or Pending, with a named
   approver different from the reviewer, justification, optional controls and expiry.
   It remains independent of normal risk review and retains its approval gates.

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
- Source criticality labels (for example C/H) are shown literally as evidence, in settings, reports and the investigation. Operational views (matrices, explorer, reviews, remediation, conflicts) no longer filter by criticality.
- Private backups must include the SoD stores. Portable configuration and diagnostics
  exports exclude them. Use only synthetic data in examples and tests.

Source import: [Data & CSV](../data/IMPORT_AND_REFRESH.md), synthetic example
[sod-matrix.example.csv](../../examples/sod-matrix.example.csv). API: [SoD API](../architecture/API.md#sod-api).
Validation and open native acceptance items: [validation tracker](../validation/README.md)
and [validation tracker](../validation/README.md).

## SoD Risk Configuration (Settings)

Settings provides Risks and Activities tabs, server-side search and compact tables.
Display name resolves non-empty local overrides, active import metadata, then curated
reference guidance. **Missing display name** means none exists. Local storage/API fields
remain compatible; displaying or saving untouched inherited text creates no override.

- Risks: identifier and Display name, Related Activities, Status, Description Review,
  Modified and Edit. Criticality and Type stay compact metadata within the Risk cell.
- Activities: identifier and Display name, Related Risks, Transactions, Modified and Edit.
  A list icon marks the compact Transactions action in the table, modal and both source slots.
- Relationships come from imported mappings, never description text. Current activity
  relationships exclude historical-only risks; retained definitions remain inspectable.
- Enabled/Disabled and description-review status retain their existing meaning. Description
  review is independent of access review and formal risk acceptance.

### Entity details and navigation

Previous/Next follows the originating filtered, server-sorted list across table pages.
Unavailable directions are disabled. Related pills navigate Risk ↔ Activity within the
same detail workflow. The header contains only Previous, position and Next; internal history keeps
at most 20 locations, and closing details preserves the originating tab and search.
A changed revision/source invalidates list navigation rather than mixing generations.
Very large navigation scopes are bounded; refine the filters if the guard reports one.

Navigation, Cancel and window close protect unsaved edits. Cancel the discard prompt
to keep the draft; confirm it to navigate without saving. Save still checks the original
catalogue revision and definition identity. A missing/removed entity shows a controlled error.

Both editors share a compact identifier/Display name header, related pills, contextual
metadata and an imported-mappings information button. The body scrolls independently of
Save/Cancel. English-only editable guidance, local colors and risk-specific settings remain;
older Norwegian fields are preserved in storage. Immutable IDs, mappings, Type and
Criticality are available through Source details and cannot be edited here.

### References and descriptions

The compact reference section shows library version and coverage with a confirmed Reset
defaults action. Advanced reference settings contain custom workbook import, coverage-ID
lists and **Download template**. The synthetic template follows the real importer schema;
Desktop uses its Save dialog and hosted deployments download through the authenticated API.
See [reference data, precedence and maintenance](../data/SOD_MATRIX.md#curated-reference-workbook).

Pills use the same icons/colors and compact descriptions across configuration and review
views. Exact active IDs in read-only guidance are not inferred relationships. Related
pills in the Settings workflow use its navigation instead of nesting competing editors;
standalone description popovers retain viewport bounds and scrolling. Full provenance and
alternate text remain in Source details without repeating them beside every field.
Source management remains under Data Sources; catalogue and investigation exports are
preserved outside this configuration page. Original reference workbooks are not distributed.

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


The **Create SoD review period** dialog is a two-column grid (name and evaluation date, then period start and end) that stacks on narrow screens; Cancel and Capture review period carry icons. In the delete dialog, *Recorded by (self-reported)* and the period-name confirmation share a grid row, consequences and impact stay full width, and Cancel and Delete permanently (or Archive period) carry icons; the confirmation rules and audit behavior are unchanged. In the Review Periods toolbar, *Compare periods* stays disabled with fewer than two eligible periods and explains why through a tooltip and an accessible description (no inline text), and *Show archived periods* is a visible toggle button with an archive icon that only changes visibility, never a period status.

## SAP User Group heatmap

One shared heatmap, **Conflicts by SAP User Group**, sits directly under the Review Context on every SoD page (Overview, Risk Matrix, Activity Matrix, Access Explorer, Reviews, Review Periods and Reports). It shows distinct users per SAP User Group and risk (or activity) for the selected review context. Darker cells have more users; the Users column and the Distinct users row are distinct counts. A user in several groups counts in each group, so group counts can exceed the distinct total. The 25 most affected columns are shown; the matrix lists all of them. Sort by group, distinct users or number of risks/activities, and export with **Export heatmap CSV** (long format: group, item, users with the item, users in the group with items).

- **Collapse.** The heading is a button; the heatmap is expanded by default. The choice is kept for the session only (session storage, never review evidence or a decision): it holds across SoD pages and reloads, and the heatmap is expanded again in a new session or after the application restarts.
- **Filtering.** Select a group (row header), a risk or activity (column header) or a cell. On Risk Matrix, Activity Matrix, Access Explorer and Reviews the selection is written into that page's own group and risk or activity filters, so it is visible in the page filters and in the removable chips under the heatmap title, and every other filter is kept. **Clear heatmap filters** removes only the group and risk or activity filters. On Overview, Review Periods and Reports (which cannot filter by them) a selection opens the Risk Matrix or Activity Matrix with the filter applied; nothing is filtered silently.
- **Scope.** Counts follow the review context and match the heatmap CSV. When SoD analysis is unavailable the page's own notice explains why and the heatmap is not shown.
- **Matrix identity column and grouping.** In the Risk and Activity Matrix the first column shows the SAP username on one line as the usual copyable codeblock and stays pinned to the left edge (opaque background, border and stacking above the cells) while the matrix scrolls sideways. The user's SAP User Group has its own plain-text **SAP User Group** column right after it, pinned with it (on screens narrower than 640 px only the username stays pinned); it is hidden while *Group by SAP User Group* is on, because the group headers already carry it, and users in several groups then keep an "Also in" note as a tooltip and screen reader text. Sort offers *SAP User Group* (users without a group always come last). *Group by* offers *No grouping* (default) and *SAP User Group*. Grouped, the matrix lists the same users and cells under collapsible group headers that show distinct users and finding cells (user-risk or user-activity pairs) for the whole filtered scope; *Expand all* and *Collapse all* are on the matrix and collapsed groups survive paging. Each user appears once, under the first of their groups that the SAP User Group filter selected, otherwise under their first group (other groups are noted beneath the username), so groups partition the users. Paging counts users and a group continued on the next page is marked. **Users per page** (10, 25, 50, 100 or All; default 50) sits in the toolbar next to *Group by*, with a range such as *1–50 of 244 users* and Previous/Next above and below the matrix. The setting is shared by the Risk and Activity Matrix for the session; pages are cut after every filter (including the shared SoD filters) and after grouping, so no user repeats across pages, and any filter, sort or grouping change returns to page 1. *All* loads up to 5000 users on one page (a notice appears if more match); CSV exports always contain every filtered user. Grouping is presentation only: detection, review decisions, snapshots and CSV exports (which follow the filters, not the grouping) are unchanged. SAP User Group is a multi-select filter whose list stays open while values are toggled; it works together with grouping and the other filters.

## Filters, tiles and drawer

- Every SoD page (matrices, Access Explorer, Role Conflicts, User Conflicts) uses the same **Filters** sidebar: search, Saved Filters and all filters live there. The toolbar keeps only sort, direction, row mode, Export CSV and Reset.
- Risk, activity, group, user, role, transaction and business area fields suggest values taken from the imported evidence (searchable, bounded). A typed value that is not suggested still filters.
- Risk and Activity matrices show tiles for users, distinct user-risk or user-activity pairs and each explicit review status (formal Pending/Accepted/Rejected/Outdated; activity Pending/Approved/Conditional legacy/Removal required/Outdated). Counts cover the whole filtered matrix, not the visible page; a status tile toggles the matching filter.
- A matrix cell opens the investigation drawer for that one user-risk or user-activity: only the matching activities, role assignments, normal Risk review and formal acceptance are listed, with **Show all review items** to widen it. The username and Open user icon navigate directly to User Details; the panel icon opens all review items. The business area reuses the configured module icon and color when it names a module.
- CSV exports use exactly the filters shown, including assignment validity (active, expired, future, unknown, all).

## Shared SoD filters

Compatible filters follow the user from one SoD page to the next with no Apply step. One source of truth (`sodFilters.shared` in the view history; nothing is persisted by the backend) holds the dimensions that mean the same on every page that offers them: **SAP User Group, SAP username, risk, activity, transaction code, business area and assigned role** (single and multi-select values). Everything else (decision filters, role suffix, validity, search, sort, status tiles, the Remediation tracking toggle, *Risks per user*) is local to its page.

- **Pages.** Risk Matrix, Activity Matrix, the Access Explorer tabs Users, Assignments and Roles, Reviews (Work queue) and Remediation share all seven dimensions; Role Conflicts offers risk, transaction code and business area only (it filters catalogue roles, so assigned-role, user and activity selections do not apply). Overview shows the shared group and risk selection in the heatmap and its investigation links add their own selection to the existing filters instead of replacing them. Review Periods, Reports and Settings do not read investigation filters.
- **Unsupported selections** stay stored, do not narrow results on a page that does not offer them, show no chip there and come back on a page that does.
- **Clear page filters** (the sidebar's Clear) empties the page's own filters and the shared dimensions that page offers; shared dimensions it does not offer, and other pages' local filters, stay. **Clear all SoD filters** empties the whole filter context (shared and every page's local filters); decisions, Saved Filter definitions, imported data and the review context are untouched.
- **Saved Filters** store and load the page's filters including the shared dimensions, so loading one updates the shared context.
- **Review context** (Current evidence or a review period) is separate state: it stays selected across SoD pages and changing it keeps the scope filters, which never alter detection, decisions, snapshots, approvals or evidence. Exports use the same filters and the selected context.
- **History.** Filter changes are history steps, so browser Back and Forward restore the filters of each step.

## Matrix cells and scope

- Cells show one status pill and one short count: for the Risk Matrix the acceptance status and reviewed/total activities, for the Activity Matrix the review status and ×roles supplying the activity (⧉ marks overlapping coverage). Full wording stays in each cell's accessible name. Criticality and type are in the column tooltip and the investigation, not in the grid.
- Column headers show the risk or activity pill, tinted with the color configured in Settings → SoD Risk Configuration. Row and column headers stay sticky.
- The Activity Matrix lists activities that contribute to at least one potential conflict (both sides of an enabled, supported risk are required). Other activities a role supplies are considered in Role Assignment Review, which shows the additional activities. Unavailable evidence is never shown as "no conflict".
- Page, row grouping, scroll position and filters survive opening a role or user page and returning with Back, within the session.

## Review workspace

- **Reviews → Work queue** lists one row per SAP user with overall progress and separate progress for activity review, role assignment review, risk access coverage and formal acceptance. Filter by Needs review, Complete or Removal recommended. The queue CSV retains its existing raw review and formal-acceptance fields (`GET /api/sod/queue/users` feeds the table).
- **Open Review** (also from a matrix cell or Explorer row) opens one panel with three sections: **Activity Review**, **Role Assignment Review** and **Risk Review**, with a separate Formal acceptance action inside Risks. Each row has its own decision button; tick several rows of one section and use **Review selected** for a batch with a single justification. Decision history opens on demand per item. The panel footer shows overall progress.
- Supporting evidence (transactions, supplying roles, removal impact, what-if simulation) sits in a collapsible section, open when the panel was opened from a specific risk or activity. Names stay self-reported, every decision keeps its evidence version, and no decision changes detection or SAP.


The filter tiles of the Work Queue (review progress) and Remediation (recommended handling) are the same shared `Kpi` control: one size, radius, selected state (`aria-pressed`), hover and focus ring. Their logic stays their own: the queue tiles filter users by review progress, the remediation tiles filter rows by recommended handling, and *Awaiting review* and *Overdue* are informational tiles (zero is neutral). The tracking toggles (All rows, Awaiting action, Verified removals) and the shared SoD filters work alongside the tiles. In Review Periods the period name and its *Active period* badge sit 8 px apart and wrap together on narrow screens.

## Assignment filters and bulk review (Access Explorer → Assignments)

- **Exact role suffix.** *Role suffix* matches the organizational suffix token of the **actual assigned role** (the text after its last `:`, `_` or `-`), case-insensitively and as a whole token, never as a substring and never through the matched catalogue pattern. Selecting `CDK` lists only assignments whose own role ends in `:CDK`; `EMS`, `ES2`, `ENO`, `ESH` or `ENP` assignments of the same catalogue role are excluded, and so is `XCDK`. Several suffixes combine with OR; they combine with every other filter with AND. The same assignment-level predicate (role, suffix, SAP User Group, activity, transaction and assignment review status) drives the Assignments rows, counts, pagination, selection, Roles lookup, work queue, remediation rows and CSV exports.
- **Multi-select SAP username and Role suffix.** The lists stay open while values are toggled and close on outside click, Escape, Tab or Close. Search inside the list never drops selections; *Select all N* acts on the values currently listed and says so (the options follow the other active filters), and *Clear selection* or *Clear all* empties it. Arrow keys move, Enter toggles, Backspace removes the last chip. The API accepts repeated `usernames` and `role_suffixes` query parameters.
- **Review queue.** The Assignments tab opens on *Needs attention (default)*: Pending, Investigate and Outdated assignments. The sidebar *Assignment review status* also offers *Pending review*, *Under investigation*, *Reviewed assignments* (completed Keep or Remove) and *All assignments*; Reset returns to the default and Saved Filters keep the choice. Filtering works on individual assignments (one user can have reviewed and unreviewed roles), and rows, counts, pages, selection and CSV follow it. A progress strip shows the assignments in scope, completed, pending, under investigation, outdated and remaining. Filtering never deletes decisions; completed ones stay in history, reports and the Reviewed and All views. The assignment CSV adds ASSIGNMENT_ID and ROLE_SUFFIX and keeps every individual decision.
- **Selection.** Each Assignments row has a checkbox keyed by the stable assignment identifier. The header checkbox selects the rows on the page; *Select all N matching* gathers every filtered assignment across pages (`GET /api/sod/explorer/access_list/selection`, up to 5,000). The toolbar shows the count and the scope (on this page, on other pages or outside the current filters, matching the filters). Changing filters never adds assignments to an existing selection.
- **Batch review.** *Keep*, *Recommend removal* (Remove) and *Investigate* open a confirmation with the number of assignments, SAP users, roles and suffixes, a self-declared reviewer and a rationale. Keep, Remove and Investigate each write one assignment review event per assignment through the same decision store as individual reviews, so every assignment keeps its own history and its own decision (a user can hold Keep, Remove, Investigate and Pending assignments at the same time). **Investigate is a review decision, not a final one**: the assignment stays outstanding until it is kept or recommended for removal, and the Investigate event stays in its history. Investigate can optionally also track one *Investigate assignment* remediation action (an open action is reused, never duplicated); decisions and action lifecycle stay separate. Completed Keep or Remove decisions are skipped unless the replacement is explicitly confirmed; earlier decisions stay in the history. Historical investigation actions are shown as actions only and are never treated as recorded decisions. Results are reported per assignment (saved, skipped, failed); success is reported only after the server persisted it, and failed or skipped assignments stay selected. `POST /api/sod/decisions/assignment/bulk` enforces evidence generation, revision and per-assignment evidence versions. Nothing is written to SAP or to imported data.

## Reports, branding and export notices

- **Report branding** (Settings → Organization & SAP System): an optional report-only logo. PNG or JPEG, up to 1 MB and 32 to 4096 pixels per side; SVG and WebP are rejected. Images are decoded, resized to at most 1024 px, stripped of metadata and stored privately with other branding assets (not in configuration packages or release artifacts). It is saved immediately, can be replaced or removed, and is used in PDF and DOCX reports (`GET/PUT/DELETE /api/sod/reports/branding`). Without it, reports use the application logo when one is set. The logo is not review evidence and is not part of a frozen period snapshot.
- **Formal report** (English only, written for management readers): sections follow the reading order Executive Summary, Scope and Evaluation Period, Overall Findings and Risk Exposure, Review Progress (activity, role assignment and risk acceptance decisions), Compensating Controls, Outstanding Risks and Actions, Remediation Responsibilities and Status, Evidence Freshness and Limitations, Changes, Conclusion and Approval, Technical Appendices. SAP terms are explained in a short glossary, the body stays free of transaction codes, and individual decisions, evidence paths and checksums are in the appendices. Section selection, document metadata, management comments and DOCX/PDF export are unchanged. The executive summary and outstanding sections keep the states apart. Review status separates *not reviewed*, *reviewed, no action required*, *reviewed, removal recommended* and *reviewed, risk rejected*. Removal follow-up separates *removal recommended*, *action completed (manually recorded, not proof of removal)* and *removal verified in later source evidence*.
- **Descriptions in reports.** The formal report and the access remediation report resolve risk and activity names and descriptions with the same resolver as the pills
  (non-empty local override, then imported metadata, then curated reference guidance, then "—"/"Not available"). Wherever any description exists they add a *Risk* table (Risk, Name, Description, Source)
  to *Overall Findings and Risk Exposure* and, with the technical appendices, an *Activity* table; a source legend explains *Imported*, *Local override*, *Curated reference library* and *Not available*, and an
  imported description that differs from a local one is marked, not mixed in. Reports for files without descriptions are unchanged. Transaction descriptions stay as supplied in the CSV.
  **Historical integrity:** a review snapshot stores its own copy of the resolved descriptions when it is captured, so a period's report (approved or still open) never shows
  descriptions imported or edited later; only a new period or a recapture sees them. A snapshot captured before R8.1 has no copy: its report shows only the local business text that was frozen with its
  risk records, says that imported descriptions were not retained for the period, and never substitutes today's imported values. The remediation report for *current evidence* uses today's
  descriptions and says so; for a period it uses the frozen copy. Descriptions never influence detection, decisions or approvals. A description with characters outside the bundled PDF font
  (for example CJK) makes the PDF fail with the existing explicit message while the editable DOCX works.
- **Access remediation report** (CSV, DOCX, PDF): also lists role assignments *awaiting review* and adds the status tables, so it is useful before any decision or action exists, with an explicit note that no actions are recorded. Nothing in it claims that access was removed.
- The report forms show the essentials (period or context, title, status, handling groups) and keep people, roles, version, date and comments under "Document details". The Norwegian language option was removed; older API requests that send `language` remain accepted and produce the English report.
- **Report status** distinguishes four labels: *Draft* (not reviewed or approved), *Reviewed* (a reviewer is named; the name is not authenticated, so it is not an approval), *Approved* (the period has a recorded approval and is frozen; names are still typed locally) and *Externally signed* (the preparer states it was signed outside SAP Lens; the signature is not verified). Approved and Externally signed require a frozen period. Earlier values *For review* and *Approved snapshot* are read as Reviewed and Approved. The preview, DOCX and PDF show the same status statement.
- **Export notice**: every export reports through one notice fixed at the top of the application. It overlays the page, so nothing shifts. Success and cancel messages fade after a few seconds; errors stay until dismissed.

## Consolidated review workflows

- **Summary tiles** that filter are buttons: the matrix status tiles and the assignment queue tiles (In scope, Completed, Pending, Under investigation, Needs review, Removal recommended). The active tile is highlighted, clicking it again toggles it off, tiles combine with the sidebar filters and *Reset tile filters* clears them. Informational tiles (for example Outdated) stay flat and dashed.
- **Actionable Overview metrics.** *Users with more than one risk* counts SAP users with at least two different risk IDs (activities or roles repeating one risk count once) and opens Access Explorer with the *Risks per user* filter. *Remediation awaiting action* counts role assignments recommended for removal that have no tracked remediation action and opens Remediation with *Awaiting action* selected; Open actions and Overdue actions open Remediation. Conflicts, Reviews and Remediation rows share one height so the cards align. The Overview does not list conflicting roles or verified remediation; the data stays available in the API (`concentration`, `verification`) and *Verified removals* remains a filter on Remediation (a removal verifies only with a newer User-Role import without the assignment; a Completed status never verifies).
- **Overview.** With no approved period and no open period the review card is a compact empty state with *Open review periods*.
- **Access Explorer.** Assignments show the SAP username and role as codeblocks with risk and activity pills; module labels, the Active assignment badge and validity dates are left out (non-active assignments keep their status badge, and the validity scope filter defaults to active assignments). Roles show the role codeblock, users, risks, activities and *Show users*. Role conflicts use the colored Risk ID pill.
- **Role Assignment Review rows** are one compact line: checkbox, copyable role, review status, Keep, Investigate and Remove icons and an expand control. Expanding shows SAP User Group, validity, activities, risks, transactions, decision history and further actions. *Select all visible* and *Review selected* ask for confirmation of the number of assignments; every assignment keeps its own history.
- **Reviewer name.** The self-reported name is remembered for the browser session and reused by quick decisions, forms, bulk review and report preparation; it can always be changed and is stored with each decision, never as an authenticated identity.
- **Work queue and periods.** The queue shows usernames as codeblocks, tile filters and an icon action. The period menu uses icons, a trigger as tall as the Open button and keeps Delete set apart behind its confirmation. Reports open with *Document details* expanded.

## Evidence dialogs and review rows

- **Access Explorer evidence.** In the Users tab the evidence button of a row (for example "3 roles") opens a wide modal: a compact summary (SAP user, risk, activities, role count), a table of the roles that scrolls inside the dialog, and shortcuts to open the SAP user or investigate. In the Roles tab the users count opens the users behind that role (SAP username codeblocks with navigation, SAP User Group, assignment intervals, Investigate). Escape closes them.
- **Potential SoD evidence.** The dialog for a finding starts with a summary (subject, risk with its source criticality, both required activities) and then one section per activity side, each with a scrollable table whose columns keep the kinds of evidence apart: Transaction (mapped to the activity), Single role, Assigned role (what the user actually has), Catalogue role or pattern (the match, exact or wildcard) and Assignment validity, plus Technical provenance. It describes potential conflicts and never effective SAP authorization.
- **Risk Review rows.** The primary row is checkbox, Risk ID, normal decision and separate Review risk / Formal acceptance actions; the description sits below and the decision history is collapsed behind the disclosure control. Bulk review, filters, decisions, removal recommendations and history are unchanged, and nothing changes in SAP.

## SAP User Group column in SoD tables

SAP usernames are always one line (copy and open actions unchanged); the SAP User Group is never stacked beneath them. Wherever a row is one SAP user it has a dedicated **SAP User Group** column right after **SAP user**, rendered by the shared `UserGroupCell` (plain compact text, the full value in the tooltip, a muted dash with the accessible text "No SAP User Group" when the data has none): Risk and Activity Matrix, Access Explorer *Users* (by risk and by activity) and *Assignments* (the group of that assignment), the Reviews *Work queue* and *Remediation* (the group of the assignment). *Roles* and *Role conflicts* aggregate users of different groups, so they show no group column rather than inventing one. CSV exports carry the group (`USER_GROUPS` in the Explorer user-activity, user-risk and review-queue exports, `USER_GROUP` in the assignment and remediation exports) whatever the table shows, and keep the active filters and their unpaged scope. Sorting by group is offered where the table has a sort control (the matrices).

## Risk and activity pill descriptions

Every risk and activity pill keeps its own color and shows, on hover, the identifier with its name and the start of its description (or "No description
available"). A free-standing pill is also a button: Enter or Space opens a popover with the identifier, display name, description, impact, business process,
source criticality (risks) or type and risk count (activities), each value marked as imported from the SoD CSV, local business text or curated reference guidance, with Escape closing it.
Pills inside controls that already have an action (matrix column headers, heatmap headings, source-detail buttons) keep the tooltip and add no second control.
Descriptions come from one resolver: non-empty local overrides first, imported metadata second, curated reference guidance third, never generated text. See
[optional descriptive columns](../data/SOD_MATRIX.md#optional-descriptive-columns).

### Access review completion and sidebar tabs

Open a user's review to work through **Roles → Activities → Risks**. One Reviewer
field applies across the tabs and retains unsaved work when switching. Individual
server accounts use the authenticated reviewer; Desktop names remain self-reported.

Current role decisions can cover an activity when every relevant supplying
assignment is reviewed. Current activity/role evidence can then cover the risk's
access assessment, without creating a formal acceptance. The panel shows the
coverage provenance. The queue reports the same unique completion across the
selected scope, separately from formal acceptance. “Reviewed — removal planned”
means the explicit proposed removals break the risk in simulation; the imported
conflict remains present until refreshed evidence verifies removal.

### Work Queue sorting and user navigation

Click a column heading to sort the complete filtered queue before pagination;
click again to reverse it. Progress categories sort by reviewed/total, with an
empty category treated as 0% and SAP username as the stable tie-break. The default
puts users requiring review first, then username ascending (regardless of their outstanding item counts). Sort state is retained
in navigation history and Saved Filters. Formal acceptance stays distinct from
risk access-review completion.

Clicking a SAP username opens its User Access profile, while **Open review**
continues to open the SoD workspace. Copy remains independent; route links retain
normal modified-click behavior.

The Work Queue keeps removal recommendations in its KPI/filter and exports, rather than
repeating them in a table column or beneath each progress bar. Progress calculations,
formal acceptance and review decisions remain unchanged.

### Work Queue bulk assignment review

**Bulk review**, beside Export CSV, reuses the assignment review store. Choose exact
role names (default), explicit role prefixes or wildcard patterns; suffixes and
users remain multi-selectable. SAP User Groups always match exactly. Select all
uses the complete server-filtered scope, not just the visible preview page;
explicit selections are retained when filters change, but out-of-filter selections
are disclosed and excluded from execution. Scopes above 5000 preview
records must be narrowed, and each confirmed operation is limited to 1000 changes.

Preview shows current/proposed decisions and excluded assignments. Previously recorded decisions, including outdated and Investigate decisions, are
excluded by default. Including them requires the
additional overwrite confirmation; unchanged decisions are not written. Keep
approves retention; Remove recommends removal, without modifying SAP. A rationale
and reviewer are required. Authenticated server reviewers use their actual account.

Queue operations are atomic: invalid IDs, stale source/revision, a finalized period
or a failed storage write rejects the entire operation. Each event retains its
previous decision and common bulk operation ID in immutable history and the queue
CSV. The queue, matrices and individual review panels refresh after success.
Activity coverage and risk access assessment may derive from assignment review;
formal risk acceptance remains a separate decision.

### Review feedback and recovery

Only the clicked assignment action shows its loading icon; competing actions on
that assignment are disabled while other rows remain usable. Writes stay serialized
against the shared revision. A stale revision may be refreshed for an unrelated
change, but a competing decision on the same assignment is never silently retried.
The authoritative subject is refreshed first; other active progress/KPI views update
in the background. Source-only filter choices are not re-requested after a decision;
review-dependent option scopes still refresh. Source imports retain full invalidation.
No decision is shown as saved before the backend confirms it.

Configuration failures retain the draft and support retry. Unexpected backend errors
return a safe request reference for diagnostics, not a requirement to restart. Local
metadata response preparation completes before its atomic commit, preventing a
failed response dependency from silently saving an unreported edit. Storage uses
private JSON/content-addressed snapshots with locks and revision checks, not SQLite.

Review method popovers separate current access-review coverage (including supported derived
coverage) from formal acceptance. Stale decisions require review; formal-acceptance reviewers
are never attributed as derived access reviewers. Remediation expands only current-page
assignment identities beside the role. Usernames remain copyable; detailed recommendations,
reasons, controls and verification remain in that assignment's expanded rows.

### Decision-first review statuses

Four primary badges describe access decisions consistently: **Approved** (green check),
**Remove** (red trash), **Investigate** (amber search), **Pending** (neutral clock).
Review completion, actual SAP access, formal acceptance and removal verification remain
supporting concepts, not alternative primary decisions.

| Context | Effective primary decision |
|---|---|
| Role assignment | Explicit Keep → Approved, Remove → Remove, Investigate → Investigate, otherwise Pending; scoped to user, exact assignment interval and period |
| Activity | Current explicit review wins. Otherwise any approved supplying role → Approved; all suppliers Remove → Remove; otherwise any Investigate → Investigate; otherwise Pending |
| Risk review | Only the explicit normal Risk review decides Approved/Remove/Investigate/Pending; access coverage cannot grant risk approval |

Approved + Remove suppliers therefore produce Activity Approved. No current suppliers does
not imply Remove. Derived activity decisions create no synthetic activity events. Explicit
activity disagreement is disclosed with both results; legacy Conditional events are retained
and presented as Approved with their recorded conditions shown in the popover/history.
The Approved with conditions form option preserves the existing conditional-review service. Outdated approval
never grants current approval. A retained Remove may stay visible with evidence needing
review, without counting as current approval/coverage.

**Review risk** records a normal risk decision with reviewer and justification. Risk Approved
means acceptable for that review; it does not create **Formal acceptance**, which retains
its separate approver, justification, controls and approval gates. Risk Remove requires
remediation planning; it never removes every related role automatically. The popover shows
when specific removal actions still need selection. Both histories are retained separately.

The shared compact popover shows identity, effective Display name, user/period, decision,
completion, source/method, available reviewer/time, evidence and supporting role distribution.
Related role badges explain approval/removal providers; disagreements remain visible.
Assignment ID and validity prevent equal role names from sharing decisions accidentally.
Risk popovers expose normal review and formal acceptance separately. Related pills are
read-only inside the popover. Remove is a recommendation until a later complete SAP import
verifies disappearance; immutable event values and old report snapshots are never rewritten.
Escape closes the popover first, restores its trigger and leaves the review open.

### Revalidation against new source revisions

Every activated users revision is compared with the assignments that have at least one decision (`assignment-lifecycle.json`, a small validated store included in backups; nothing else is tracked):

| Case | Result |
|---|---|
| Unchanged | The decision stays current. |
| Changed (other validity, group or role) | A different assignment identity: it starts Pending and never inherits the old decision. Evidence that changes materially still marks a decision Outdated, as before. |
| Removed | Recorded as absent when absence is verifiable: the user is fully mapped and the assignment is missing, or the user is no longer in the source at all. The decision and its history are kept. |
| Reappearing | **Outdated** with the reason *Assignment reappeared after it was removed from the SAP import; review it again.* until a new decision is recorded after the reappearance. Outdated approvals grant no activity or risk coverage. |
| Ambiguous | A user who is present but only partly mapped, a failed or unavailable source, or unavailable SoD/mapping: nothing is marked in either direction. |

A user that disappears and later returns does not inherit decisions (the username may belong to someone else). The status is derived at read time: decision events, retained evidence and
frozen review periods are never rewritten, and frozen assessments ignore later reappearance. Installations upgraded from an earlier version start with no lifecycle memory, so nothing changes
until a verified absence is observed. If the file is unreadable it is ignored with a warning (behaviour as before) until restored from a backup.

#### Identity continuity and fail-safe applicability

* **Identity evidence.** The imports provide nothing more reliable than the username except the SAP e-mail address and name in the User–Role Mapping file (the Employee Directory is matched through that
  same address, so it adds no independent evidence). Hashed tokens of them are kept per tracked assignment; addresses used by several SAP users are ignored, as in the directory matching. If both the recorded
  and the current user carry evidence and share none of it, the username probably belongs to someone else and the earlier decision reads **Outdated** (*SAP user identity evidence … changed*). A changed mailbox
  with the same name, or a changed surname with the same mailbox, is continuity. Missing evidence on either side proves nothing and changes nothing.
* **Fail safe.** If the lifecycle memory is damaged or fails its checksum, is missing although it was established before (for example a backup from before this feature restored over an established installation),
  or is older than the newest state this installation wrote (an old backup restored), no assignment decision can be confirmed for the same identity: all assignment decisions read Outdated with the reason
  *Review continuity data is unavailable or cannot be trusted …*. Imports, source availability, activity/risk reviews, events, evidence and frozen periods are unaffected. A fresh or upgraded installation with no
  memory at all starts a baseline silently, as before.
* **Visibility.** Data Health lists *Review decision continuity cannot be confirmed* (warning, with the affected assignments) and *Assignments needing a new review after reappearing* (information); the storage status
  and diagnostics export carry `review_continuity` (`ok`, `corrupt`, `missing`, `stale`).
* **Recovery.** An administrator confirms *Re-baseline* (`POST /api/storage/lifecycle/rebaseline`): the current imported data becomes the continuity baseline, the damaged file is kept as
  `assignment-lifecycle.json.before-rebaseline-<time>`, the baseline is attributed to the administrator and decisions apply again. Nothing is repaired automatically.
* **Exports.** CSV and report schemas are unchanged: the status value stays `Outdated`; the reason is in the decision explanation shown by the API and the status popover.

### SAP import verification and history

Removal checks use every actual imported assignment, including expired and non-conflicting
records. A role disappearing from the active SoD finding list does not prove it was removed.
Current role popovers and assignment history retain the original Remove event and show
separate verification metadata. Verified absence requires a newer validated User–Role source
revision, the same exact user/role/validity/group identity, available source coverage and
unambiguous mapping for the user. Failed refresh, rejected/error-bearing data, unavailable
sources and ambiguous mapping cannot verify absence. Frozen periods retain their captured
evidence and do not use later imports to rewrite historical results.

Verification describes the supplied validated export scope, not effective SAP authorization
or proof that the exporter included the whole organization. Administrators must provide a
complete full-replacement export; silent truncation outside the application cannot be
established from CSV columns alone. If the user disappears or matching coverage is uncertain,
verification stays unassessable. Immutable review events and retained source/report snapshots
remain the audit evidence; no synthetic approval/removal review event is written.

Matrix and Explorer primary badges use effective decisions, including derived Activity
approval and explicit normal Risk review. Formal acceptance and coverage are supporting
information. Existing explicit-review filters, status counters and raw export lifecycle
columns retain their meanings; a derived badge does not turn an explicit Pending event into
an explicit Approved event. Remediation uses the same effective badge projection, while
recommendations and actual SAP verification remain separate.

### Shared username review action

Supported SAP username codeblocks contain four independent interactions: username
and Open user icon navigate directly to User Details, Copy copies the exact
identifier, and **Open in SoD Review** opens or switches the review sidebar.
There is no intermediate username popover.
The action is available only when that SAP identity has detected conflict evidence
in the selected review context. It opens the same non-modal panel from SoD and
User Access, including Account Review and release assignment tables. Employee-only
records, isolated Component Library previews and modal contexts without sidebar
navigation do not offer it.

Selecting another user updates the existing panel and preserves its Roles,
Activities or Risks tab. User-specific selections, forms and simulation state are
isolated; an open decision form requires confirmation before switching users.
Only the current exact user's action is highlighted. Page filters and scroll are
unchanged; copy does not open the panel.

Risk Review rows place selection, risk identifier, decision, **Review**, formal
acceptance action and details toggle before a separate description. Controls wrap
on narrow screens. Formal acceptance remains a separate action and popover value;
it is not repeated inline in every description.

### SAP User Group provenance

User Access and SAP Identity summarize imported `USER_GROUP` values. SoD shows the
groups from the contributing assignment evidence for its review context and
validity scope. Different scopes can legitimately differ. Work Queue aggregation
uses current scoped items even when retained historical reviews sort first;
historical-only items cannot erase or supply current groups. Missing groups stay
missing, and multiple source groups are preserved. Groups are never inferred from
role suffixes, AD membership or related usernames.

### Reviews navigation

Reviews contains **Work queue → Bulk Review → Remediation**. Bulk Review embeds
the same assignment selector and confirmation component used by the existing
review tools. Work queue's Bulk review action opens that tab. Direct routes are
`#/sod/reviews`, `#/sod/reviews/bulk` and `#/sod/reviews/remediation`; reload and view
history retain the chosen tab. Access Explorer remains the analysis workspace.
The confirmation freezes its context, source generation and decision revision
with the selected assignments; background reads cannot silently refresh a preview
into permission to overwrite a newer decision.

### Complete Bulk Role Review and base-role filters

Bulk Review defaults to all active imported user–role assignments matching its
filters, including users/roles without detected conflicts. Choose Keep, Remove or
Investigate, explicitly select assignments (or all matching across pages), inspect
the preview and continue to the final confirmation. Remove is a recommendation,
never an SAP operation. Reviewer and rationale follow the existing review policy.
Previously reviewed assignments are excluded by default; including them requires
an additional replacement confirmation. The preview shows selected users, roles,
assignments, excluded/unchanged rows and current/proposed decisions. Selection
outside current filters is counted explicitly. Context, generation and revision
are frozen; stale or protected atomic submissions save nothing.

The shared Assigned role selector groups only recognized business-role families
using the existing naming evidence or an explicit catalogue `:*` pattern. New
family choices and new exact fallback choices are stored separately from legacy
role/search selections. Multiple choices are OR; exact suffix choices are OR;
role and suffix categories combine with AND. Unproven suffixes, opaque identifiers,
release-role tokens and interior wildcard patterns stay exact rather than being
silently grouped. The current CSV assignment parser remains unchanged; catalogue
wildcards are not treated as direct transaction assignments.

Saved exact filters are not converted or broadened. Clear/reset removes the new
family/exact fields as well. Explicit prefix/wildcard modes expose a separate
pattern input; SAP User Group selections remain exact. All-page previews are
bounded to 5000 assignments and atomic submissions to 1000: narrow larger scopes
before confirming. No truncated set is silently applied.

New review periods capture the full assignment cut and catalogue naming evidence
privately. Current imports never replace that period's evidence. Older immutable
periods without a full assignment cut retain their original conflict evidence;
the full-population preview reports that limitation rather than using current
records. Non-active validity views are for inspection; decisions require active
reviewable evidence and an editable period.

In Access Explorer → Roles, **Review matching assignments** opens Bulk Review
with the effective role, suffix, user and group scope and selects the complete
matching set across pages. This includes assignments without a detected conflict.
The shortcut never records a decision; inspect the frozen preview and confirm
explicitly. Returning to Explorer preserves its filters.

The review queue, Dashboard review coverage, review-period progress, remediation
and reports use the same complete assignment population. An assignment with no
linked conflict activity can be approved, recommended for removal or investigated;
it has no invented activity or risk decision. Remediation labels these rows
**No linked SoD activity**. Conflict counts and formal risk acceptance remain
independent. Existing immutable periods without a complete assignment snapshot
continue to use their retained scope.


### Compact Bulk Review selection

The shared sidebar owns the scope. Recognized base-role families and exact suffixes
combine as before; legacy prefix/wildcard/search modes remain under **Advanced role
matching** without changing saved filters or Explorer handoff.

**Users** and **Assignments** count all current matches; **Eligible** counts those
that can change under the proposed decision and inclusion policy. These totals
are calculated server-side, before the bounded preview. Previously reviewed
assignments are hidden by default. **Include previously reviewed** reveals them
without selecting them; switching it off clears their selections. Unchanged
decisions remain non-executable.

The header checkbox selects eligible assignments on the current page, including
an indeterminate state. When additional pages exist, **Select all N matching
eligible assignments** selects the complete loaded eligible scope. Selections
survive pagination. Out-of-filter selections have a separate disclosure and clear
action; they never enter the operation. A truncated scope cannot be selected all
at once; narrow it for a complete preview.

Keep, Remove and Investigate change only the proposed decision. The table action
bar shows the executable selected count. **Preview** and **Review N assignments**
open the same frozen confirmation with current/proposed assignments, reviewer,
rationale, filters, period and source/review revisions. **Mark N role assignments
for removal** records a recommendation, never a SAP change. Reconsidering prior
decisions requires the additional replacement checkbox. Atomic validation, source
checks, period gates and per-assignment immutable history are unchanged.

## Remediation CSV exports

**Export CSV** on Remediation is a menu with two formats, both honoring every active Remediation filter (SAP User Group, username, risk, activity, assigned role, role suffix, transaction code, business area, assignment validity, recommended handling and tracking) across all pages, independent of expanded rows:

- **Role Assignments** (`sap-lens-sod-role-assignments-YYYY-MM-DD.csv`): columns `USERNAME;ROLE;SAP User Group;Decision Status`, one row per exact SAP username and assigned role, sorted by username then role. Several activities, risks or validity intervals of the same pair never add rows; display names and descriptions are not used to merge anything. Where one pair has several values the result is deterministic and visible: the SAP User Group is the distinct non-empty groups joined with `, ` (empty when none exists, never invented), and the Decision Status is the authoritative assignment decision when all intervals agree, otherwise `Mixed (A / B)` listing the distinct decisions. It reports the review decision only; remediation actions and verification stay in the detailed export.
- **Detailed Remediation** (`sap-lens-sod-access-remediation-YYYY-MM-DD.csv`): unchanged columns and activity-level rows for evidence and investigation.

Both use the established CSV conventions (semicolon delimiter, all fields quoted, UTF-8 with BOM, spreadsheet-formula protection).
