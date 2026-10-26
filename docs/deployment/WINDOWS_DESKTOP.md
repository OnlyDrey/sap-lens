# Windows Desktop installation and upgrades

## Status and supported target

The deployment package has an Inno Setup installer definition and native acceptance
script. **Installer compilation and native installation have not been executed in
the Linux development environment.** Download availability depends on a successful
approved Windows packaging run; the presence of these scripts is not a claim that
an installer has already been published. The separate legacy Windows release
workflow still produces its existing portable EXE distribution.

Target: Windows 10/11 x64 with Microsoft Edge WebView2 Evergreen Runtime
86.0.622.0 or newer. Install prerequisites through your approved IT process.
No Python, Node.js, compiler or Windows Service is required on the destination.
Setup checks WebView2 and stops with guidance if unavailable; it does not silently
download software or bypass enterprise controls. The application remains unsigned.

## Obtain and verify the package

Build `Windows Desktop` or `All` with **Build Deployment Packages** after approval,
or use the documented [local build](BUILD.md). The output is:

`SAP-Lens-Windows-Desktop-x64-<version>.zip` and its SHA-256 sidecar.

After extracting GitHub's download wrapper, verify that sidecar before opening
the inner ZIP. It contains:

- The existing portable `SAP-Lens.exe` and checksum.
- `SAP-Lens-Windows-Desktop-x64-<version>-Setup.exe` and checksum.
- Application and Inno Setup licenses, this guide, exact package manifest and
  native installer validation report.

Use a trusted distribution source. An unsigned package plus its own checksum
provides integrity, not an independently authenticated publisher identity.

## Install

Close all SAP Lens windows. Run the Setup executable and follow the wizard.
Installation is per user, defaults to `%LOCALAPPDATA%\Programs\SAP Lens`, creates
an Installed Apps entry and Start Menu shortcut, and offers an optional desktop
shortcut. The program is a windowed application and does not require a terminal.
Administrator privileges are not required for normal installation.

Unattended example, replacing the filename with the actual verified version:

```powershell
$setup = Start-Process '.\SAP-Lens-Windows-Desktop-x64-0.1.0-beta.1-Setup.exe' `
  -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -Wait -PassThru
if ($setup.ExitCode -ne 0) { throw 'SAP Lens installation failed; inspect the setup log.' }
```

Inno Setup supports `/DIR="C:\Users\<user>\Applications\SAP Lens"` and `/LOG="..."`.
Use a dedicated writable installation directory; Setup refuses an unmanaged
existing executable rather than overwriting a portable copy. Installed program
files and mutable data must remain separate. No end-user license agreement or
new permission grant is introduced by the wizard; the proprietary notice remains
in `LICENSE.md`.

## Data and upgrades

Application data remains under `%LOCALAPPDATA%\SAP Lens`, or the existing absolute
`SAP_LENS_CONFIG_DIR` override. That includes settings, CSV snapshots, saved
filters, review decisions and source metadata. The installer does not change
source modes, role interpretation or imports.

Run the new verified Setup executable over the registered installation. Setup
rejects a downgrade and creates a private stopped-state backup before replacing
application files. Close all sessions first; the existing application mutex and
storage lease protect maintenance. Setup never force-terminates SAP Lens.

Backups default to `%LOCALAPPDATA%\SAP Lens Backups`; an explicit absolute
`SAP_LENS_BACKUP_DIR` environment override selects another private location.
These archives may contain personal data/configuration. Keep them outside Git and
distribution packages. Windows ACLs protect the archive; external CSV paths are
not followed. Back up external Dynamic exports separately when required.

For a former portable installation without an Installed Apps version record, the
backup is labeled with the creating runtime's version. It does not guess the old
portable version. This deliberately prevents restoring it with older software
without a reviewed recovery procedure. An unknown data-directory layout or failed
backup stops Setup rather than risking silent data loss.

Keep backups until the new version starts, reads its sources and preserves saved
state. Binary replacement alone does not reverse a future storage migration.
For recovery, use the verified portable executable's local maintenance command to
restore a compatible archive into **empty** destinations; see
[backup/recovery semantics](../archive/validation/INSTALLATION_LIFECYCLE_VALIDATION.md). Review paths and
permissions before selecting restored data. Do not extract a backup over a live
store or delete the prior valid data as a shortcut.

For a desktop backup, after retaining/renaming the original store and closing the
application, restore into an empty directory with the verified portable EXE:

```powershell
$restore = Start-Process '.\SAP-Lens.exe' -ArgumentList @(
  '--maintenance','restore','--mode','desktop',
  '--archive','"D:\PrivateBackups\SAP-Lens-example.tar.gz"',
  '--data','"C:\Recovery\SAP Lens"','--confirm-restore',
  '--report','"C:\Recovery\restore-report.json"'
) -Wait -PassThru
if ($restore.ExitCode -ne 0) { throw 'Restore refused; inspect the safe report.' }
```

Selecting that recovery directory requires the existing `SAP_LENS_CONFIG_DIR`
override; otherwise restore into the empty original configured path after moving
its old contents aside. Keep the old store and backup until runtime/data checks
pass. The report's parent directory must already exist and remain private.

## Uninstall and explicit private-data removal

Use **Windows Settings → Apps → Installed Apps → SAP Lens → Uninstall**, or the
installation's `unins000.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`.
Uninstall removes managed program files, shortcuts and registration. It preserves
application data, imported snapshots, external CSVs and private backups.

For intentional private-data removal, first uninstall/close the application and
take a backup. The verified **portable** executable remains available in the
deployment package and supports a separate, explicit command:

```powershell
$data = Join-Path $env:LOCALAPPDATA 'SAP Lens' # Use the actual configured data root.
$report = Join-Path $env:TEMP 'SAP-Lens-data-removal.json'
$cleanup = Start-Process '.\SAP-Lens.exe' -ArgumentList @(
  '--maintenance','purge','--mode','desktop','--data',('"'+$data+'"'),
  '--confirm-purge','--report',('"'+$report+'"')
) -Wait -PassThru
if ($cleanup.ExitCode -ne 0) { throw 'Data removal refused; inspect the safe report and application locks.' }
Get-Content $report
```

This command requires recognized deployment ownership, rejects links and active
storage locks, and removes private files only after explicit confirmation. It
retains the nonprivate runtime lock stub/directory to avoid a race with new process
startup. External sources and backups are never followed or deleted. Legacy data
without a recognized deployment marker requires explicit migration/review first.
There is no HTTP endpoint for backup, restore or purge.

## Build prerequisites and verification boundary

The installer wraps the canonically compiled/verified EXE; it does not introduce
another application build. The build script provisions SHA-256-pinned Inno Setup
7.1.0 under ignored `backend/build/inno-setup-7.1.0`, verifies the compiler after
provisioning and retains the vendor license. Tool provisioning may register its
per-user build-tool installation; it does not alter Python/Node installations.
Do not delete its tool receipt or bypass a changed-compiler error blindly.

The deployment pipeline keeps the canonical portable verifier's exactly-two-file
ZIP rules. Its outer deployment ZIP adds an explicit manifest and installer assets;
after download, it rechecks exact contents, hashes, identity, unsigned installer
resources and the canonical portable payload. The native acceptance definition
refuses an existing registered installation and uses isolated data to test install,
repeat installation, installed-EXE lifecycle, uninstall and data preservation.

Pending manual acceptance includes actual Windows compiler/setup execution,
previous-version upgrades, clean-PC/IT-policy behavior, WebView2, Explorer/file
and Save dialogs, high DPI, restart/recovery and UNC sources. Linux unit/static
checks are not equivalent to these tests.
