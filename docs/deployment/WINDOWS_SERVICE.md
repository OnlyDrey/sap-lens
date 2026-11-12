# Windows Server service

## Approach and distribution

The service ZIP includes **SAP-Lens-Service-Manager.exe**, a .NET Framework 4.8
Windows GUI. It requests administrator approval for service administration; normal
server execution uses LocalService. End users do not need to execute PowerShell
scripts. PowerShell remains a build/CI tool and an optional legacy maintenance path.
Unsigned EXEs can still be subject to company application-control policy.

## Recommended setup: direct HTTPS

1. Extract the complete service ZIP to a permanent, administrator-controlled folder,
   for example `C:\Program Files\SAP Lens Server`. Keep the complete `app/` folder.
2. Open `SAP-Lens-Service-Manager.exe` and approve elevation.
3. Review the detected hostname, FQDN and active IPv4 addresses. Keep only the
   addresses users should use; add a DNS alias if needed. Enter comma-separated
   names/IPs without URL schemes or ports. Detection is a suggestion, not DNS
   provisioning: each selected name must resolve from the client computers.
4. Choose the HTTPS port (default 18743), a dedicated local data directory and the
   IPv4 listen address. `0.0.0.0` listens on all IPv4 interfaces; it is not a URL.
   The manager initially requires an empty data directory and refuses Windows,
   Program Files, application and credential-directory locations.
5. Generate a self-signed certificate or specify an existing PEM certificate and
   unencrypted PEM private key. Existing files are copied into protected storage.
   Generated certificates contain typed DNS/IP SANs for every selected address and
   expire after 365 days. Trust warnings are expected for an untrusted issuer.
   Expired certificates, mismatched keys and missing SAN coverage are rejected.
6. Enter the initial administrator username and a password of 14–256 characters.
   Click **Register / save**, then **Start**. Registration sets automatic startup;
   no logged-in desktop or visible terminal is required for normal operation.
7. Configure Windows Firewall separately to allow that port only from approved
   client machines/subnets or VPN. The manager does not open any firewall rules.
8. Use one of the **Configured URLs**, for example `https://SERVER01:18743`,
   `https://server01.example.invalid:18743` or `https://192.0.2.10:18743`.

The manager generates `SAPLensService.xml` in its own folder. The port, binding,
allowed hosts, origins, certificate and data path in that configuration are the
values used by the installed service. All aliases share the same HTTPS scheme and
port and are accepted by the origin checks. Direct TLS requires no IIS/reverse
proxy. The application retains its existing single-worker and storage-lease policy.

Stop the service before saving configuration changes, then start it again. Address
changes need matching certificate SANs; generate a replacement or provide a suitable
certificate. Renew certificates before expiry. Data relocation is intentionally
refused after registration: back up and migrate while stopped rather than silently
pointing the service at a different empty store. Unregistering retains configuration,
data and credentials; an existing XML is never silently overwritten by re-registration.

### Accounts and permissions

Use **Save account** in the elevated manager to add an account, change its role or
password, or disable it. For existing accounts, a blank password preserves the
current password. A new account needs a password. The last enabled administrator
cannot be disabled or demoted. Account changes apply on the next request without
a restart. Usernames are case-sensitive; allowed characters are letters, digits,
dot, underscore, hyphen and `@`. The local account file supports up to 100 accounts.

| Role | Allowed operations |
| --- | --- |
| Administrator | All application operations, including configuration, imports and review-period administration |
| Reviewer | Read shared data, export reports and record Account Review/SoD decisions and remediation actions |
| Read-only | Read shared data, simulate access changes and export reports; no review or configuration changes |

Permissions are enforced in the backend. This is a shared dataset, not per-account
data isolation. Some UI controls may remain visible and return a permission error
for a restricted account. Accounts are administered locally, not through the website.
Passwords are stored as salted PBKDF2-SHA256 hashes (600,000 iterations); local
account administration passes passwords on stdin rather than the command line.
HTTP Basic challenges are used over HTTPS, with the existing failed-sign-in
throttle. Browsers may retain credentials; use a separate browser profile or close
the browser session when switching accounts. Do not rely on a tab close as logout.

