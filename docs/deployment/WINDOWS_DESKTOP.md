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
or use the [installer/deployment build](../BUILD.md#commands). For local portable EXE
development, the canonical [Windows Build mode](../BUILD.md#commands)
uses the authoritative version without `-Version`; its output is a portable ZIP,
not this installer-first archive. Neither build path grants production acceptance.
The installer deployment output is:

`sap-lens-win-desktop-x64-v<version>.zip`. GitHub Releases publish only the
archive, not loose checksum sidecars. Actions retain their checksum internally for
distribution round-trip verification. The standard ZIP has one launch choice:

- `SAP-Lens-Windows-Desktop-x64-<version>-Setup.exe` — per-user Setup.
- A short README and application/Inno Setup licenses.
- `metadata/` with the exact package manifest and native installer receipt.

The portable application EXE is retained internally for installer construction,
canonical PE/privacy checks and native smoke tests. It is not duplicated in this
ZIP. The legacy **Build Windows Application** workflow still provides its explicit
portable distribution with the unchanged exactly-two-file verification contract.

Installer binary file/product versions use the four numeric components from the
validated build identity. Displayed versions retain the full version string,
including Alpha, Beta or RC suffixes. The package verifier checks both numeric
versions and the textual product identity against that same build identity.

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
[deployment validation status](README.md#validation-status). Review paths and
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

For intentional private-data removal, close the application and take a backup.
Before uninstalling, the installed executable supports an explicit maintenance
command. An independently obtained legacy portable distribution also supports it:

```powershell
$data = Join-Path $env:LOCALAPPDATA 'SAP Lens' # Use the actual configured data root.
$report = Join-Path $env:TEMP 'SAP-Lens-data-removal.json'
$cleanup = Start-Process (Join-Path $env:LOCALAPPDATA 'Programs\SAP Lens\SAP-Lens.exe') -ArgumentList @(
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

Before application packaging, the selected Windows Desktop job compiles the
complete installer definition (including Pascal code) for Alpha, Beta, RC and
Stable and verifies each resulting PE with the canonical installer verifier.
The existing `pefile` verifier dependency is pinned in build requirements and
provisioned in an isolated compiler-check environment. Inno's fixed-width text
resources contain trailing spaces; the verifier removes only trailing space/NUL
padding and still rejects different product names, versions, numeric resources,
signatures or duplicate metadata. Controlled failures identify the rejected
field without printing private third-party parser errors.
The check uses a temporary compiler-as-payload fixture, deletes the outputs and
does not run or approve an application installer. Normal packaging still requires
the validated application inputs and the native installation/lifecycle tests.
PowerShell parsing and Python recipe checks alone do not compile Inno's `[Code]`
section; that section uses Pascal comments (`//` or braces), not INI `;` comments.

The deployment pipeline keeps the canonical portable verifier's exactly-two-file
ZIP rules for the internal portable input. The installer-only outer ZIP groups
its manifest and receipt under `metadata/`. After download, CI rechecks exact
contents, hashes, identity, unsigned installer resources and the retained internal
portable payload; it does not need to ship that second copy to users. Native acceptance permits an existing registered production installation by
compiling a separate, test-only AppId into a private marked workspace. It never
executes production Setup. It tests installation, reinstallation, installed-EXE
lifecycle, uninstall and data preservation, then verifies production invariance.
On failure, the native test reports its current phase and retains its isolated
setup log directory. The selected Windows Desktop job uploads only setup/reinstallation logs
from those synthetic test directories as a separate seven-day diagnostics
artifact; local operators can inspect and then remove their retained directory.
Settings, backups and runtime data are not uploaded. Diagnostic logs are never
added to the deployment package or release assets.

Pending manual acceptance includes actual Windows compiler/setup execution,
previous-version upgrades, clean-PC/IT-policy behavior, WebView2, Explorer/file
and Save dialogs, high DPI, restart/recovery and UNC sources. Linux unit/static
checks are not equivalent to these tests.

## Optional system tray operation

These preferences are under **Settings → Runtime & Scheduling** and exist only in the Windows Desktop application. A [scheduled refresh](../data/IMPORT_AND_REFRESH.md#scheduled-refresh) also runs only while the desktop application is running, so combine it with tray operation if the window is normally closed.

In the native Windows application, open **Settings → Runtime & Scheduling → Windows Desktop**.
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


## EXE startup smoke contract

Process readiness and data configuration are separate. `/health/ready` must
return HTTP 200 with `status: ready`; this does not imply any SAP source has
been imported. `/health` also identifies the application and owned runtime.
The native `scripts/test-windows-exe.ps1` smoke check requires exact states:

| Scenario | Application status | Cached roles |
| --- | --- | --- |
| Fresh first launch, no source configured | `needs_configuration` | 0 |
| Synthetic catalogue configured in Dynamic mode | `ok` | 2 |
| Relaunch of that configured installation | `ok` | 2 |
| Configured installation with preferred port occupied | `ok` | 2 |

`loading`, unknown states, wrong identities and incorrect counts never pass.
A configured scenario still at `needs_configuration` reports
`configuration_required`; inspect its application log for an unavailable or
invalid source. A fresh installation requiring configuration is not a process
startup failure. Production health semantics are unchanged.

Run on native Windows against the intended artifact after closing any existing
desktop instance (the smoke test never terminates unrelated applications):

```powershell
powershell -NoProfile -File .\scripts\test-windows-exe.ps1 -ExecutablePath .\backend\dist\SAP-Lens.exe
```

Use the actual built EXE path if different. Test storage and source environment
are isolated; production CSVs are never used by the smoke fixtures. Source-mode
backend tests and static PowerShell contracts do not establish packaged Windows
or WebView2 acceptance.

### App Control / WDAC blocks before startup

An unsigned EXE can be rejected by an enforced Windows App Control (WDAC)
policy **before process creation**. This is different from a running application
reporting `needs_configuration`. Packaging success is not launch authorization;
a checksum, PE product metadata and an Authenticode signature are separate
properties. A signature alone does not guarantee acceptance by organization policy.
See [code signing readiness](CODE_SIGNING.md) for the existing unsigned status.

The smoke test reports `windows_application_control_blocked` for native Windows
error **1260** (`ERROR_ACCESS_DISABLED_BY_POLICY`) or a blocking Code Integrity
**3077 / 3033** event correlated to this exact EXE and launch time. It reports
other creation failures as `process_creation_failed`. Error 577 or `NotSigned`
alone does not prove WDAC. Audit-only event 3076 is not treated as a block.

Failure diagnostics include the original launch error, native error code when
available, whether this attempt created a process, Authenticode status and
correlated event/policy IDs. The read-only event query covers two seconds before
and after the attempted process creation, capped at 128 entries. Exact DOS or
mapped NT device paths are compared; basename/suffix matches and parent-process
paths cannot attribute a block. NT drive mapping uses the read-only Windows
`QueryDosDevice` API. If App Control/Constrained Language prevents its diagnostic
helper, or event/signature inspection is unavailable, the limitation is reported;
the original exception remains the cause. Ordinary smoke execution does not
require elevation. A blocked launch always fails verification.

Use an existing package first; a rebuild is not necessary to investigate policy.
From the repository root, with all existing SAP Lens desktop instances closed:

```powershell
# Parse scripts and run direct contracts before attempting the EXE.
powershell -NoProfile -File .\scripts\check-powershell.ps1
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --test test_desktop_smoke_script --test test_desktop --test test_windows_stages --test test_windows_package --test test_startup_session --jobs 1 --log build/windows-wdac-targeted.log --report build/windows-wdac-targeted.json

$exe = (Resolve-Path .\backend\dist\SAP-Lens.exe).Path
Get-AuthenticodeSignature -LiteralPath $exe | Select-Object Status
$launchStart = Get-Date
powershell -NoProfile -File .\scripts\test-windows-exe.ps1 -ExecutablePath $exe
$smokeExit = $LASTEXITCODE
$launchEnd = Get-Date
Write-Host "Desktop smoke exit code: $smokeExit"

# Optional read-only event overview; the smoke report performs exact EXE correlation.
# This overview alone cannot attribute events to SAP Lens.
Get-WinEvent -FilterHashtable @{
    LogName = 'Microsoft-Windows-CodeIntegrity/Operational'
    Id = @(3077, 3033)
    StartTime = $launchStart.AddSeconds(-2)
    EndTime = $launchEnd.AddSeconds(2)
} -MaxEvents 128 -ErrorAction Stop | Select-Object TimeCreated, Id, RecordId
```

In Event Viewer, use **Applications and Services Logs → Microsoft → Windows →
CodeIntegrity → Operational**. Inspect the event XML's `FileName` and policy ID
near the launch timestamp. An unrelated executable or old event is not evidence
for this launch. If logs are inaccessible, retain the original process error and
ask the organization's security administrator to review the matching event.
Use organization-approved signing and deployment; do not disable WDAC, alter
policies, install trust certificates, add exclusions or bypass enterprise controls.
No certificate provisioning or automatic signing is implemented here.

### Configured-source failure evidence

The earlier seeded-CSV failure occurred **after** backend startup, unlike the
subsequent policy block. The loose-source fingerprint defect described below
has now been reproduced and corrected; native acceptance of that correction is
still pending. After the organization authorizes execution, all four smoke scenarios must pass; a
configured installation still requires `ok` and exactly two synthetic roles.

The failure report records settings/source existence, whitelisted source mode,
schema-current and expected-fixture-path flags, readability, byte count and a
read-error type. No CSV contents or configuration values are printed. Bounded
startup evidence summarizes only allowlisted stage/result fields and whether a
CSV failure was logged; the existing redacted log tail remains available.
These observations distinguish missing/unreadable fixtures, persistence/path
mismatches and logged initialization/import failures. They cannot alone prove a
database or packaged-resource cause. Preserve the full local application log,
scenario settings and build identity for investigation, but inspect/redact them
before sharing; never commit settings, logs, source files, credentials or tokens.
Native Windows and WebView2 acceptance remain separate from Linux/mock checks.

### Packaged source initialization and cache identity

Frozen PyInstaller modules live in the bundled Python archive; their loose `.py`
files are not required or distributed. Source fingerprinting previously tried to
read those files before parsing a configured CSV. That produced a per-source
failure and left zero roles even when the CSV was valid and readable. The old
loader exception log did not cover failures returned in a lifecycle report.

Frozen fingerprints now hash module-loader code objects, including nested code,
module identity and the Python cache tag. Extraction-specific filenames are
normalized so identical code can reuse its cache across launches. Code changes
still invalidate fingerprints; unavailable module code fails explicitly rather
than using a constant fallback. Source checkouts continue hashing source bytes.
Import validation, atomic replacement, SQLite/HMAC integrity, authentication and
health-state/count requirements are unchanged.

Startup `data_loader: created` means the loader object exists, not that a source
has loaded. `source_initialization` separately reports starting, ready, failed or
unconfigured. Per-source activation records report only operation, source kind,
status/category, skip reason and record count. Failure records include phase,
exception class and OS error codes, never file contents or configuration secrets.
The smoke log summary recognizes lifecycle failures and retains backup-failure
and source-initialization stage markers.

A forced pre-migration backup failure does not prevent the same valid source
from loading in the regression test. This is separate from the source-file
fingerprint defect; the exact native backup warning still needs its full local
application log for diagnosis. No backup verification or migration safety gate
was bypassed.

After syncing the fix, run direct tests on Windows:

```powershell
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --test test_desktop --test test_persistent_cache --test test_csv_lifecycle --test test_storage_migration --test test_desktop_smoke_script --test test_test_profiles --jobs 1 --log build/windows-packaged-csv.log --report build/windows-packaged-csv.json
```

The existing EXE contains the old fingerprint code. Rebuild the Desktop target
**once** to test the correction (service packaging need not be repeated):

```powershell
.\scripts\build.ps1 -Mode build -Platform windows -Target desktop -NonInteractive
```

The build runs native EXE smoke validation. To inspect that same new artifact
again without another build:

```powershell
powershell -NoProfile -File .\scripts\test-windows-exe.ps1 -ExecutablePath .\backend\dist\SAP-Lens.exe
```

Retain all four scenario results. Linux source/frozen-loader simulations do not
establish native Windows/WebView2 success. App Control requirements still apply.

### Resolve build tools before packaging

Run prerequisite setup for the selected target before rebuilding. actionlint
1.7.12 is acquired and verified before expensive local validation; Inno Setup's
pinned bootstrap uses the same resolver when an installer target needs it.
Portable Desktop does not acquire unrelated installer tooling. See the
[build prerequisite guide](../BUILD.md#centralized-prerequisites-and-restricted-networks)
for native Windows setup/check commands, persistent caches, internal mirrors,
offline artifacts and strict checksum/version handling. A corporate HTTP 403
remains unverified until that setup succeeds on the affected Windows network;
packaging success or Linux/mock tests cannot establish it.


## Isolated native installer acceptance

A registered SAP Lens copy can remain installed. Exit any running copy, including
its background/tray process, first; the test never terminates it or bypasses the
production single-instance/maintenance mutex. Run as the same Windows user, without
administrator elevation. An unrelated Windows Service installation remains separate.

The production AppId stays `{5DB5BC51-A860-44CA-93CA-09AE85812DF0}`. Each acceptance
run compiles the same Inno recipe and verified application payload with a fresh
test-only GUID. The test wrapper has a distinct name/uninstall key, no shared
shortcuts or automatic application launch, and a private workspace whose absolute
path is bound into the executable. Setup rejects `/DIR` relocation and reparse
paths; its uninstaller requires the same workspace/ownership marker. Test data
and backups are fixed to that workspace, not the production fallback directories.

Before execution, the PE verifier requires `FileDescription` to identify that
exact test GUID. Production verification rejects test-only wrappers; the native
harness refuses a production or changed executable. Production Setup is only
resource-checked and hashed, never installed. Production uninstall registrations
(in both registry views), installed files and default/custom data/backup paths
are read-only snapshots checked through the lifecycle. Registry differences and
file paths are reported without file contents. The private plan contains local
paths and hashes and is not a distribution/upload artifact.

A success receipt is written only after test uninstall, production-invariance
checks and workspace cleanup complete. It binds the source production installer,
the **different test installer actually executed**, recipe and payload hashes,
test/production IDs and cleanup outcome. This proves the isolated recipe lifecycle;
production-AppId upgrade compatibility, clean-PC and enterprise-policy acceptance
remain separate release gates.

### Verify without repeating the entire Windows build

Keep the prepared `backend/build/python-env`, pinned Inno compiler, validated
`backend/dist/SAP-Lens.exe`, package-verification and build-version metadata from
the same previous build. Isolated wrapper compilation reuses those verified bytes;
it does not bypass the production packaging receipt/freshness gate or rebuild the
application. The production Setup must have a matching producer-written
`backend/build/installer-proofs/<Setup-SHA256>.json` binding its approved payload,
recipe and build identity. Older installers without this proof must be rebuilt
through the normal validated installer builder; do not generate a proof
retrospectively or bypass its freshness checks. Only the isolated test wrapper
reuses the bound payload. Use a new report filename and a verified production Setup EXE (extract
it from its checked Desktop ZIP if necessary).

```powershell
powershell -NoProfile -File .\scripts\check-powershell.ps1
.\scripts\build-desktop-installer.ps1 -CompileCheck -OutputDirectory .\backend\build\installer-isolation-check
.\backend\build\python-env\Scripts\python.exe scripts/run-tests.py targeted --test test_desktop_installer --test test_windows_ports --test test_installer_preflight --jobs 1 --log build/installer-isolation-native.log --report build/installer-isolation-native.json
.\scripts\test-desktop-installer.ps1 -Installer 'C:\Builds\SAP-Lens-Windows-Desktop-x64-<version>-Setup.exe' -Report ".\backend\build\installer-acceptance-$([guid]::NewGuid().ToString('N')).json"
```

CompileCheck now covers four production channels **and** the acceptance-only
conditional code; its compiler-as-payload fixtures are never installed or released.
Actual Inno compilation and the full native lifecycle still require Windows.

### Failed acceptance and recovery

Failures name their stage, keep the primary failure separate from cleanup errors,
and retain the private `sap-lens-installer-<GUID>` workspace with ownership marker,
plan, compiler proof and setup/reinstallation logs. The test uninstalls only a
registration whose GUID, install location and uninstall executable belong to that
workspace. It never deletes registry entries manually or runs a production
uninstaller. Sharing failures leave recovery evidence and return a nonzero status.

Inspect the retained plan and the **test GUID's** HKCU uninstall entry before any
manual action. If the automated cleanup could not finish, run only that workspace's
`application\unins000.exe` as the same user; its bound-directory guard remains
active. Do not move it, remove `.owner`, delete production registry keys or apply
recursive permission changes. Preserve diagnostics before removing test-only files.
Private snapshots, settings and backups are excluded from CI diagnostics uploads.
