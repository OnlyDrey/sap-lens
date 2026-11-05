# CSV data lifecycle and refresh evidence

## Sources and compatibility

SAP Lens has four independent local CSV sources: Role Catalogue, User–Role Mapping, Employee Directory and the [SoD Matrix](SOD_MATRIX.md). Role catalogue and user assignments default to **Dynamic**, preserving the existing refresh behavior. Employee Directory and the SoD Matrix default to **Static**, retaining snapshots until explicit replacement. Older schema-3 settings receive these additive defaults without losing feature preferences, profiles or paths.

Settings → Data Sources offers a source mode selector. Use the existing **Apply settings** action to persist mode changes; no second Save action is needed. Changing a mode does not delete imported records. Existing CSV mappings, delimiter/encoding controls and validation remain authoritative.

- **Static:** selecting a replacement automatically validates and imports it. Global Refresh skips the CSV and continues using the private snapshot, even if the original file is unavailable.
- **Dynamic:** Global Refresh rereads the entire configured file. A daily export can overwrite that file; SAP Lens does not schedule or monitor exports. A complete valid replacement removes records absent from the incoming file.

Never point two sources at different interpretations of the same file without configuring their respective import formats.

## Preparation, publication and persistence

Parsing happens off the request thread. Each candidate is validated separately, and immutable content-addressed snapshot files are staged under `%LOCALAPPDATA%\SAP Lens\csv-data\snapshots\`. Employee Directory retains its existing content-addressed `employee-directory` format. SHA-256 verifies stored snapshot bytes before restoration; canonical observations are rebuilt through the existing catalogue/user processing, not deserialized executable objects.

The single atomic settings update contains snapshot references and bounded report references. A revision check rejects a competing settings/import operation. Only after that commit are the prepared cache generation and directory indexes activated. Readers keep the previous generation during preparation. Cancellation prevents the commit; no timed-out worker may later overwrite a newer generation.

A source read/validation/staging failure retains that source. Other independent sources can succeed. If catalogue data changes while user CSV reading fails, retained **raw validated user observations** are remapped against the new catalogue. This rebuilds wildcard/transaction indexes; old derived transaction claims are never mixed with a new catalogue. A transaction/storage failure before pointer commit activates none of the staged candidates.

Successful imports store full replacements, not email-based upserts. For example, replacing 1,310 directory rows with 1,295 leaves exactly 1,295 active records, with removed employees absent from email/manager indexes. Missing email remains a quality warning. Empty email keys are excluded from duplicate-email indexing.

Startup restores durable observations and initializes enabled dynamic sources. Failed live reads can retain restored data. Static sources restore without reopening the original CSV. A legacy, enabled directory that only has a readable path is validated and durably captured once at startup. An invalid/missing snapshot is reported; it is never silently accepted as valid data. Original source availability and durable snapshot availability are separate facts.

Immutable staged files are private application data, never build inputs. Old snapshot files are retained conservatively for local configuration-backup recovery; clearing a source removes its active reference. Do not manually delete snapshots referenced by a backup you intend to restore. Report retention is independent and bounded to five recent operations.

## Change identity and evidence

Logical records are compared independently of row order. Exact duplicate representations follow the existing importer's deduplication rules; distinct assignment intervals remain distinct evidence.

| Source | Stable grouping key | Important limitation |
|---|---|---|
| Catalogue | AGR_NAME, CHILD_AGR, PARENT_AGR, Effective_Role, TCODE | Multiple relationship observations are retained. |
| User assignments | Normalized USERNAME, exact-role identity, USER_GROUP | Exact intervals cancel first; multiple remaining observations are not arbitrarily paired. |
| Employees | DistinguishedName, otherwise SamAccountName | Email and display name are never universal record identifiers. |

Exact observations cancel as multisets. Only one remaining old/new record for a stable key is reported as modified. Ambiguous groups and records without usable identifiers remain additions/removals with an explicit identity limitation. Modified records retain field-level before/after values. Original display values remain available; normalization does not rewrite imported identity attributes.

Snapshots/reports have version-1 contracts and bounded input/storage sizes. A source changing during its read is rejected; retry after the external export finishes.

## Refresh results and history

The global refresh control is application-scoped and prevents concurrent repeated requests. Results appear at the top of the main content, not inside the navbar:

- Green: successful changes, with **View Changes**.
- Neutral: no changes, with no change-view action.
- Red: partial or complete failure, with **View Errors**, never View Changes.

Skipped static, disabled and unconfigured sources are counted separately. A partial failure does not turn successful independent updates into failures. Dismissing the banner does not remove its report.

Data Sources and Health & Diagnostics expose five recent private operation reports. Changes support source/type filters, search, bounded pages, copyable identifiers, expandable field evidence and CSV export. Export uses the selected change filters and escapes spreadsheet formula prefixes. Error views use safe categories and recovery advice without exposing exception text, private paths or CSV contents.

Reports contain personal data and stay local. Diagnostic exports contain only allowlisted aggregate status; they exclude report identities, record details, source paths and employee data. Normal logs never include imported record values. Older reports are removed by retention; corrupt/unavailable reports produce an explicit recovery state.

## Scheduled refresh

**Settings → Runtime & Scheduling** can run the same refresh automatically. The backend schedules it, so no browser tab has to be open, and every run is the normal refresh: Dynamic sources are re-read, Static sources are not, a changed source is validated before it replaces the previous one, and any failure keeps the previously validated data.

- **Schedule.** Enable it, then choose a daily time (HH:MM, 24-hour) or an advanced five-field cron expression (`minute hour day-of-month month day-of-week`; lists, ranges, steps and `JAN`/`MON` names; Sunday is 0 or 7; day-of-month and weekday are OR-ed like standard cron). Runs must be at least 5 minutes apart. The page explains the schedule in words and lists the next runs before you apply it.
- **Time zone.** Local time (the computer or server), UTC, or an IANA name such as Europe/Oslo. The pinned `tzdata` database ships with the runtime, including Windows packages, so named zones work without an operating-system IANA database. Daily time uses explicit 24-hour `HH:mm` entry regardless of browser/Windows AM/PM preferences. A local time skipped by a spring-forward change is skipped; a repeated hour runs once.
- **Safety.** One process owns the data store, so a schedule cannot run twice, and a scheduled run is skipped when another load or refresh is already running. A slot missed while the application was not running is skipped, never replayed; editing the schedule starts it fresh from that moment.
- **Status.** Next run, last attempted run, last successful run, last failure (and failures in a row) and the last outcome (succeeded, partly failed, failed, skipped) are shown in Settings and summarized, without paths, in the diagnostics export. Failure messages are generic; details stay in the refresh history.

| Deployment | When scheduled refresh runs |
| --- | --- |
| Windows Desktop | Only while SAP Lens is running, in its window or in the system tray |
| Windows Service | Continuously while the service runs; no sign-in or browser needed |
| Linux Docker | Continuously while the container runs |
| Linux native / systemd | Continuously while the unit runs |

## Feature dependencies

1. User–Role Mapping enables SAP assignment investigations.
2. Employee Directory independently enables local employee records.
3. SAP Identity Enrichment is derived from both enabled features with available data; it is not an extra preference to keep in sync.

Disabling either source feature preserves its preference-independent data and configuration. Employee Directory does not automatically switch off when mapping is disabled. Its local records remain usable, while SAP email enrichment/manager-to-SAP navigation is unavailable. Backend endpoints enforce dependencies; hiding UI controls is not the boundary. Re-enabling valid retained sources resumes operation without reimport.

The older `operational_status` directory API field remains a compatibility description of enrichment readiness. The explicit `directory_operational` and `enrichment` fields distinguish local directory availability from matching prerequisites.

## Employee import and preview

For all four sources, selecting a file automatically reads, validates, stages and
activates a complete non-empty dataset. There is no separate normal-flow Validate,
Confirm or Import action. **Browse / Upload file** (one label for every source) is always available,
also when a file is already configured; only an import in progress for that source
blocks it. It opens the native dialog in the desktop app, the upload chooser where browser
uploads are supported, and otherwise explains that native browsing is desktop-only and moves
to the file location field. A replacement that does not validate (invalid, empty or
unreadable) never replaces the configured file or its data: the attempted path stays in the field
for correction or column mapping, and the message says the active file is unchanged and names
it, while a valid replacement is confirmed by file name and counts.
Native Browse activates the selected server-visible file;
browser uploads activate a private Static source. Entering a path activates on Enter
or leaving the field. Selecting the same file again explicitly revalidates it.

Settings shows progress, committed record/change counts, source status and links to
View changes, Preview data and technical details. Preview inspects the current
validated snapshot without rereading the original CSV. For the **SoD Matrix** it is a read-only inspection: record, risk, activity and transaction counts, validation results (documented columns, required values, both activity sides, evaluated types, duplicates, missing descriptions, overlapping transactions), a column-interpretation table (the schema is fixed, so the meanings are explained; a mapping only chooses the source header), quality warnings, import metadata (file, mode, imported, checked, snapshot, feature state) and the imported records. Employee preview retains
search, sorting, paging and quality filters. Missing emails are warnings, not a
reason to discard otherwise valid records. Feature preferences are independent:
importing does not enable a disabled optional feature.

The previous dataset remains active while validation runs. Empty, unreadable,
malformed or changing files cannot replace it. Settings revision checks, source
signature checks and a single active load prevent conflicting publication. Source
files must remain stable until validation completes; select again after an export
finishes. Explicit Clear source data requires confirmation and never deletes the
original CSV. Opening Data Sources does not reimport configured files.

Mode/profile-only edits use Apply settings. Completed automatic imports persist
immediately and are not undone by Cancel settings; unrelated unsaved edits survive
source activation. Advanced mapping and optional parsing inspection remain available
for custom formats. The legacy preview/digest/import API contract remains supported
for existing callers; it is no longer the normal Settings workflow.

## Platform validation

Automated browser and backend tests use synthetic identities. Fresh-process snapshot restoration on Linux verifies persistence logic but does not prove Windows/WebView2, native file dialogs or UNC-share access. Run those checks on Windows before treating a new desktop distribution as validated. No new executable is built by these changes.

## SoD Matrix import format, mapping and validation

Settings → Data Sources → SoD Matrix has the same **Advanced import format and column mapping** section as the other CSV sources, in three steps: *CSV Import Format* (delimiter and encoding, both automatic by default; the documented columns RISK through TTEXT are a fixed schema), *Column mapping* (columns are matched by name; choose a source column only where a header differs, for example `Risk_ID` for RISK) and *Validation & preview* (counts, parser errors, SoD-specific checks and sample rows, in a table that scrolls inside its own container). The section inspects the selected file through `POST /api/data-sources/sod/inspect`, which parses it exactly as an import would but stores nothing: active data, risk definitions, decisions and review snapshots are never touched, and an invalid file never replaces the last valid dataset. The format and mapping are saved with the next import or **Apply settings** (`sod_import` in the configuration) and are used for static and dynamic refreshes. Browse / Upload file, Refresh source, Preview data, View changes, Technical source details and Clear source data are unchanged.


### Browser file uploads

In Settings → Data Sources, **Browse / Upload file** opens the browser's file picker
for Role Catalogue, User Access, Employee Directory and SoD Matrix CSVs. No server
filesystem path is required. Desktop WebView2 uses the same primary action with its native file dialog;
a browser connected to the desktop backend can also upload using its authenticated session.

The authenticated multipart request (`POST /api/server/uploads/{source}/activate`)
carries one CSV, the current settings revision and optional existing import profile.
It reuses the same source-selection, complete validation, atomic activation and snapshot
persistence service as desktop browsing. Only after activation succeeds does the shared
application-data owner refresh dependent views and show record/change counts. Active
filename, import timestamps and snapshot metadata remain available beside the source controls.

Limits are 50 MiB for Employee Directory and 128 MiB for other CSV sources, with bounded
multipart overhead and form fields. Empty files, invalid names/types/schemas, interrupted
uploads, stale revisions and concurrent replacements are rejected without replacing valid
data. Failed staged files and multipart temporary files are cleaned up. Files use generated
private names and Static mode; Global Refresh never rereads a client device. Optional
administrator-managed Dynamic paths remain under Advanced server source path and follow
server source-root permissions. Existing raw staging endpoints remain compatible with
packaging tools, but the UI uses multipart activation, not the legacy staging/confirmation flow.


There is one primary **Browse / Upload file** action per Data Sources tab. Native desktop
uses its file dialog; browser sessions use the authenticated multipart uploader. The optional
**Advanced server source path** contains only the path input, with no second Browse action.
Uploaded replacements explicitly use Static mode (shown beside the action and in completion
feedback/source mode); administrator-selected paths retain the chosen Static/Dynamic mode.
Global/manual/scheduled refresh behavior, inspection and failure recovery are unchanged.

## Source-specific refresh and the unchanged fast path

Start-up (Dynamic sources) and every refresh evaluate each source on its own:

1. **Fingerprint.** For Role Catalogue, User-Role Mapping and SoD Matrix the file content digest is combined with the parsing settings (active import profile or SoD format) and the digest of the
   parser code. The fingerprint of the input that produced the active revision is stored with that revision in the SQLite store.
2. **Unchanged:** an equal fingerprint, the same path and a loaded active revision mean parsing would reproduce the active snapshot exactly. The source is reported `unchanged` (marked `fast_path`) and is
   neither parsed, compared, anomaly-checked, snapshotted nor rebuilt; its `checked_at` is updated. The file is still read once to hash it; the content is never trusted by timestamp or size alone.
3. **Changed:** only that source takes the full path (parse, validate, compare with the previous approved revision of the same source, anomaly check, snapshot). Users are re-mapped against the
   catalogue **once**: when the users file is re-read they are already mapped to the final catalogue; when only the catalogue changed, the unchanged users are re-mapped without reading their file.
4. **Unknown fingerprint** (first start after an upgrade, store missing or rebuilt, different parser) simply takes the full path once and then records the fingerprint.

Activation stays atomic. The new snapshot is written (immutable), its rows are *staged* in the store (invisible to readers), the configuration pointer is committed with the existing compare-and-swap, and
only then are the staged revisions activated (one short transaction per source). Each load is a staging *operation* with its own identifier; staged revisions are owned by it. If the commit does not happen, or the load fails or is cancelled, only that operation's staged revisions are discarded (a snapshot two overlapping loaders both staged is handed to the remaining one, never deleted under it). Revisions left by a process that died are orphans: they are removed at start-up and, while running, when older than an hour and not owned by a live operation. Activation clears ownership. In memory the published dataset is replaced as one object.
Snapshot integrity is verified on every start (SHA-256 of the snapshot file against its content address) even when the records come from the store or the derived cache.

## Import checks: suspicious versus invalid

Every replacement source is compared with the **active revision of the same source** (roles, users, employees or SoD) and with nothing else: not another source, not an
unactivated or held file. A first import has nothing to compare and is never held.

| Outcome | Meaning | What happens |
| --- | --- | --- |
| Invalid | Structurally unusable: no records, wrong headers, bad dates, unreadable | Rejected. Cannot be confirmed. `severity: invalid`, `confirmable: false`. |
| Suspicious | Valid, but a sharp reduction against the active revision | Parsed and reported, **not activated**. Needs explicit confirmation. `category: needs_confirmation`, `severity: suspicious`. |
| Normal | Anything else | Activated atomically as before. |

Rules (Settings > Data Sources > Import checks; defaults 30 % and 20 records, changes apply with Apply settings):

- **Reduction:** records or a distinct-entity count falls by more than the limit. Entities per source: roles - catalogue entries and transactions; users - SAP users and assigned roles;
  employees - directory accounts; SoD - risks.
- **Missing group:** every record of an organizational group (user group, module area or department) disappears and that group held at least 5 records and 1 % of the previous source.
- Active sources smaller than the minimum are never held, and the checks can be switched off. The limit is between 1 % and 95 %.

A held import keeps the active data, settings revision and snapshots untouched. The API answers `409` with `code: import_needs_confirmation`, the triggered checks and the old and new counts; the
Settings dialog shows the same report. Importing again with confirmation (`confirm_anomalies`, upload form field of the same name) activates it through the normal atomic path and appends an entry
(source, time, actor, triggered checks, old and new record counts; last 100) to `data_lifecycle.confirmations`. A scheduled or startup refresh that finds a suspicious file reports the source as
failed with `previous_preserved: true` and never activates it.
