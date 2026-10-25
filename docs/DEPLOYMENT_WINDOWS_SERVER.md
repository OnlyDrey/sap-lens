# Windows Server service

## Approach and distribution

A **separate headless onedir PyInstaller bundle** uses `backend/server.py`. A pinned
WinSW x64 wrapper registers that console host with SCM, sends stop signals, manages
its process tree, rotates logs and configures recovery. This avoids adding service
or WebView2 dependencies to shared business code. The existing one-file desktop
EXE/build/version/release workflow is unchanged. Do not register the desktop EXE
as a service. Target machines need neither Python/Node nor a logged-in desktop.

Windows build/install/SCM/reboot/UNC tests have to run on Windows; the Linux
validation report cannot certify this distribution. The following is the implemented
build/install procedure, pending native acceptance testing.

## Download from Actions

Choose `Windows Server Service` or `All` in
[Build Deployment Packages](DEPLOYMENT_PACKAGES.md). After a successful approved
run, download `SAP-Lens-Windows-Service-x64-<version>`, extract GitHub's wrapper ZIP,
verify the inner ZIP's `.sha256`, and extract it into a new installation directory.
The inner ZIP contains `app/` (headless EXE/Python runtime/frontend), pinned WinSW,
management script, WinSW MIT license, README, PE verification report, package
manifest and per-file hashes. Actual machine-specific `SAPLensService.xml` is
created by **Install** using the canonical management script; no organization
configuration or credentials are shipped.

Intended targets: Windows Server 2022/2025 x64, subject to native acceptance;
older Server versions are not certified. CI uses `windows-latest`. No logged-in
user or Node/Python development environment is required on the target.
Copy to `C:\Program Files\SAP Lens Server` and use the management commands below.
Do not launch the desktop EXE as a service. The workflow verifies PE/resources and
runs SCM install/start/health/version/stop/uninstall, when actually dispatched on a
Windows runner; reboot/recovery/UNC acceptance remains manual. See the
[execution report](PACKAGING_VALIDATION.md) before interpreting implemented checks
as executed results.

## Build on x64 Windows

Use the existing local build prerequisites and full validation first. Run from the
repository root with a clean committed checkout:

```powershell
.\scripts\build-local.ps1 -Mode Validate -Version 0.1.0
# Download the official wrapper to a private development-tools directory.
Invoke-WebRequest https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe -OutFile "$env:TEMP\WinSW-x64.exe"
Get-FileHash "$env:TEMP\WinSW-x64.exe" -Algorithm SHA256
.\scripts\build-server-windows.ps1 -Version 0.1.0 -WinSW "$env:TEMP\WinSW-x64.exe"
```

Pinned SHA-256:
`05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da`.
The script checks it; never substitute an unverified wrapper. WinSW 2.12.0 is the
stable selected wrapper, not the 3.x alpha line. Review upstream security/support
before changing the pinned version. Keep its upstream MIT license with deployment
records. The application/service hosting implementation is unsigned.

The build requires the canonical 24-hour validation receipt matching the clean
commit, pinned build tools, frontend, environment and requested version. It reuses
metadata/resource validation, keeps `--noupx`, verifies x64 console PE, version,
icon, manifest, embedded identity/modules, frontend hashes, private-file exclusion
and wrapper/file SHA-256. It excludes WebView2. Output:
`dist/server/<version>/` containing `app/`, `SAPLensService.exe`, management script
and `verification-report.json`, README and WinSW license. This is an **unofficial local build** with the same
local version identity rules as desktop. No release/tag/publication is performed.
Copy the complete folder to `C:\Program Files\SAP Lens Server`; verify its report
checksums over a trusted channel. Do not mix desktop and headless executables.

## Install and manage

Open elevated PowerShell in the installed folder (SCM changes require admin):

```powershell
.\manage-server-service.ps1 -Action Install
.\manage-server-service.ps1 -Action Start
.\manage-server-service.ps1 -Action Status
.\manage-server-service.ps1 -Action Stop
.\manage-server-service.ps1 -Action Restart
```

Default service name `SAPLens`, automatic startup, LocalService identity and a
service SID `NT SERVICE\SAPLens`. Data/log ACLs grant only SYSTEM, Administrators
and this SID. Default data is `C:\ProgramData\SAP Lens Server`, logs its `logs`
subdirectory, sources its `sources` subdirectory. Keep the installed program
read-only for the service identity. No writable storage belongs in Program Files.
The wrapper must be able to read its installed configuration/executable.

Configure at install using `-ListenHost`, `-Port`, `-DataDirectory`,
`-SourceDirectory`, `-LogDirectory`, `-PublicOrigin`, `-AllowedHosts`,
`-Authentication`, `-SecretFile` and `-TrustedProxies`. Start loopback-only, then
configure an [authenticated HTTPS boundary](DEPLOYMENT_SECURITY.md) for browser
access from other devices. The backend additionally validates configuration on
startup. Configuration is `SAPLensService.xml`; it contains secret **paths**, not
credential values. Protect it with normal Program Files administrator ACLs.
For an initial secret, the headless executable supports:

