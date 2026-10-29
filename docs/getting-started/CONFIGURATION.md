# Configuration and recovery

Settings groups existing configuration by purpose; saved settings, import presets,
module preferences and theme colors retain their existing schema and behavior.

| Category | Section | Responsibility |
| --- | --- | --- |
| General | Organization & SAP System | Organization identity and SAP system/client description |
| General | Appearance & Branding | Themes, colors, local logo and appearance |
| Data & Modules | Data Sources | Role Catalogue, User Access, Employee Directory; mappings, validation, imports and recovery |
| Data & Modules | SAP Modules | Module search, enabled areas, labels, icons and colors used throughout the application |
| Application | Features | Optional capabilities and account-review group classification |
| Application | Health & Diagnostics | Backend/storage status, refresh history, actionable recovery and safe export |
| Application | Runtime & Scheduling | Scheduled refresh; Windows Desktop tray and sign-in options (Windows Desktop only) |
| Application | About SAP Lens | Version, build and runtime information |

Employee Directory remains a Data Sources subsection, not another top-level page.
CSV paths never live in Features. The existing Apply/cancel mechanism saves ordinary
settings. Automatic source import, durable-snapshot recovery and review decisions are
explicit operations with their own confirmation/feedback, not duplicate generic
Save buttons.

Use Up/Down/Home/End to traverse the sidebar in its displayed order. The selected
section has a matching panel and visible keyboard focus. Dashboard/source-recovery
links open the relevant Data Sources subsection directly.

Employee Directory is an optional third CSV source; see [Employee Directory](../data/EMPLOYEE_DIRECTORY.md). Defaults describe one dataset/system; no multi-system infrastructure is introduced.

Organization name, platform (S/4HANA, ECC or Other/Custom), system ID, client, description and footer are editable. The configured organization name is the primary header heading; an empty name uses SAP Lens. Windows and repository branding remain SAP Lens. Module display overrides preserve stable SAP area IDs; custom business-domain configuration has been retired. Theme supports System, Light and Dark, defaults to Dark, and persists independent color palettes and custom presets. See [desktop workspace and theme colors](../architecture/APPEARANCE.md).

## Features and colors

Features lists User–Role Mapping, Employee Directory and Segregation of Duties in the same order as the Data Sources tabs; each card shows the **Enabled** switch above its **Configure source** action, both aligned to the right edge of the card. SoD risk and activity colors use the same hexadecimal input as module colors, with validation, a preview and Reset.

## Storage and upgrades

Schema version 3 settings live at `%LOCALAPPDATA%/SAP Lens/settings.json` on Windows, or `$XDG_CONFIG_HOME/sap-lens` / `~/.config/sap-lens` on Linux. They survive moving/upgrading the EXE. `SAP_LENS_CONFIG_DIR` can override this with an absolute path. `DATA_CSV_PATH` bootstraps an initial path only; saved settings take precedence. Environment variables override `backend/.env` bootstrap values. Neither is needed for normal desktop use.

Desktop binds exclusively to `127.0.0.1`, preferring 18743 with an OS-assigned fallback. Desktop CORS is the actual origin. Source-only `CORS_ORIGINS` defaults to `http://127.0.0.1:18743` and `http://localhost:18743`; HTTP loopback origins only, no wildcard. Restart development after changing bootstrap variables.

Settings are validated, revision checked and atomically replaced. Concurrent stale edits receive 409. Analysis-affecting changes build a complete new graph before settings/cache publication; metadata-only edits avoid rereading CSV. Profile content edits increase their versions. Migration from the previous path-only format makes an exact-byte backup first. Unknown, malformed or future-schema files remain untouched until an explicit recovery save/reset; a notice explains fallback defaults. Before-save backups are under `configuration-backups/`. Keep private backups secure; retention is user-managed and they can grow.

## Branding and portability

Choose PNG, JPEG or WebP up to 2 MB and 4096 pixels per side. SVG and animated images are rejected. Decoded pixels are resized to at most 1024 per side, stripped of metadata and reencoded as PNG in the private `branding/` directory. Moving/deleting the original does not affect the saved image. Missing/invalid copied images fall back to SAP Lens. Replace, remove or restore the default in Appearance & Branding. Retained assets/backups permit recovery and are not automatically erased by reset.

Export defaults to a redacted portable `.sap-lens.json` package. Including private organization details, import formats, inactive legacy configuration, mappings, module overrides, unlicensed-group classification and the logo requires the explicit private export option. Both modes include theme colors/custom preset names and exclude CSV paths and records, session capabilities and runtime state. Review private packages before sharing. Import validates the package/version/logo and preserves all three local CSV paths; it never trusts an embedded source path. Reset restores generic defaults after confirmation. Desktop export uses a native Save dialog; browser development downloads JSON. Open configuration folder is a guarded Windows native action.

Logs rotate at 2 MB with two backups, contain safe stages/counts and omit source paths, SAP values and capabilities. `runtime.json` contains only process/origin/instance diagnostics and is removed on normal exit. A stale record cannot authorize a connection. Settings, assets and backups use normal per-user filesystem protection, not encryption.

See [CSV import](../data/CSV_SCHEMAS.md), [classification](../data/CLASSIFICATION.md) and [privacy](../architecture/PRIVACY.md).

The removed frontend environment template was unused: no VITE_API_URL setting exists. Browser requests are same-origin and development uses the Vite proxy. Keep local data paths in application settings; backend/.env.example documents optional bootstrap variables only.

