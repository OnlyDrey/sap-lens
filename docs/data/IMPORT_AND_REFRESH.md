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
- **Time zone.** Local time (the computer or server), UTC, or an IANA name such as Europe/Oslo when the operating system has the time zone database (Windows Desktop may offer only Local time and UTC). A local time skipped by a spring-forward change is skipped; a repeated hour runs once.
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
Confirm or Import action. **Browse CSV** (one label for every source) is always available,
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

Settings → Data Sources → SoD Matrix has the same **Advanced import format and column mapping** section as the other CSV sources, in three steps: *CSV Import Format* (delimiter and encoding, both automatic by default; the documented columns RISK through TTEXT are a fixed schema), *Column mapping* (columns are matched by name; choose a source column only where a header differs, for example `Risk_ID` for RISK) and *Validation & preview* (counts, parser errors, SoD-specific checks and sample rows, in a table that scrolls inside its own container). The section inspects the selected file through `POST /api/data-sources/sod/inspect`, which parses it exactly as an import would but stores nothing: active data, risk definitions, decisions and review snapshots are never touched, and an invalid file never replaces the last valid dataset. The format and mapping are saved with the next import or **Apply settings** (`sod_import` in the configuration) and are used for static and dynamic refreshes. Browse CSV, Refresh source, Preview data, View changes, Technical source details and Clear source data are unchanged.