```powershell
.\app\SAP-Lens.exe --init-secret 'C:\ProgramData\SAP Lens Server\access.secret'
```

Create its parent directory first. The installer preserves an existing administrator XML
configuration and refuses to overwrite it during reinstall; review it explicitly. Supply `-SecretFile` when installing basic/proxy
mode; installer restricts its ACL. Do not put domain passwords in this file.
Service failure recovery restarts after 10/30 seconds with a one-hour reset window.
The backend refuses a duplicate data store or occupied port rather than silently
moving. Stop timeout is 25 seconds; review wrapper/SCM logs for forced termination.

## UNC and service identity

Mapped drives belong to interactive sessions and are not supported. Configure an
absolute UNC source root (for example `\\files.example.test\sap-exports`) and paths
inside it. Grant both **share and NTFS read/traverse** permissions to the actual
service identity. LocalService generally has no usable domain network identity.

Where UNC is required, use a domain-managed account or gMSA, configured by your
Windows/domain administrator through SCM/WinSW. For example, after provisioning
the gMSA on the host, configure its identity in SCM using `sc.exe config SAPLens
obj= "EXAMPLE\svcSAPLens$" password= ""`. This is a machine/domain operation, not
an application credential store. Keep the service SID enabled and preserve local
data/log ACLs. Test the path **as the service account**, not as the logged-in user.
The installer deliberately leaves remote share ACLs unchanged; have its administrator
grant permissions to the domain service identity before starting. No plaintext domain credentials are stored.

## Upgrade, backup and removal

Use an elevated PowerShell and a newly extracted, checksum-verified service
package. Management actions retain the installed XML, service identity, external
sources and mutable data. Do not overwrite an installed directory by extracting
an archive over it.

```powershell
.\manage-server-service.ps1 -Action Backup
.\manage-server-service.ps1 -Action Start
.\manage-server-service.ps1 -Action Upgrade -NewBundleDirectory 'C:\Staging\SAP-Lens-Service'
```

Backup stops the service and leaves it stopped. The default private backup
directory is `C:\ProgramData\SAP Lens Server Backups`; `-BackupDirectory` selects
another dedicated location outside data and binaries. The archive includes
persistent records and the administrator service XML. External source files and
external access-secret files are not followed; preserve them separately.

Upgrade verifies exact replacement contents, pinned WinSW and hashes, rejects a
downgrade, stops the installed service and creates a private backup before
activating staged application files. The XML and registration are retained.
Readiness requires a listener belonging to the registered service process tree.
Previous application files remain under `app.previous.<identifier>` until an
administrator accepts the upgrade and makes a retention decision. If startup
fails, the service stays stopped; review logs and compatible data recovery before
switching binaries back. A binary-only rollback is not a data recovery guarantee.

Restore stages into **empty** operator-selected destinations, without overwriting
the live configuration or data:

```powershell
.\manage-server-service.ps1 -Action Restore `
  -Archive 'D:\PrivateBackups\SAP-Lens-Service-example.tar.gz' `
  -RestoreDataDirectory 'D:\Recovery\SAP-Lens-Data' `
  -RestoreConfigurationDirectory 'D:\Recovery\SAP-Lens-Configuration' `
  -ConfirmRestore
```

Keep the original stores and archive until recovery is accepted. Review restored
paths, restore the service SID's required data/configuration access, and explicitly
activate the restored paths/XML before starting. Restore does not rewrite SCM or
silently switch the selected data directory. Test readiness and imported data
before declaring recovery complete. Newer settings cannot be restored into an
older application version.

```powershell
.\manage-server-service.ps1 -Action Uninstall
```

Uninstall stops and unregisters the service; it preserves data, logs, source files,
secrets and the installation. Remove them separately only under retention policy.

Portable helper tests cover exact contents, checksum rejection, XML preservation
and external-entity rejection. The native smoke definition also covers private
backup, empty-target restore and same-version staged upgrade. These native steps
remain **unexecuted in the Linux development environment**, as do reboot, service
recovery and UNC acceptance. No signed installer or unattended OS reboot test is
implied by the management scripts.

Inspect rotating wrapper/application logs under the log directory and Windows
Event Viewer for SCM/wrapper startup failures. No personal data or raw CSV content
should be included in routine application logs. Native acceptance must cover SCM
start/stop/restart/recovery/reboot, no interactive session, WebView2 independence,
local/UNC reads, browser upload/download, snapshot recovery, graceful lock release
and retained desktop native dialogs/exports.

For intentional private-data removal, `-Action Uninstall -PurgeData -ConfirmPurge`
first stops the recognized installed service and invokes the local maintenance
purge under the runtime storage lease. Back up first. It refuses unknown stores,
links or an active writer. The nonprivate lock stub, configuration XML, previous
binaries, external sources/secrets and private backups remain for an explicit
administrator retention decision. There is no automatic global directory removal.