Account Review checks the previously displayed decision timestamp before accepting
a server-user update. SoD retains its revision/evidence conflict checks and frozen
history. Individual-account review actions record the authenticated username instead
of trusting the reviewer text entered in the browser. Desktop and legacy shared
credential deployments retain their existing identity behavior.

Accounts and TLS material default to `C:\ProgramData\SAP Lens Server Access`.
The service can read that location; only administrators/SYSTEM should modify it.
Data and logs default to `C:\ProgramData\SAP Lens Server`. Back up access material
separately under equivalent ACLs: the legacy data-backup command does not include
this separate account/certificate directory. The application folder is protected
for administrators/SYSTEM with read/execute permission for the dedicated service SID.
Existing unrelated explicit ACLs on selected data folders must be reviewed by IT.

### Validation limits

Offline tests cover account authentication/permissions, alias origins, stale edits,
certificate SANs and invalid TLS settings. The Windows build compiles the manager,
runs its certificate-generation self-test and verifies its x64 GUI/elevation metadata.
Native GUI operation, registration using the manager, ACLs, reboot startup, certificate
renewal, recovery and concurrent real-client use still require Windows acceptance.
Do not treat Linux tests as evidence that those Windows checks have executed.

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
[Build Deployment Packages](../BUILD.md). After a successful approved
run, download `sap-lens-win-service-x64-v<version>`, extract GitHub's wrapper ZIP,
verify the inner ZIP's `.sha256`, and extract it into a new installation directory.
The inner ZIP contains `app/` (headless EXE/Python runtime/frontend), pinned WinSW,
service manager EXE, optional management script, WinSW MIT license, README, PE verification report, package
manifest and per-file hashes. Actual machine-specific `SAPLensService.xml` is
created by service registration through the manager or optional script; no organization
configuration or credentials are shipped.

