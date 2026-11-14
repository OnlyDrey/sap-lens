# Troubleshooting

Symptoms, likely causes and the first thing to try. Each answer points to the guide that owns the detail. The messages are quoted from the application.
If a problem persists, export the sanitized report from **Settings → Health & Diagnostics** (it omits paths, SAP values and capabilities) before asking for help.

## Startup

| Symptom | Likely cause | What to do |
|---|---|---|
| The window stays on "Starting backend…" or "Connecting to local service…" | The local service has not finished starting, or its port is taken. Desktop prefers port 18743 and falls back to a free port by itself. | Wait for the bounded startup check. On failure, use the displayed code and Log location, then Retry startup if offered. If shutdown is incomplete, fully exit (including the tray) before relaunching. Do not start two copies of one data directory. See [desktop recovery](../architecture/DESKTOP.md#readiness-diagnostics-and-controlled-recovery). |
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

## Build setup: pip certificate errors

`CERTIFICATE_VERIFY_FAILED` while installing Python packages almost always means the project environment was seeded with pip 24.0, which does not use the Windows certificate store. Run the official entry point again (`.\scripts\build.ps1 -Mode test`): it upgrades pip to the pinned release, retrying once with the system trust store, and then installs the locked dependencies. If it still fails, your proxy's CA is not trusted by Windows: ask IT to install it in the certificate store. SAP Lens never disables verification or uses `--trusted-host`. Other build prerequisites are listed in the [prerequisite matrix](../BUILD.md#prerequisite-matrix).

## Session disconnected

**Session disconnected** means this window holds a local session from an earlier start of SAP Lens (for example after a restart while the window stayed open). Choose **Reconnect session**; your view and filters are kept. If you typed into a form, SAP Lens asks before reloading because that text is lost. **Connection lost** means the local service is not answering: wait a moment and choose **Retry connection**. If the notice returns after a normal start, close other SAP Lens windows, restart SAP Lens and open **Technical details** for the state and category. Nothing is saved or resubmitted automatically.

## Connection lost

**Connection lost** means SAP Lens could not reach its local service (a request got no response). It is shown once at the top of the
window, separate from application errors (which name the failed action) and from **Session disconnected**. Data on screen may be out of
date until the service answers. The notice clears by itself when background reads succeed again; **Retry connection** tries at once.

A write that was interrupted is reported as failed in the form that sent it, never as saved. The form stays open with what you typed,
and nothing is sent again automatically: check the result, then submit again yourself. Reconnecting a stale session asks before it
reloads if a form holds typed text.

## Recovery

Backups and restores are documented per deployment: [Windows desktop](../deployment/WINDOWS_DESKTOP.md#data-and-upgrades),
[Windows service](../deployment/WINDOWS_SERVICE.md#upgrade-backup-and-removal), [Linux native](../deployment/LINUX_NATIVE.md) and
[Linux Docker](../deployment/LINUX_DOCKER.md). Restore never overwrites an existing data store; restore into an empty directory, review permissions and
only then start the application. Settings, review decisions, snapshots and history are private local data and belong in a protected backup, never in Git.
For settings, logs and storage locations see [configuration and recovery](CONFIGURATION.md).

## SAP Lens shows "Restoring workspace…" or a recovery screen at start

After a restart SAP Lens re-establishes its local session by itself; you should only see "Starting SAP Lens…", "Connecting to local service…" or "Restoring workspace…" for a moment. A recovery screen appears only when that failed: *Retry connection* repeats the attempt.
If it keeps appearing, close all SAP Lens windows and browser tabs that point at it, then start SAP Lens again. Details of the cause classes are in [Local session lifecycle](../architecture/SECURITY.md#local-session-lifecycle-and-start-up-recovery). Backup & Restore is offered only when the configuration itself could not be loaded.

## Build prerequisite download blocked

`workflow_lint BLOCKED (prerequisite)` or `managed_tools BLOCKED` means a tool
was not verified, not that application tests failed. Resolve prerequisites
before another package build. A persistent HTTP 403 needs approved upstream
access, an internal mirror or a checksum-verified local artifact; repeated
rebuilds and a different User-Agent do not override policy. See
[build prerequisite recovery](../BUILD.md#centralized-prerequisites-and-restricted-networks)
for exact commands, environment variables and cache/version diagnostics.
