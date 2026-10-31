# Quick Start

## 1. Choose how to run

- Windows workstation: [Windows Desktop](../deployment/WINDOWS_DESKTOP.md), native WebView2 and local dialogs.
- Shared Windows host: [Windows Service](../deployment/WINDOWS_SERVICE.md), headless WinSW/SCM and browser access.
- Linux container host: [Docker](../deployment/LINUX_DOCKER.md), persistent volume and browser access.
- Linux server/workstation: [Linux Native](../deployment/LINUX_NATIVE.md), Python 3.12 with systemd or a manual browser process.
- Developer: [run from source without an EXE](../development/DEVELOPMENT.md).

Obtain artifacts from an authorized successful build or build them using the
[central build guide](../deployment/BUILD.md). No pre-existing download is implied.
Linux clients use a browser; no separate Linux GUI executable is supplied.

## 2. Configure safely

Keep mutable data separate from installed binaries. Defaults are loopback-only;
read [server security](../deployment/SECURITY.md) before remote access. The platform
guide explains startup, storage, logs and lifecycle commands. See
[Configuration](CONFIGURATION.md) for application preferences and recovery.

## 3. Load sources

Open Settings → Data Sources. Role Catalogue supplies roles/transactions;
User–Role Mapping supplies users/assignments. Employee Directory is optional
identity enrichment. Follow [import and refresh](../data/IMPORT_AND_REFRESH.md),
select a file to validate and import automatically; invalid or empty files retain previous data. Start with
[synthetic examples](../../examples/README.md) when exploring; never commit real exports.

Enable optional capabilities under Settings → Features and Apply settings.
Selection alone is not success: wait for Completed and the committed record count. A missing optional
source does not prevent the application from starting.

## 4. Investigate

Start at [Dashboard](../features/DASHBOARD.md), then
[Role Lookup](../features/ROLE_LOOKUP.md) or [User Access](../features/USER_ACCESS.md).
Role-derived transaction mappings are investigation evidence, not proof of
effective SAP authorization. [Data Health](../data/DATA_HEALTH.md) explains coverage gaps.

If something does not behave as expected, see [Troubleshooting](TROUBLESHOOTING.md).
