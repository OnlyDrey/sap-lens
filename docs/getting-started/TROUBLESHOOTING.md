# Troubleshooting

Symptoms, likely causes and the first thing to try. Each answer points to the guide that owns the detail. The messages are quoted from the application.
If a problem persists, export the sanitized report from **Settings → Health & Diagnostics** (it omits paths, SAP values and capabilities) before asking for help.

## Startup

| Symptom | Likely cause | What to do |
|---|---|---|
| The window stays on "Starting backend…" or "Connecting to local service…" | The local service has not finished starting, or its port is taken. Desktop prefers port 18743 and falls back to a free port by itself. | Wait a moment; if it does not change, close and reopen SAP Lens. Do not start two copies of one data directory. See [desktop connectivity](../architecture/DESKTOP.md). |
| "Unable to connect to the local service" with **Retry connection** | The service stopped or was blocked. Your saved configuration is retained. | Select Retry connection; if it repeats, close and reopen SAP Lens. |
| "Choose a SAP role catalogue or user access CSV in Settings." | No source is configured yet (or the configured file was cleared). | Settings → Data Sources: choose a CSV for each source ([Quick start](QUICK_START.md)). |
| Server mode does not start | A boundary check failed: loopback binding, HTTPS origin, allowed hosts, authentication secret (32 to 256 non-whitespace ASCII characters, not readable by other users), data directory outside the application files. | Read the startup log message and the [deployment security guide](../deployment/SECURITY.md). |

## Data and imports

| Symptom | Likely cause | What to do |
|---|---|---|
| "Failed — … No source data was replaced." | The new file did not validate. The last valid data stays active. | Open Settings → Data Sources → the source → **Advanced import format and column mapping**: the inspection lists the errors and the columns. Fix the file or the mapping, then select it again. Nothing is lost. |
| "The CSV changed while being read. Wait for its export to finish and retry; previous data is retained." | The export was still writing. | Wait for the export to finish and refresh the source. |
| "The CSV contains no usable records." | The file is empty or has only a header. | Use a complete export. To remove a dataset on purpose, use **Clear source data**. |
| A dynamic source does not update | The source is Static, the feature is disabled, or the scheduler is off. | Check the source mode in Data Sources and Runtime & Scheduling; use **Refresh source** to force a check. See [import and refresh](../data/IMPORT_AND_REFRESH.md). |
| SoD is missing from the navigation | SoD is a manual feature and is off until enabled. | Settings → Features. It also needs User–Role Mapping data ([SoD](../features/SOD.md)). |
| Descriptions are missing on risk or activity pills | The SoD CSV has no descriptive columns and no local text exists. | Add local business text in Settings → SoD Risk Configuration, or import a CSV with the optional columns ([SoD matrix](../data/SOD_MATRIX.md#optional-descriptive-columns)). Metadata coverage is shown under Data Sources → SoD Matrix → Preview data. |
| "Settings changed. Reload before applying your edits." (409) | Another window or an import changed the settings after you opened them. | Reload Settings and apply your edit again. |

## Access to the server

| Message | Meaning | What to do |
|---|---|---|
| "Server access is not authorized." (401) | Missing or wrong credentials, or the proxy headers are incomplete. | Use the shared username and secret (Basic) or the configured proxy path. |
| "Origin is not allowed." / "Desktop access requires its exact loopback listener." (403) | The page was opened from another origin or host than the configured one. | Open SAP Lens through the configured public origin and an allowed host. |
| "Application request is not authorized." (403) | An API address was opened directly without the application session. | Open the application itself; API addresses are not meant for direct browsing. |

## Recovery

Backups and restores are documented per deployment: [Windows desktop](../deployment/WINDOWS_DESKTOP.md#data-and-upgrades),
[Windows service](../deployment/WINDOWS_SERVICE.md#upgrade-backup-and-removal), [Linux native](../deployment/LINUX_NATIVE.md) and
[Linux Docker](../deployment/LINUX_DOCKER.md). Restore never overwrites an existing data store; restore into an empty directory, review permissions and
only then start the application. Settings, review decisions, snapshots and history are private local data and belong in a protected backup, never in Git.
For settings, logs and storage locations see [configuration and recovery](CONFIGURATION.md).