Intended targets: Windows Server 2022/2025 x64, subject to native acceptance;
older Server versions are not certified. CI uses `windows-latest`. No logged-in
user or Node/Python development environment is required on the target.
Copy to `C:\Program Files\SAP Lens Server` and use the management commands below.
Do not launch the desktop EXE as a service. The workflow verifies PE/resources and
runs SCM install/start/health/version/stop/uninstall, when actually dispatched on a
Windows runner; reboot/recovery/UNC acceptance remains manual. See the
[deployment validation status](README.md#validation-status) before interpreting implemented checks
as executed results.

## Build on x64 Windows

Use the [central build guide](../BUILD.md#commands):
`scripts/build.ps1 -Mode package -Platform windows -Target service` (or target `all` for
installer/desktop plus service). Version resolution is automatic; deployment
archives default to `dist/<version>-<commit12>/`. WinSW is acquired and SHA-256 checked;
internal offline `-WinSW` overrides are still checked. Packaging does not install
SCM; actual service installation/lifecycle acceptance needs Windows administration.

No tags, releases or remote commits are created by local builds.

The selected wrapper is WinSW 2.12.0 x64, SHA-256
`05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da`.
Keep its MIT license. Pin/version changes require upstream/security review.
The onedir console package excludes WebView2 and verifies PE/resources, identity,
frontend bytes, private-file exclusions and hashes. Fresh local receipts or same-run
CI attestations are mandatory; neither is an unchecked skip-validation option.

## Legacy script administration

For the optional script path, copy to `C:\Program Files\SAP Lens Server` and open
elevated PowerShell there (SCM changes require admin). Another location requires
`-InstallDirectory 'C:\Your\Permanent\Folder'` on each command. These defaults are
legacy loopback/local access; use the GUI above for direct shared HTTPS hosting:

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
configure an [authenticated HTTPS boundary](SECURITY.md) for browser
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

### Access-secret permissions: fresh install, upgrade and repair

- **Fresh install:** `--init-secret` creates the file and immediately restricts it to the creating account and SYSTEM (if that fails the new file is deleted). `-Action Install` then replaces the ACL with SYSTEM (full), Administrators (full) and the dedicated service SID `NT SERVICE\SAPLens` (read), inheritance removed. Links and directories are refused as secret paths.
- **Startup policy:** the service refuses a secret that Everyone, Users, Authenticated Users, Interactive, Network, Anonymous or Guests can read or change, or whose ACL cannot be read (fail closed). The message names the principals, never the content.
- **Upgrade from an older installation:** `-Action Upgrade` first runs the application's own configuration check against the installed service configuration. If the secret still carries a permissive inherited ACL (for example a copy restored under `C:\ProgramData`), the upgrade stops before any file is changed and points to the repair.
- **Repair (explicit):** `-Action RepairSecret` reports the policy result for the secret path **from the installed service configuration** (never from a parameter); `-Action RepairSecret -ConfirmSecretRepair` then applies the same ACL as install and re-checks. It never reads or prints the content, ignores other files, and needs an elevated shell. Named user groups added by hand are not removed silently: if the policy still rejects the file afterwards, review them with `icacls`.
- **Backup and restore:** archives do not contain the secret file; after restoring one from another source, run `RepairSecret` before starting.
- **Status:** the DACL parser and the lifecycle are unit-tested with simulated DACLs; `GetNamedSecurityInfoW`, `icacls` and the service SID on a real Windows host are pending native acceptance.
The backend refuses a duplicate data store or occupied port rather than silently
moving. Stop timeout is 25 seconds; review wrapper/SCM logs for forced termination.
After a successful WinSW command, management waits up to 40 seconds for SCM to
confirm the expected state (Stopped, Running or removed). A timeout fails the
operation and reports the last observed state. Backup, upgrade and uninstall do
not proceed merely because the wrapper's stop command returned successfully.

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

## Installer preflight

`manage-server-service.ps1 -Action Install` refuses, before creating any directory, permission or service, on a host that is not 64-bit Windows 10 or Server 2016 or newer, when the port is already in use, when a `SAPLens` service already exists, when the PowerShell session is not elevated, or when the bundle or the WinSW wrapper fails its integrity check. The installed service needs no Python, pip, Node.js or npm. These are static and mocked-test guarantees; real Windows service acceptance is separate.

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

## Connection modes and registration diagnostics

The Service Manager offers three explicit modes (default: HTTPS with a generated self-signed certificate):

| Mode | Certificate | Notes |
|---|---|---|
| HTTPS, generate a self-signed certificate | generated and validated | SANs contain every enabled DNS name and IPv4 address; a wildcard listen address such as `0.0.0.0` is never a name |
| HTTPS, use an existing certificate | PEM certificate and unencrypted PEM key | validity period, key match and SAN coverage of every enabled name are checked before activation |
| HTTP, no certificate | none; nothing is generated | unencrypted. Binding HTTP beyond this computer needs the explicit acknowledgement in the Service Manager (`SAP_LENS_ALLOW_HTTP=1`); account authentication and the firewall restriction still apply. HTTPS is never downgraded automatically: an existing HTTPS installation opens in an HTTPS mode. |

The access URLs shown by the Service Manager use the configured scheme. A failed registration now reports the validation step and the underlying error, for example `Invalid server configuration at step "TLS certificate names (SAN)": The TLS certificate SANs do not cover: 127.0.0.1. Present: DNS=localhost.` The steps are listen address, port, data and source directories, public origin, allowed hosts, authentication boundary, TLS certificate and key files, TLS certificate and private key (load and match), TLS certificate decoding, TLS certificate validity period, TLS certificate names (SAN) and account file. The same check can be run by hand with `SAP-Lens.exe --check-server-config` (with the service environment).

The command-line `manage-server-service.ps1` keeps its stricter rule: network public origins require HTTPS there; HTTP on the network is a Service Manager decision with acknowledgement.

## Isolated native SCM acceptance

Run from the repository in an elevated PowerShell, with no existing `SAPLens`
service. Use a trusted, package-verified service bundle. Both inputs are supported:

```powershell
.\scripts\test-server-service.ps1 -Bundle 'C:\Builds\verified-service-bundle'
.\scripts\test-server-service.ps1 -Bundle 'C:\Builds\verified-service-package.zip'
```

The test copies directory input or safely extracts ZIP input into a unique
`sap-lens-scm-<GUID>` workspace under RUNNER_TEMP/the user's temporary directory.
It rejects links, junctions/reparse points, traversal/ADS/reserved ZIP names,
duplicate entries and oversized archives before installation. ZIP origin-zone
metadata is propagated to extracted files; extraction does not unblock code. Required files,
the verification report and its file hashes are checked before SCM operations.
Expected runtime version comes from that package's identity, not a previous
checkout's generated build metadata. An unsigned archive is not automatically
trusted merely because its internal hashes agree; verify artifact provenance.

All mutable configuration, data, backups, restore targets, replacement bundles
and upgrade copies stay inside this workspace. Production backup ACLs remain
unchanged. The workspace is restricted to its creator and SYSTEM, with a bound
ownership marker. There is no new SYSTEM endpoint, scheduled task, service
cleanup command or production purge option. Production purge deliberately
preserves backups and is not used as a substitute for test cleanup.

After verifying that the test-owned service is removed, cleanup validates the
workspace marker, canonical boundary and reparse-free tree. If SYSTEM-only ACLs
block enumeration/deletion, it takes ownership of that single validated test
entry and grants FullControl only to the invoking SID using literal paths.
There is no recursive takeown/icacls, no Everyone/Users/Authenticated Users
grant, and no privilege operation outside the marked workspace. The full tree
is checked before deletion; directories are removed non-recursively. Original
acceptance errors remain primary if cleanup also fails, and both are reported.
A service not owned by the test, remaining registration, ACL error or locked
file causes nonzero failure and retention of the workspace for investigation.
Do not manually run recursive ownership commands against production directories.

ServiceController/CIM handles are disposed. The test refuses existing services
and checks the SCM binary path before uninstalling a partially installed service.
A passing report is written only after service removal **and cleanup** succeed.
Directory input updates `verification-report.json`; ZIP input remains unchanged
and gets a `<zip>.scm-verification.json` sidecar. Failed cleanup never marks the
report passed. Reboot, recovery and UNC scenarios remain separate acceptance.

Native release-gate checks are still required; Linux structural tests cannot
prove SYSTEM-owned cleanup or SCM behavior. Run the helper tests and parser on
Windows PowerShell 5.1 and PowerShell 7 where available:

```powershell
.\.venv\Scripts\python.exe scripts/run-tests.py targeted --test test_windows_acceptance_split --test test_local_deployments --test test_prerequisites --test test_unified_build --jobs 1 --log build/windows-scm-build.log --report build/windows-scm-build.json
powershell -NoProfile -File .\scripts\check-powershell.ps1
```

The protected-ACL fixture requires elevation; other helper tests never install
a service. The real SCM command above installs a service and requires elevation.


### Replacement inventory and retained-workspace diagnostics

SCM acceptance captures a pristine replacement from the verified manifest **before**
service startup. It copies exactly the approved files and verification report,
never runtime logs, generated service XML or backup debris from an installed
bundle. Upgrade still rejects unexpected/missing files and reparse points; its
message now names the relative path and entry type. Do not add runtime files to
the package allowlist to make acceptance pass.

After uninstall, acceptance waits up to 15 seconds for processes whose executable
paths belong to its isolated workspace. It does not terminate unrelated processes.
Entry cleanup clears read-only attributes inside the marked test tree and retries
only access/sharing/lock errors at most five times (1.5 seconds total backoff).
ACL recovery remains per-entry and caller-scoped, without recursive grants.

If cleanup fails, keep the printed workspace, primary error, cleanup error and
package verification report. Inspect the named entry, running processes and ACLs
from an elevated shell before any manual removal. Never run recursive ownership
or deletion against the input package, a production install or application data.
A retained workspace is not a successful acceptance run. New native helper tests
cover manifest-defined replacement, read-only directories and locked-file
retention/retry; the full elevated SCM run remains a separate gate.

## Separate Windows SCM acceptance evidence

A successful standalone acceptance writes `PACKAGE.zip.scm-verification.json`
beside the tested ZIP. Directory inputs write `DIRECTORY.scm-verification.json`
beside the directory; their fingerprint binds the original verification report
and is not a ZIP release receipt. Neither path rewrites `verification-report.json`
or the historical `build-manifest.json`.

Evidence records the package SHA-256, source/version identity, completed lifecycle
checks and successful isolated cleanup. Management runs in a child PowerShell host
so its exit cannot terminate the reporting host. Success is announced only after
the create-only receipt is flushed and read back. A publication failure returns a
nonzero error even if the service lifecycle completed. An existing sidecar is
preserved, never silently overwritten; inspect it before any authorized rerun.
Reboot, recovery-policy and UNC acceptance remain unverified by this lifecycle.

Local release-output verification accepts either the original successful native
build evidence or a valid separate ZIP receipt. Wrong hashes/identity, missing
checks, failed cleanup and missing requested build targets are rejected. A sidecar
is local acceptance evidence, not a signed attestation or permission to publish.
Existing same-run CI publication protections are unchanged.

To verify a managed output directory without rebuilding or running SCM, select its
existing `build-manifest.json` in PowerShell (run from the repository root):

```powershell
$ErrorActionPreference='Stop'
$manifests=@(Get-ChildItem .\dist -Filter build-manifest.json -File -Recurse | Sort-Object LastWriteTime -Descending)
if (-not $manifests.Count) { throw 'No managed deployment build found.' }
$selected=$manifests[0]
$identity=Get-Content -LiteralPath $selected.FullName -Raw | ConvertFrom-Json
python scripts/deployment/build-deployments.py --verify-output --version $identity.version --platform service --output-dir $selected.DirectoryName
if ($LASTEXITCODE -ne 0) { throw 'Release-output evidence verification failed; inspect the manifest and native sidecar.' }
```

This checks against the current source commit. If the selected manifest belongs to
another commit, verification intentionally fails. No lifecycle run, release or
workflow is started. Do not edit a historical manifest to mark acceptance passed.
A native SCM rerun requires explicit authorization, elevation, no existing SAPLens
service and a verified package. Packaging success alone is not that authorization.

## SCM cleanup invalid-parameter diagnostics

Cleanup removes files with `Remove-Item -LiteralPath -Force`; it does not first
rewrite `FileInfo.Attributes`. Directory read-only handling is conditional.
Windows error 87 means invalid parameter, not evidence of a lock. It is never
retried as a sharing violation. Failures retain the owner marker/workspace and
report relative path, entry type, operation and captured attributes. Existing
same-user ownership/reparse boundaries and narrowly scoped ACL recovery remain.

Management subprocesses have a 180-second limit with periodic RUNNING messages;
HTTP probes use three-second timeouts and process enumeration uses a bounded CIM
operation. Cleanup has a cooperative 120-second traversal/deletion deadline inside a
separately supervised child. The external watchdog can terminate that owned child
even when traversal is blocked in an OS I/O call. Only the explicitly created management host is killed on its timeout.
Cleanup still verifies service removal and waits for workspace-owned processes;
no unrelated process or production installation is terminated. Every cleanup
failure prevents successful evidence publication.

From the Windows repository root, without running the SCM lifecycle:

```powershell
powershell -NoProfile -File .\scripts\check-powershell.ps1
python scripts/run-tests.py targeted --test test_windows_acceptance_split --jobs 1 --log build/scm-cleanup-native.log --report build/scm-cleanup-native.json
```

The helper regression exercises Normal/Read-only
`data\.application-backups\retention.json` in a private synthetic workspace.
Run on both Windows PowerShell 5.1 and PowerShell 7 when installed. A full native
SCM acceptance run is a separate check; Linux/static tests do not establish it.

## PowerShell 5.1 SCM management host

SCM acceptance starts its management host with `System.Diagnostics.Process`,
`UseShellExecute=false` and a retained process handle. The former
`Start-Process -PassThru` path could report HasExited but expose an empty ExitCode
on Windows PowerShell 5.1. Missing/non-integer exit status now has its own explicit
failure; it is never treated as zero. Disposal happens after exit/output handling.
The executable is passed via ProcessStartInfo.FileName, and Arguments contains
only fixed switches and a UTF-16 Base64 encoded command. Script paths and named
argument values remain quoted in that payload; shell joining of space-containing
paths is avoided. No execution-policy bypass is used.

Both output streams drain asynchronously to avoid pipe deadlocks and are relayed
before the outer PASS/FAIL message. Management has a 180-second limit; only the
owned child is terminated on timeout. Post-exit pipe draining is bounded, since a
descendant could retain an inherited pipe. Capture failures block acceptance.
The retention.json cleanup correction and evidence-after-cleanup gate are unchanged.

From the Windows repository root (no SCM lifecycle is executed by these tests):

```powershell
powershell -NoProfile -File .\scripts\check-powershell.ps1
python scripts/run-tests.py targeted --test test_windows_acceptance_split --jobs 1 --log build/scm-process-native.log --report build/scm-process-native.json
```

Run with Windows PowerShell 5.1 and PowerShell 7 installed when possible: the helper
cases cover both detected shells, success, explicit nonzero exit, timeout,
unavailable exit status, output capture and paths containing spaces/apostrophes.
A helper pass does not establish native SCM installation/upgrade/cleanup acceptance.

## Cleanup traversal and external watchdog

Cleanup retains the 120-second limit. The main acceptance process now supervises
an explicitly owned cleanup child, so blocked enumeration, ACL tools or filesystem
calls cannot prevent the parent from timing out and failing acceptance. Its last
`.scm-cleanup-progress.json` checkpoint and owner marker remain in the workspace on
failure. No successful evidence is written after a failed or timed-out worker.

Full ownership validation previously repeatedly reparsed the same JSON marker and
used PowerShell provider operations to walk ancestors for every file, often more
than once during deletion. The helper now uses direct .NET attribute checks and
compares the marker's exact text against its initially validated fields. It still
reads/rechecks the marker, caller identity, boundaries and ancestors on each
operation; a changed marker or reparse point fails closed. Redundant outer delete
checks are removed because the deletion helper performs them. All bundle,
replacement, data, restored-data and backup entries remain subject to cleanup;
archives are deleted as files, not opened and recursively expanded.

Progress is streamed approximately every five seconds with phase, elapsed time,
file/directory/deletion counts and relative checkpoint path. A stalled call cannot
emit a new checkpoint; the parent's heartbeat continues and the external deadline
still applies. No Defender/antivirus cause is assumed. The observed 120-second
failure proves expiration, not which operation consumed the time. Native timings
are still required to attribute additional environmental overhead.

Run helper tests first (no service installation):

```powershell
powershell -NoProfile -File .\scripts\check-powershell.ps1
python scripts/run-tests.py targeted --test test_windows_acceptance_split --jobs 1 --log build/scm-traversal-native.log --report build/scm-traversal-native.json
```

After they pass, use an elevated PowerShell for the native lifecycle against your
existing verified package; this does not require rebuilding every artifact:

```powershell
$ErrorActionPreference='Stop'
$bundle=Read-Host 'Absolute path to the existing verified Windows Service ZIP'
$bundle=(Get-Item -LiteralPath $bundle -ErrorAction Stop).FullName
$expected=((Get-Content -LiteralPath ($bundle+'.sha256') -Raw).Trim() -split '\s+')[0]
if ($expected -notmatch '^[a-fA-F0-9]{64}$' -or (Get-FileHash -LiteralPath $bundle -Algorithm SHA256).Hash -ine $expected) { throw 'Package checksum verification failed.' }
.\scripts\test-server-service.ps1 -Bundle $bundle
if ($LASTEXITCODE -ne 0) { throw 'Native acceptance failed; preserve workspace and diagnostics.' }
Get-Content -LiteralPath ($bundle+'.scm-verification.json') -Raw | ConvertFrom-Json
```

An existing SAPLens service remains a hard stop. An existing successful sidecar is
preserved; do not overwrite it or fabricate evidence. Retain native console output
and the latest progress checkpoint if cleanup fails. Helper/contract passes alone
never establish native SCM acceptance.
