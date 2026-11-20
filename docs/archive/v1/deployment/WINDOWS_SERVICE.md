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
3. Review the detected hostname, FQDN and active IP addresses. Keep only the
   addresses users should use; add a DNS alias if needed. Enter comma-separated
   names/IPs without URL schemes or ports. Detection is a suggestion, not DNS
   provisioning: each selected name must resolve from the client computers.
4. Choose the port (default 18743), a dedicated local data directory and the
   listen address (IPv4 or IPv6). `0.0.0.0` and `::` listen on all interfaces; they are not URLs and are refused for
   Local access (HTTP). See [Connection modes](#connection-modes-and-registration-diagnostics).
   The manager initially requires an empty data directory and refuses Windows,
   Program Files, application and credential-directory locations.
5. Generate a self-signed certificate or specify an existing PEM certificate and
   unencrypted PEM private key. Existing files are copied into protected storage.
   Generated certificates contain typed DNS/IP SANs for every selected address and
   expire after 365 days. Trust warnings are expected for an untrusted issuer.
   Expired certificates, mismatched keys and missing SAN coverage are rejected.
6. Enter the initial administrator username and a password of 14–256 characters.
   Click **Register / save configuration**, then **Start**. Registration sets automatic startup;
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
portable records, branding and account verifiers in an encrypted `.slbak` archive.
The installed recovery-key environment is used. Preserve the key, service XML, TLS
configuration and external source files separately; they are never transferred.
See [encryption and recovery](BACKUP_RESTORE.md#configure-and-escrow-a-key).

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
  -Archive 'D:\PrivateBackups\SAP-Lens-Service-example.slbak' `
  -RestoreDataDirectory 'D:\Recovery\SAP-Lens-Data' `
  -ConfirmRestore -ConfirmAccountRollback
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
| Network access (HTTPS), generate a self-signed certificate | generated and validated | SANs contain every enabled DNS name and IPv4/IPv6 address; a wildcard listen address such as `0.0.0.0` or `::` is never a name |
| Network access (HTTPS), use an existing certificate | PEM certificate and unencrypted PEM key | copied into protected storage; validity period, key strength, key match and SAN coverage of every enabled name are checked before activation |
| Local access (HTTP), this computer only | none; nothing is generated | unencrypted, so accepted only with a loopback listen address (`127.0.0.1`, `::1`) and local server names (`localhost`, `127.0.0.1`, `::1`). HTTPS is never downgraded automatically. |

HTTP rule (the same in the Service Manager and in the server's `authentication boundary` step): a wildcard listener (`0.0.0.0`, `::`),
a network address, a server name other than the three local names, or a `localhost` that resolves to a network address on the
computer is refused. The Service Manager shows the field and the reason under the mode selection while you type and again on
Register, before anything is created. An older installation that was registered with HTTP on the network and
`SAP_LENS_ALLOW_HTTP=1` keeps its stored configuration until it is saved again; the server itself already refuses to start
remote password sign-in over HTTP, so switch such an installation to HTTPS.

A failed Register / save leaves nothing behind: the previous configuration is restored, and a backup key, certificate pair,
first-run data folder content or configuration file created by that attempt is removed again, newest first. Existing keys,
certificates and data are never part of that rollback. If a file cannot be removed, the error names it.

The access URLs shown by the Service Manager use the configured scheme. A failed registration now reports the validation step and the underlying error, for example `Invalid server configuration at step "TLS certificate names (SAN)": The TLS certificate SANs do not cover: 127.0.0.1. Present: DNS=localhost.` The steps are listen address, port, data and source directories, public origin, allowed hosts, authentication boundary, TLS certificate and key files, TLS certificate and private key (load and match), TLS certificate decoding, TLS certificate validity period, TLS certificate names (SAN) and account file. The same check can be run by hand with `SAP-Lens.exe --check-server-config` (with the service environment).

Certificate key strength: the generated certificate uses a 3072-bit RSA key, created at that size and checked before any file is
written. The server refuses a certificate whose key is weaker than RSA 2048 bits or EC P-256 at the step
`TLS certificate key strength`. An installation that failed earlier with `EE_KEY_TOO_SMALL` has no activated configuration; save
again with the corrected Service Manager. Certificate and key files are created under new names and never overwritten, and the
files of a rejected attempt are removed while the previous configuration is restored. To replace a weak existing certificate,
supply a new pair under new file names; the old files are not changed or deleted for you.

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

Cleanup removes validated files through `System.IO.File.Delete` with fresh
attribute checks and a checked absence postcondition. Read-only clearing is
conditional; Archive-only files are not rewritten. Directory handling is unchanged.
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

### ZIP members without explicit parent directories

SCM extraction validates each destination before creating its parent. ZIP files can
contain `app/SAP-Lens.exe` without an `app/` directory entry. Parent validation
therefore tolerates only .NET FileNotFoundException/DirectoryNotFoundException
and continues up to the owned root. It creates nothing. Every existing ancestor
must be a directory without reparse attributes; permission errors and other I/O
failures remain fatal. A missing descendant beneath a junction is still rejected
when the walk reaches that existing junction. The root and owner marker must
always exist and validate. Absolute/traversing ZIP names remain forbidden.

The native helper suite covers this with nested Unicode/spaced ZIP paths without
directory records, directory bundles, existing parents/files, traversal entries
and missing descendants beneath a junction. Run the helper command above on
Windows PowerShell 5.1 before attempting another native SCM lifecycle. Linux
contract tests do not establish native extraction or acceptance success.

### Repeated retention.json delete failure and CLIXML

The later native transcript localizes error 87 to the PowerShell provider's
`Remove-Item -Force` deletion, after a fresh lookup reports Archive attributes
(32). It does not retain the original provider exception, prove an open handle,
or reproduce deletion of the same file independently. The guarded file primitive
now uses direct .NET File.Delete, rejects missing files before deletion, rejects
reparse/directory targets, clears only Read-only when present, and verifies absence
without suppressing access errors. Stale enumeration objects are refreshed before
use. Changed entry types fail. All ownership/boundary checks remain upstream.
Error diagnostics retain the original exception and print its type/HRESULT chain,
error identifier and precise API phase; code 87 is never ignored or retried.

Child PowerShell uses `-OutputFormat Text` and disables cosmetic progress records.
Useful information, authored structured checkpoints and stderr/errors are still
captured. This avoids CLIXML information metadata containing user/host identifiers;
it does not filter out errors or downgrade failed cleanup.

Native helper verification (no SCM lifecycle):

```powershell
powershell -NoProfile -File .\scripts\check-powershell.ps1
python scripts/run-tests.py targeted --test test_windows_acceptance_split --jobs 1 --log build/scm-delete-native.log --report build/scm-delete-native.json
```

Optional isolated-copy diagnosis in PowerShell, reading the retained original
without deleting or modifying it. Do not upload original data files:

```powershell
. .\scripts\testing\windows-scm-test-helpers.ps1
$original=Read-Host 'Absolute path to retained retention.json (read only)'
$original=(Get-Item -LiteralPath $original -Force).FullName
$before=(Get-FileHash -LiteralPath $original -Algorithm SHA256).Hash
$copyWorkspace=New-ScmWorkspace ([IO.Path]::GetTempPath())
$folder=Join-Path $copyWorkspace.Root 'data/.application-backups'
[IO.Directory]::CreateDirectory($folder) | Out-Null
$copy=Join-Path $folder 'retention.json'
[IO.File]::Copy($original,$copy)
try {
    Remove-ScmTestEntry $copyWorkspace (Get-Item -LiteralPath $copy -Force)
    if ((Get-FileHash -LiteralPath $original -Algorithm SHA256).Hash -ne $before) { throw 'Original file changed; preserve evidence.' }
    Invoke-ScmCleanupWorker $copyWorkspace
    Write-Host 'Isolated-copy deletion passed; original retained.'
} catch {
    Write-Warning ('Isolated-copy failure; preserve workspace: '+$copyWorkspace.Root)
    throw
}
```

This is not native SCM acceptance. A full native run must still complete cleanup
and publish/read back the receipt. The 120-second deadline and no-existing-service
guard remain unchanged; application backup-retention behavior was not modified.

### PowerShell 5.1 information-stream serialization

Native follow-up showed that `-OutputFormat Text` still permits redirected
Write-Information records to appear as CLIXML on stderr. The runner now renders
recognized CLIXML frames to message text while preserving ordinary stderr before,
between and after them. Information/warning/error text remains; cosmetic progress
records and user/computer serialization metadata are omitted. It never deserializes
arbitrary objects: XML parsing prohibits DTD/entity resolution, bounds input size
and rejects unknown or unrenderable data. Malformed capture fails acceptance even
when the child exits zero; handle disposal is unconditional. This does not change
exit codes, deletion, ownership, timeout or evidence gates.

Rerun the focused process/output test, then the module, without starting SCM:

```powershell
python scripts/run-tests.py targeted --test test_windows_acceptance_split.EvidenceHostTests.test_owned_process_success_failure_timeout_and_missing_exit_code --jobs 1 --log build/scm-output-focused.log --report build/scm-output-focused.json
python scripts/run-tests.py targeted --test test_windows_acceptance_split --jobs 1 --log build/scm-output-native.log --report build/scm-output-native.json
```

These checks include the unchanged no-CLIXML assertion. Native helper success is
still separate from full SCM cleanup and verified evidence publication.

## Account save and browser authentication diagnosis

This issue is separate from SCM cleanup: Running means the service process is up,
not that a browser's credentials were accepted. A 401 is authentication refusal;
403 is authorization/origin refusal and 429 is sign-in throttling. Keep browser
errors and service logs distinct from native acceptance evidence.

- **Register / save configuration** creates the first administrator only when no
  account store exists. It does not reset existing passwords. Previously an entered
  password was silently ignored and cleared when the store existed. This now
  produces actionable guidance before saving; input is retained on failure.
- **Save account** explicitly creates/updates an account, role or enabled state.
  The form fields are pending edits, not a read-back of a stored account; a checked
  Enabled box alone does not prove an account was saved or is active.
  It now targets `SAP_LENS_USERS_FILE` from this installation's configuration,
  rather than always writing the manager's default path. Other authentication
  modes or missing configured stores are refused, never silently initialized.
- The default account location is the separate protected ProgramData access
  directory, not the application data directory selected for datasets. Changing
  the data directory does not create or select a matching users.json automatically.
- Existing configured account paths are preserved during configuration saves.
  Local service-SID read ACLs are reapplied to a successfully replaced account
  file. The manager's installation ownership guard remains in force.
- Blank password on an **existing** account preserves its salt/hash. New accounts
  require a password. Passwords are sent as UTF-8 JSON on stdin, hashed with salted
  PBKDF2 and atomically persisted; they are not command-line arguments or logs.
- Account-file contents are read on each authenticated request: account/password,
  role and enabled-state updates need no service restart. Listener, authentication
  mode and account-file **path** are startup settings; change configuration only
  while stopped, then start the service. Manual XML edits while running are not
  proof that the active runtime uses those new settings.

Check the manager's displayed authentication mode and its installed
`SAPLensService.xml`: mode must be `users` for these accounts to authenticate.
`basic` is a separate shared credential mode and `local` is loopback access.
Do not paste account files, password hashes, credentials or Authorization headers
into tickets/logs. Usernames and passwords are matched exactly. Basic credentials
may be cached by the browser; close its authentication session when retesting.

Account-store read/validation failures now produce only a category/type warning,
without exception text, usernames, paths or credentials. The 401 response remains
generic to avoid account enumeration. Ordinary wrong passwords and disabled or
unknown accounts remain indistinguishable to the browser. No automatic reset or
account-data migration is performed.

Native source verification, independent of existing service/data:

```powershell
powershell -NoProfile -File .\scripts\check-powershell.ps1
python scripts/run-tests.py targeted --test test_server_setup --test test_server_connection_modes --jobs 1 --log build/service-auth-native.log --report build/service-auth-native.json
```

To compile the manager and its disposable self-test harness only, when the prepared
build-version metadata/.NET Framework prerequisites already exist:

```powershell
$out=Join-Path (Get-Location).Path ('backend\build\auth-manager-check-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $out | Out-Null
.\scripts\build-service-manager.ps1 -OutputDirectory $out
if ($LASTEXITCODE -ne 0) { throw 'Manager compilation/self-test failed.' }
```

These outputs are test-only. Do not replace an EXE inside a verified installed
bundle: its manifest will correctly reject changed bytes. A deployed fix requires
normal verified service packaging and a controlled upgrade preserving data/accounts.
Native GUI, active service configuration, service-SID access and browser sign-in
must still be verified on Windows; Linux/source HTTP tests do not establish them.

A local credential check can use curl's password prompt instead of placing a
password on the command line (use only the trusted URL displayed by the manager):

```powershell
$url=Read-Host 'Configured trusted service URL, including scheme and port'
$name=Read-Host 'Application username'
curl.exe --silent --show-error --user $name --write-out "`nHTTP %{http_code}`n" ($url.TrimEnd('/')+'/api/runtime')
```

No restart or password change is performed by this request. Do not share its
password prompt input or unredacted identity response. Service Running plus 401
alone cannot identify which account store, credentials or browser cache caused it.

## Session-account Service Manager rollout

The session-enabled manager creates a fresh identity store through the packaged
runtime before generating logs/source subdirectories, then starts the same
headless server. It has **First-run activation code** and controlled
**Recover administrator** actions; normal account/password/role editing belongs
in **SAP Lens → Settings → User Management**. **My Profile** manages the signed-in
user's password and sessions. See [application accounts](../getting-started/CONFIGURATION.md#application-accounts-session-authenticated-servers).

Existing service configurations retain their selected authentication mode and
account-file location when technical settings are saved. The application account
migration remains a required separate rollout gate; saving configuration does
not reset or silently replace legacy credentials. The old account instructions
above describe legacy packages and remain historical compatibility guidance.
A fresh session installation requires HTTPS for remote passwords; unencrypted
HTTP is restricted to a loopback listener and loopback browser name.

The manager still owns service lifecycle, binding/port, data directory, TLS and
technical diagnostics. Recovery only issues a code for an existing administrator;
it does not create another account or read an old password. The verified bundle
and installation-ownership checks run before activation commands. Native C#
compilation, fresh service registration and browser activation have not yet been
accepted on Windows for this development version.

## Native Windows acceptance checklist: accounts, reviewer identity and encrypted backups

**Status: not executed.** Everything below was implemented and validated on Linux (unit, browser and real Docker containers) and by
contract tests of the PowerShell and C# sources. None of it has run on Windows for this implementation, and the earlier SCM acceptance
is bound to its own package. Record each item as passed only after it ran on Windows from the commit under test.

Safety rules for every step: use a disposable virtual machine or a machine without a production SAP Lens; never point a test at an
existing data directory or register over an installed `SAPLens` service; use synthetic CSV data only; keep the previous acceptance
ZIP, its SHA-256 and `.scm-verification.json` untouched.

Preparation (PowerShell 5.1 or 7, repository root):

```powershell
git fetch origin; git checkout work; git pull --ff-only origin work
.\scripts\build.ps1 -Mode prerequisites
.\.venv\Scripts\python.exe scripts\run-tests.py full --backend --log build\backend-windows.log
.\.venv\Scripts\python.exe scripts\run-tests.py targeted --test test_server --test test_auth_store --test test_persistent_cache
.\scripts\build.ps1 -Mode package -Platform windows -Target installer
.\scripts\build.ps1 -Mode package -Platform windows -Target service
```

| # | Check | How | Expected |
| --- | --- | --- | --- |
| 1 | Desktop starts without sign-in | Install the desktop package on the clean machine and start it | The application opens directly; no sign-in or activation form; `GET /api/auth/state` reports `provider: desktop` |
| 2 | Local reviewer profile | Open a review form; change the name under the reviewer profile; restart | Reviewer field is read-only and shows the profile; the name and its identity survive the restart; earlier reviews keep their recorded name |
| 3 | Session recovery after restart | Leave the window open, exit from the tray, start again, reload the old window | "Restoring workspace" briefly, then the application; no error card and no sign-in form |
| 4 | Service Manager build and start | Build the service target; open the manager from the verified bundle | The manager compiles (.NET Framework `csc.exe`) and shows service, binding, TLS, activation and recovery actions; no account or password editor |
| 5 | Fresh server installation and first administrator | Install into an empty data directory with HTTPS; use **First-run activation code**; open the HTTPS URL | The code is shown once in the manager only; activation creates the administrator; a second use of the code and plain HTTP from another machine are refused |
| 6 | ACLs | `icacls` on `security\accounts.sqlite3`, its folder and the backup key file | Inheritance removed; only SYSTEM, Administrators and `NT SERVICE\SAPLens` (read for the key); no Users, Everyone or Authenticated Users |
| 7 | Administrator recovery | **Recover administrator** in the manager for the existing administrator | Sessions of that account end; the one-time code sets a new password under account recovery; the account identity and audit history are unchanged; no new account appears |
| 8 | Migration and rollback | On a copy of a legacy installation (individual accounts, and separately shared password) run the stopped migration from the manager | Accounts, roles and disabled state preserved; shared password is not converted (a recovery code is issued); an encrypted pre-migration snapshot exists; a forced failure leaves the legacy files and data unchanged |
| 9 | Encrypted backup, key export, restore | Create a backup; export the key; restore into an empty data directory on the same and on a second machine with the exported key | `.slbak` archive; restore needs confirmation; accounts, roles, branding, settings, periods and decisions return; sessions do not; a wrong key or a modified archive is refused and leaves the target empty |
| 10 | SCM lifecycle | `.\scripts\test-server-service.ps1 -Bundle <verified bundle or ZIP>` in an elevated shell with no `SAPLens` service | Install, start, health, authenticated session checks, stop and uninstall pass; a new `.scm-verification.json` is written for this package only |
| 11 | Installer isolation and cleanup | Install and uninstall the desktop installer and the service package on the disposable machine | No file outside the installation and data directories; uninstall keeps data; no leftover service, scheduled task or firewall rule beyond what the guide documents |
| 12 | Preservation | Before and after items 8 and 9 compare accounts, review history, SoD decisions, periods and audit entries | Counts and identifiers equal; historical reviewer names unchanged; nothing rewritten in frozen periods |
| 13 | Unified build directory | Build Desktop, then Server (and separately Server, then Desktop) for the same commit: `.\scripts\build.ps1 -Mode build -Platform windows -Target desktop` and `-Target service` | One `dist\<version>-<commit12>\`; `manifests\` has one record per target; `SHA256SUMS.txt` lists every archive (`Get-FileHash` equals each row); no earlier artifact, manifest or `.scm-verification.json` changed |
| 14 | Desktop artifact identity | Run the Smoke stage after a Server build; then `scripts\test-windows-exe.ps1 -IdentityPath dist\<dir>\manifests\desktop-build-manifest.json` against the extracted EXE | Passes using `backend\build\artifact-identity\<sha256>.json`; a copy of the EXE with one byte changed is refused with "No build identity is bound" |
| 15 | Service Manager compiles | `.\scripts\build-service-manager.ps1` (or the Server build) | `csc.exe` compiles without a missing-reference error for `RSACng` (System.Core) and the `--self-test` run passes: 3072-bit key, validity period, loopback HTTP rule |
| 16 | Default HTTPS certificate | Register with the default mode and no certificate supplied; start the service; open the HTTPS URL | Registration succeeds with no `EE_KEY_TOO_SMALL`; `openssl x509 -text` or `certutil -dump` shows RSA 3072 and every enabled name (IPv4 and IPv6) in the SAN; the service starts |
| 17 | Key and certificate ACLs | `icacls` on `SAP Lens Server Access\server-*.key` and `.crt` | Inheritance removed; the private key is readable only by SYSTEM, Administrators and `NT SERVICE\SAPLens` |
| 18 | HTTP rule and failed Save | Choose Local access (HTTP) with `0.0.0.0`, then `::`, a LAN address and a non-local name; then force a failure (for example an unreadable custom key) on an installed, stopped service | Each HTTP attempt is refused naming the field before anything is created; after the failure the old `SAPLensService.xml` is unchanged and no new `server-*`, backup key or first-run data folder remains |

Also confirm on Windows the two lifecycle fixes that only Windows can show: the desktop build passes the `PackagingBackend` stage
(no `WinError 32` on `accounts.sqlite3`), and the complete backend suite finishes without teardown `PermissionError`.