Role catalogue and User Access have separate CSV Import Formats and local paths. Custom presets support create, rename, duplicate and confirmed deletion; the active source falls back to its protected default. Legacy classification is archived without execution or destructive rewrite. See [access investigation](../features/USER_ACCESS.md).


## Compact health information

Health & Diagnostics shows service status, last successful refresh and whether
application storage exists. **Data source health** shows one card per source: the source icon and name with an Enabled/Disabled badge at the far right, the load status, record count and last import, and a **Review source** action that opens the source tab. Source mode, snapshot availability, the last validated check and file availability are under the card's expandable **Technical details**, together with the locations and diagnostics dialog; a failed refresh is stated on the card. Expand **Health details and refresh history** for
source counts, configuration versions and last failed refresh in this process.
**Source locations and storage details** reveals local paths privately in the
application. **Employee Directory technical details** explains its optional source,
storage and dependency states. Disabled optional sources do not fail core health.
Import history and detailed data quality belong to Data Sources.

A storage directory existing is not a claim that every future write will succeed.
Import/annotation writes report actual failures and retain prior accepted data.
Last failed refresh is session history; it is not invented from old successful data.
Native logs are still available through the existing controlled desktop action.

## “No durable records saved”

A legacy path-only configuration may load and validate records in memory without
having completed a successful source import. A path is not a durable dataset. It can work
until a restart/share disconnect makes that path unreadable.

Open **Data Sources → Employee Directory**:

1. If validated records are currently available, **Save durable directory snapshot**
   saves them to existing private snapshot storage without rereading the CSV.
   Unrelated draft edits are preserved. It verifies the directory digest and
   current settings revision, then stages the snapshot and atomically saves its ID.
2. Otherwise select a readable CSV and wait for automatic validation/import to complete.
3. Check **Durable snapshot available**. The import timestamp is retained. A successful
   durable import/restoration no longer needs the original CSV at startup.

Recovery never guesses records from a missing path. Failed writes retain the prior
configuration and validated in-memory data. Restart and missing-source recovery
are covered by backend tests using cleared configuration/directory caches; browser
reload also checks status synchronization. Actual Windows/WebView2 and UNC testing
still requires native validation; these tests do not establish share availability.

## Safe diagnostic export

Diagnostic JSON contains allowlisted versions, status, counts and refresh times.
It excludes CSV paths/contents, organization/employee identities, review annotations
and SoD decisions, periods and remediation actions, credentials and routine logs. Full source paths appear only in the protected local
UI. Account Review CSV export is a separate explicit export containing identity
and review information; do not confuse it with the redacted support report.

See [Employee Directory](../data/EMPLOYEE_DIRECTORY.md), [Account Review](../features/ACCOUNT_REVIEW.md),
and [local Windows testing](../deployment/BUILD.md).

## Investigation filter storage and data coverage

[Saved Filters](../features/SAVED_FILTERS.md) stores bounded investigation controls in the private per-user application settings directory, independently of imported source data and portable settings. [Data Health & Coverage](../data/DATA_HEALTH.md) is a collapsible overview under Data Sources; source-specific import, snapshot recovery and directory diagnostics remain in their existing source tabs.

## Component Library

Settings → APPLICATION → Component Library contains interactive previews of the real shared controls, navigation, tables and SAP status components. Previews use synthetic identities and isolated memory, including saved-filter management, and cannot alter imports or persisted settings. See [Component Library](../architecture/COMPONENTS.md) and the [design system](../architecture/DESIGN_SYSTEM.md).

## CSV modes and retained refresh evidence

Each source can be Static (manual replacement) or Dynamic (Global Refresh rereads its configured path). Role/user sources default to Dynamic; Employee Directory defaults to Static. Validated observations now have durable local snapshots, separate from original CSV availability. See [CSV data lifecycle](../data/IMPORT_AND_REFRESH.md) for replacement semantics, recovery, feature dependencies, preview and private change/error reports.

## Scheduled refresh and runtime


**Settings → Runtime & Scheduling** holds the scheduled refresh and, in the Windows Desktop application only, the tray options. The schedule is saved in the `refresh_schedule` object of the settings (`enabled`, `mode` daily or cron, `time` HH:MM, `cron`, `timezone`) with the normal Apply/Cancel and revision checks; its run history is kept separately in `refresh-schedule.json` so refreshes never change the settings revision. See [Scheduled refresh](../data/IMPORT_AND_REFRESH.md#scheduled-refresh).

Windows Desktop background preferences are under **Settings → Runtime & Scheduling → Windows
Desktop** (marked with a four-pane window icon), visible only through the native Windows capability. The local `desktop`
object contains `close_to_tray`, `run_at_signin` and `start_minimized`, all defaulting
to false. Start minimized requires tray mode. Ordinary Apply/Cancel and revision
checks apply; portable packages do not activate another machine's sign-in startup.
See [tray operation](../deployment/WINDOWS_DESKTOP.md#optional-system-tray-operation).

Appearance & Branding previews draft organization/system details and the same draft
logo in both live and local previews. The six palette colors (including Secondary Color) are
editable controls in a responsive grid (five columns in a wide settings area, three or two on
smaller ones, one on a phone), each with the native picker, HEX field and Reset. Apply/Cancel
retain their existing persistence behavior.

## SoD review data

SoD decisions, review periods, remediation actions, the report log and their immutable
snapshots are private application data (see [SoD architecture](../architecture/SOD.md#stores-private-atomically-written-backed-up-with-the-application-data)).
They are not part of portable configuration or diagnostic exports. Include them in private
backups; restoring only part of them can leave a period snapshot or retained decision
evidence unavailable, which SAP Lens reports instead of silently changing history.
