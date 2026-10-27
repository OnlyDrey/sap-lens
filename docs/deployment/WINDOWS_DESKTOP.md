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

## Optional system tray operation

In the native Windows application, open **Settings → About SAP Lens → Windows Desktop**.
Enable **Minimize to System Tray on Close**, then **Apply settings**. Defaults remain
off: ordinary close still stops the owned backend. When enabled, X hides the window
only after the backend and notification icon are ready. Double-click the SAP Lens
tray icon, or choose **Open SAP Lens**, to restore the same window/backend.

The tray menu provides Open SAP Lens, Open Web Interface, Refresh Data Sources,
Settings and Exit SAP Lens. Web Interface opens the actual selected loopback origin
(including a fallback port), using the existing guarded browser handoff. Refresh
uses the normal authenticated, validated full-replacement workflow. Status text
shows startup, readiness, refresh failure or backend unavailability; web/refresh
actions are unavailable when the backend is down. **Exit SAP Lens** performs normal
graceful backend/socket/storage-lease cleanup. A hidden instance still owns the
single-instance mutex: launching the EXE again restores it rather than starting
another backend. Exit before upgrading or uninstalling.

**Start SAP Lens at Windows sign-in** is optional and supported by the packaged EXE.
It creates only the current user's `SAPLensDesktop` value under
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`; no administrator or password
is needed. Paths with spaces/Unicode are quoted. **Start minimized to the system
tray** requires tray mode. These machine/user preferences use the existing local
configuration and are not transferred through portable configuration packages.
Moving a portable EXE requires disabling/applying and re-enabling/applying sign-in
startup so Windows uses the new path. Disable sign-in startup before removing a
portable installation. If the EXE is already removed, delete only its registration:

```powershell
Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'SAPLensDesktop' -ErrorAction SilentlyContinue
```

This is **not a Windows Service**: it requires a signed-in user and stops at sign-out.
For unattended hosting, use [Windows Service](WINDOWS_SERVICE.md). Service/Linux
modes do not initialize a tray or alter Windows startup. Browser-only clients hide
these native settings. If the notification area cannot initialize or disappears,
SAP Lens retains/restores the window and normal close behavior rather than leaving
an inaccessible background process. Organization policy can block sign-in registry
writes; previous preferences are retained when applying the change fails.

Automated Linux tests cover controller transitions, native-API contracts, settings
persistence/rollback and browser controls. **Native acceptance is still required**:
EXE/WebView2 close/hide, double-click and menu restoration, Explorer restart, actual
browser access while hidden, simultaneous browser/WebView use, explicit Exit,
shutdown/sign-out, sign-in startup, port conflicts and cleanup during uninstall.
