# Windows deployment: SSH-driven test server and installers

How the SAP Lens .NET server is built, validated and deployed on a Windows test host from Linux over SSH, how an earlier `SapLens2` service is
migrated to `SapLens`, and how the Desktop and Server installers are built. Every value below is an example (`192.0.2.0/24`, `lens.example.com`,
`deployer`, `C:\Users\example`); real host names, addresses, paths and credentials stay in the host's own configuration file and are never committed.

Status: deployment state-machine tests use mocked SCM/network operations (Pester); SSH tests use a fake SSH (Bash). **Native Windows acceptance is pending**; see
[Acceptance checklist](#acceptance-checklist-windows-pending). Nothing here claims that a Windows run passed.

## Components

| Path (under `backend/`) | Role |
| --- | --- |
| `scripts/deploy/deploy-windows.sh` | Linux entry point. Validates input, sends one PowerShell bootstrap over SSH (`-EncodedCommand`), keeps a local log, maps exit codes |
| `scripts/deploy/Deploy-SapLens.ps1` | Windows entry point (Windows PowerShell 5.1 and PowerShell 7): actions, elevation and `-Yes` checks, result line `SAPLENS-RESULT: <json>` |
| `scripts/deploy/SapLens.Deploy.psm1` | Deployment state machine: commit lock, isolated worktree build, release verification, backup, service control, rollback, recovery, service migration |
| `scripts/deploy/deploy.example.json` | Configuration template (copy it outside the repository) |
| `installer/SapLens-Desktop.iss`, `installer/SapLens-Server.iss`, `scripts/build-installers.ps1` | Inno Setup installers and their build script |
| `scripts/tests/SapLens.Deploy.Tests.ps1`, `scripts/tests/deploy-windows.test.sh` | Pester (mocked operating system) and Bash (fake SSH, real PowerShell) tests |

The bootstrap resolves the branch or commit **on the Windows host**, locks the full SHA, extracts the deployment scripts of exactly that commit with
`git archive` and runs them. A developer checkout is never copied to the host. Commits from before the rename (with `Deploy-SapLens2.ps1` and
`SAPLENS2-RESULT`) still run.

Exit codes: `0` success, `1` failed (nothing changed, or rolled back and ready again), `2` refused before any change, `4` manual action required
(`RECOVERY-REQUIRED.txt` in the run folder), `64` invalid usage (Linux side, SSH never called), `255` SSH failure, `130` interrupted locally.

## Prerequisites on the Windows host

1. **OpenSSH Server** (Windows optional feature) with key authentication only:
   ```powershell
   Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
   Set-Service sshd -StartupType Automatic; Start-Service sshd
   # Administrators: the public key goes into C:\ProgramData\ssh\administrators_authorized_keys (owner SYSTEM/Administrators only)
   icacls C:\ProgramData\ssh\administrators_authorized_keys /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"
   ```
   Set `PasswordAuthentication no` in `C:\ProgramData\ssh\sshd_config` and restart `sshd`. PowerShell remoting (WinRM) is not used and needs no change.
2. An **administrator account** for SSH (deploy, install, rollback and recover need elevation; status, health, build and dry-run do not change the service).
3. **Git**, **.NET SDK 10** and **Node.js 24 or 25** on `PATH` (the release builder builds the React UI and runs the tests).
4. A **clone of the repository** whose `origin` carries `experiment/dotnet-backend` (for example `C:\Users\example\Git\sap-lens`). The deployment
   never changes its checkout: builds use isolated worktrees under `WorkRoot`.
5. The **TLS certificate** (`.pfx`) and a **password file** readable by administrators, outside the repository and outside the data directory.

On Linux: `ssh`, `bash`, `iconv`, `base64` and an SSH key or agent for the host (`BatchMode=yes`: no password is ever asked for or passed).

## Configuration

Copy `backend\scripts\deploy\deploy.example.json` to a folder outside the repository and edit it. Lookup when `-ConfigFile`/`--config` is not given, first
match wins: `$env:SAPLENS_DEPLOY_CONFIG`, `$env:SAPLENS2_DEPLOY_CONFIG`, `C:\sap-lens\deploy\deploy.local.json`, `C:\saplens\deploy.local.json`, `C:\saplens2\deploy.local.json`.

| Setting | Default | Notes |
| --- | --- | --- |
| `RepositoryPath` | required | The clone on the host |
| `WorkRoot`, `ReleasesRoot`, `BackupRoot` | `<config folder>\deploy`, `\releases`, `\predeploy-backups` | An existing `C:\saplens2\deploy.local.json` therefore keeps its `C:\saplens2\...` folders |
| `ServiceName`, `ServiceAccount` | detected | Leave both out: `SapLens` if it exists, else an existing `SapLens2`, else `SapLens` for a new installation. Account `NT SERVICE\<name>` |
| `ListenAddress`, `Port` | required | The server's HTTPS endpoint (`--listen`, `--port`) |
| `AllowedHosts`, `TrustedProxies` | `[]` | `--allowed-hosts` (every name the browser uses) and `--trusted-proxies` (only the reverse proxy's address) |
| `DataDirectory`, `CertificatePath`, `CertificatePasswordFile` | required | Absolute paths outside the release and the repository |
| `ReadyTimeoutSeconds`, `StopTimeoutSeconds` | 120, 90 | Readiness wait after start; graceful stop wait (the service is never killed) |

Unknown settings, relative paths and invalid ports are refused. The file holds paths, addresses and host names only: the certificate password stays in
its file, which only the server reads, and is never on a command line.

## Modes

```bash
D=backend/scripts/deploy/deploy-windows.sh
H=(--host 192.0.2.10 --user deployer --repo 'C:\Users\example\Git\sap-lens')
$D "${H[@]}" --mode status                       # service model, name, state, linked release, readiness, journal
$D "${H[@]}" --mode health                       # /health/ready and /product-version.json of the running server
$D "${H[@]}" --mode build --tests focused        # lock, build in a worktree, test, verify, publish to ReleasesRoot; no service change
$D "${H[@]}" --mode dry-run                      # lock the commit and print the plan; no build, backup or service change
$D "${H[@]}" --mode deploy --tests focused --yes # build, test, verify, back up, stop, switch, start, verify; roll back when safe
$D "${H[@]}" --mode deploy --commit 1a2b3c4d --tests full --yes
$D "${H[@]}" --mode rollback --yes               # previous release, only when it can open the current data
$D "${H[@]}" --mode recover --yes                # finish an interrupted deployment (Ctrl+C, dropped SSH)
# Directory migration uses the explicit local PowerShell actions below; no SSH shortcut is implied.
```

`--tests focused` runs the deployment-relevant test classes (startup, API, network, reverse proxy, sessions, accounts, persistence, backups,
maintenance commands, v1 compatibility, versioning, v1 migration); `--tests full` runs the whole suite once. Tests run once per build, inside the
release builder, never again during the deployment. `main` and `work` are refused; a `--commit` must be on the pushed branch.

### Deployment sequence

The running service keeps serving while the release is built and tested. Then, each step journaled in `WorkRoot\deployment-journal.json` under an
exclusive lock:

1. Refuse when an earlier run was interrupted (run `recover` first), the service is not installed (unless `--first-install`), or the service runs
   another executable (unless `--adopt-service`, below).
2. `--schema-info` of the new release: refuse data written by a newer build.
3. Encrypted pre-deployment backup with the current release (`--backup-local`), then `--backup-verify`. No verified backup, no stop.
4. Stop through the Service Control Manager (graceful; imports are handed back). A service that does not stop in time is reported (exit 4), never killed.
5. Switch `ReleasesRoot\current` (a junction) to the new release, start, and wait for the service's own process to listen and `/health/ready` to answer 200.
6. Compare `/product-version.json` with the expected version and commit. Only then is the release kept (`complete`).
7. On any failure: roll back to the previous release when it can open the data (`--schema-info` of the previous build, or no migration applied
   during the run for older builds). Otherwise stop, keep the service stopped and write exact choices to `RECOVERY-REQUIRED.txt` (exit 4). An older
   database is never restored automatically.

### Release packages and integrity

Implemented and tested on Linux (Pester `verify-release.Tests.ps1`, `SapLens.Migration.Tests.ps1`); awaiting Windows acceptance.

| Kind | Where | Contents | Verify with |
| --- | --- | --- | --- |
| Full release | Builder output (`WorkRoot\builds\<sha12>\SAP-Lens-…-win-x64`, or `build-release.ps1 -Output`) | Every artifact in `build-manifest.json`: `server\`, `desktop\`, `symbols\`, `README.txt`, `Service-Manager.ps1` | `verify-release.ps1 -ReleasePath <folder>` |
| Server deployment package | `ReleasesRoot\SAP-Lens-…-win-x64` (what the service runs) | Every artifact except `desktop\**` and `symbols\**`, the unchanged `build-manifest.json` and `SHA256SUMS`, and `deployment-package.json` | `verify-release.ps1 -ReleasePath <folder> -Scope Server` |

- `build-manifest.json` and `SHA256SUMS` always describe the full build and are **never rewritten** in a package. `deployment-package.json`
  declares the package: kind `server`, the release name, the SHA-256 of `build-manifest.json`, and the exact omitted paths.
- `-Scope Server` allows only `desktop\**` and `symbols\**` to be absent and names every omitted file. Any other missing, changed or added file,
  a changed manifest, or a declaration that disagrees with the folder fails. The default full scope refuses a package outright.
- Publication (`Build` and `Deploy`) assembles the package in `ReleasesRoot\.staging\<name>`, verifies it there and only then moves it into
  place. A package that fails verification is never published; its staging copy is kept for inspection and blocks the next attempt until an
  operator removes it. An existing folder of the same commit is reused only if it verifies; it is never overwritten or repaired.
- `Deploy -Release <folder>` and the migration preflight (`source_release`) verify with `-Scope Server` before anything else.
- **Packages published before this contract** (for example the `SapLens2` release of commit `5096382`) contain `server\`, `README.txt`,
  `build-manifest.json` and `SHA256SUMS` only. They verify with `-Scope Server` as *undeclared*: every server artifact and the manifest still
  have to match the recorded checksums, and the absent Desktop and symbol files are listed by name. The default full scope correctly reports them
  missing. Do not add, edit or regenerate files in such a folder. If the full build is needed (Desktop, symbols), use the builder output under
  `WorkRoot\builds\<sha12>` when it still exists (verify it with the full scope), or rebuild that commit into a new folder.
- A package published by an older script from a build that contained `Service-Manager.ps1` lacks that file and fails `-Scope Server`: republish
  it from its verified full build with the current scripts.

## First deployment

**Host with a hand-installed server** (for example an earlier `SapLens2` service started from a build folder):

```bash
$D "${H[@]}" --mode status                                  # service_model windows-service, binary_path_matches false
$D "${H[@]}" --mode dry-run
$D "${H[@]}" --mode deploy --tests focused --adopt-service --yes
```

Adoption requires the service's arguments to be equivalent to the configuration (data directory, network mode, listen address, port, allowed
hosts, trusted proxies, certificate and password file); otherwise it is refused before any change, listing each difference. The comparison is
semantic: option order and the order of entries in `--allowed-hosts`/`--trusted-proxies` do not matter, host names and Windows paths compare
without regard to case, addresses as IP addresses. A missing, repeated, unknown or valueless option is always a difference. The original command line is recorded and restored if the adopted deployment fails.

**New host:** `--mode build`, then `--mode deploy --first-install --yes` (installs the `SapLens` service with automatic start, its virtual account,
restart on failure and least-privilege grants), then `--mode status`.

## Migrating SapLens2 to SapLens

This is an explicit, separate maintenance operation. Do not run it on the working VM during development. Native acceptance must pass first
on [unique synthetic fixtures](WINDOWS_TEST_VM.md#isolated-native-migration-acceptance). Production cutover still needs authorization.
An already activated v1 data migration is preserved; do not preview/run/activate it again and do not auto-confirm its functional acceptance.

| Purpose | Canonical location |
| --- | --- |
| Verified immutable releases / current junction | `C:\sap-lens\releases` / `C:\sap-lens\releases\current` |
| Deployment tools, private config and mirrored journal | `C:\sap-lens\deploy` |
| Mutable application data | `C:\ProgramData\SapLens\data` |
| Existing TLS certificate and password copy | `C:\ProgramData\SapLens\tls` |
| Existing host key and recovery copies | `C:\ProgramData\SapLens\backup` |
| Verified pre-deployment/migration archives | `C:\ProgramData\SapLens\predeploy-backups` |

Prepare two private JSON configurations **outside the new target roots**. Source explicitly names `SapLens2` and its actual paths, arguments
and account. Target explicitly names `SapLens` and the canonical paths above. Preserve `LocalSystem` when the source uses it; a source virtual
account maps to `NT SERVICE\SapLens`. Custom credential accounts are refused. Never switch the account implicitly. Preserve the exact listen
address, port, allowed hosts, trusted proxies and TLS filenames; no certificate regeneration, key rotation, proxy or firewall change occurs.
Target roots must not exist, must be disjoint local NTFS directories, and must have private parent ACLs and adequate free space.
Prepare only their containing application/persistent roots with administrator/SYSTEM access before preflight (`-Action ProtectAcl`, see
[NTFS permissions](#ntfs-permissions)); a public parent that lets ordinary users read or create children is refused. Staging creates its work directory exclusively and never adopts a directory that appeared after inspection.

Use the **new verified release's** server executable as an inspector. Its read-only `--inspect-data` advertises verified upload-rebasing support;
older inspectors are refused before service control. The inspector is never installed by migration: the
source's verified release is copied unchanged. Legacy source releases need `--schema-info`, `--backup-local` and `--backup-verify` support.
The inspector copies database/WAL/journal files into scratch and opens only those copies; it never opens live source SQLite. SHM is rebuilt in
scratch because Windows locks the live WAL index. Inspection refuses concurrent changes; repeat at a quiet time, without weakening checks.

```powershell
$entry = '.\backend\scripts\deploy\Deploy-SapLens.ps1'
$source = 'C:\private-operations\source.local.json'
$target = 'C:\private-operations\target.local.json'
$inspector = 'C:\private-operations\verified-release\server\SapLens.Api.exe'
# Read-only: inspect result.safe and every check; no backup, journal, ACL or service change.
& $entry -Action PreflightMigration -ConfigFile $source -TargetConfigFile $target -InspectorExecutable $inspector
# ONLY in an explicitly authorized maintenance window after isolated acceptance:
& $entry -Action MigrateService -ConfigFile $source -TargetConfigFile $target -InspectorExecutable $inspector -Yes
& $entry -Action VerifyMigration -ConfigFile $source
& $entry -Action Status -ConfigFile 'C:\sap-lens\deploy\deploy.local.json'
```

Preflight checks the actual SCM arguments/account/listener PID, readiness and running SHA/version against the verified release manifest,
SQLite integrity/schema compatibility, private ACLs, TLS/private key/password validity, host/recovery key location, history and recovery state.
Environment overrides and pending deployment, restore or v1 activation/rollback block migration. CSV source paths within the retiring
executable/tool installation also block it: re-import from an approved durable external location first, rather than blindly rewriting settings.
Recognized private uploads (`data/sources/<source>-<16 hex>.csv`) are recorded for checked rebasing in the staged copy; preflight never changes them.

The existing deployment framework serializes operations with a host mutex. It durably journals intent before service operations and mirrors
`migration-journal.json` to both work roots. It takes an online encrypted backup, verifies it, stages release/TLS/key files, disables and stops
the source, takes a final verified offline backup, copies all data and history with NTFS security, and verifies content/ACL inventories.
The copied key pointer and recognized private-upload paths are updated. The copy-only maintenance command requires the original data root, expected
database SHA-256 and an explicit migration-copy flag; it compares copied CSV bytes, keeps external locations unchanged, advances only the settings
revision and preserves immutable source/review records. Missing CSVs never erase valid imported records. It verifies decryption using the copied key,
creates the target service with manual start, verifies
readiness/SHA/version, then enables automatic start and publishes the canonical config. `SapLens2` remains stopped and disabled; its service,
data, keys, TLS and releases are never deleted. Target partial copies are retained on failure. There is no automatic cleanup.

After interruption use `Status`, inspect both journals, then explicitly recover:

```powershell
& $entry -Action RecoverMigration -ConfigFile $source -Yes
# Explicit rollback request after completed cutover; subject to the same no-lost-writes proof:
& $entry -Action RollbackMigration -ConfigFile $source -Yes
```

Recovery first disables/stops the owned target. It returns to the source only when inventories prove no writes would be discarded.
After target startup, even normal log/database changes can make automatic rollback unsafe. Exit `4` and journal `recovery` instructions mean
**manual recovery required**: retain and back up both trees, reconcile into a NEW directory, and enable only the chosen service. Recovery never
restores over live data, deletes staging, guesses ownership or starts the source after a failed target stop. Completed reruns verify status.

Subsequent Build & Replace uses the published **target** config and the usual `Deploy`/`Rollback` actions, retaining backups and data. The old
source config is blocked. `VerifyMigration` follows the current release after later deployments, reporting both current and migration commits.
Legacy cleanup needs separate authorization after acceptance and backup verification; once the retained old service is removed, use ordinary
`Health`/`Status` rather than the migration verifier, which deliberately requires the retained rollback service.

## NTFS permissions

Implemented and tested on Linux with synthetic ACLs (Pester `SapLens.Acl.Tests.ps1`, `SapLens.Migration.Tests.ps1`); **awaiting Windows
acceptance** (no real ACL was read or changed from this environment).

**Broad principals** (matched by well-known SID, so localized account names do not matter): Everyone `S-1-1-0`, Authenticated Users
`S-1-5-11`, Users `S-1-5-32-545`, Interactive `S-1-5-4`, Network `S-1-5-2`, Anonymous Logon `S-1-5-7`, Guests `S-1-5-32-546`, Domain Users and
Domain Guests (`S-1-5-21-…-513`/`-514`). An allow rule counts when it applies to the object itself or, on a folder, to new children
(container/object inherit, also inherit-only): that is what a folder created later inherits. Deny rules and individual accounts are not findings.
*Read* is ReadData/ListDirectory, GENERIC_READ or GENERIC_ALL; *write* is any of WriteData/CreateFiles, AppendData/CreateDirectories, WriteEA,
WriteAttributes, DeleteSubdirectoriesAndFiles, Delete, ChangePermissions, TakeOwnership, GENERIC_WRITE or GENERIC_ALL.

| Class | Paths (source configuration, then migration target) | Broad read | Broad write | Required identities |
| --- | --- | --- | --- | --- |
| Private | Data directory and every descendant; pre-deployment backups; TLS folder (certificate, password file); the folder of the host backup key; deployment state (`WorkRoot`) | refused | refused | SYSTEM and Administrators full control; the service's virtual account modify on data, read on TLS and key (an `NT SERVICE\…` account only: `LocalSystem` is SYSTEM) |
| Binaries | `ReleasesRoot`, the configuration file, the folder that holds it (for example `C:\saplens2`) | allowed (read and execute) | refused | SYSTEM and Administrators full control; service read and execute on `ReleasesRoot` |
| Target parent | The folder that will hold a new target root (`C:\ProgramData\SapLens`, `C:\sap-lens`); while missing, its nearest existing ancestor is judged | refused when it holds a private target | refused | SYSTEM and Administrators |

`C:\ProgramData` itself grants Users read and "create folders" to new children by design. It is **never changed**: `ProtectAcl` creates
`C:\ProgramData\SapLens` with a protected DACL instead. The preflight reports every finding with path, role, principal, access, rights mask,
inherited or explicit, and what it applies to.

### Audit and remediation

```powershell
$entry = '.\backend\scripts\deploy\Deploy-SapLens.ps1'
# Read-only: every finding for the source state and the target parents (exit 0 safe, 2 unsafe). Changes nothing.
& $entry -Action AuditAcl -ConfigFile $source -TargetConfigFile $target
# Explicit, approved remediation in an elevated session (does not stop or reconfigure the service):
& $entry -Action ProtectAcl -ConfigFile $source -TargetConfigFile $target -Yes
# Undo exactly what ProtectAcl changed:
& $entry -Action RestoreAcl -ConfigFile $source -AclBackup <WorkRoot>\acl-backups\<UTC time> -Yes
```

`ProtectAcl` changes only paths with findings, and missing target parents:

1. Creates `WorkRoot\acl-backups\<UTC time>` with a protected DACL (SYSTEM, Administrators) and saves every affected ACL with its
   descendants (`icacls <path> /save <file> /T /C`), plus `acl-backup.json` listing what was saved and what will be created.
2. For each path: `icacls /inheritance:r` with SYSTEM and Administrators full control (and the service's virtual account where the table says
   so), removes explicit grants to the broad SIDs, grants authenticated users read and execute again on release folders only, and resets the
   descendants of private folders to inherit (their earlier explicit entries are in the backup).
3. Creates missing target parents with the same protected DACL. Target roots themselves are never created (the migration requires them new).
4. Audits again and returns the result; exit 2 when anything is still unsafe.

It refuses drive roots, `%ProgramData%`, `%ProgramFiles%`, the Windows folder, `%SystemDrive%\Users` and user profiles. The running service
keeps its access (SYSTEM for `LocalSystem`, its own grant otherwise), so it is not stopped. Before running it on the production host: take a
verified application backup, run `AuditAcl` and review each listed path, run in a quiet window, and keep the printed backup folder.
`RestoreAcl` replays the saved ACLs newest first (`icacls <parent> /restore <file>`) and keeps folders `ProtectAcl` created (empty and protected).

## Service model and permissions

- **Managed or not:** a service counts as managed (`binary_path_matches` in status) when its executable is the release link's
  `current\server\SapLens.Api.exe` and its arguments are equivalent to the configuration. Both are compared normalized (quotes, separators and
  case of the path; option and list order of the arguments, as in [adoption](#first-deployment)), never as raw strings: Windows can store an
  equivalent command line differently (for example without the quotes around the executable when Windows PowerShell 5.1 passes `binPath=` to
  `sc.exe`). A real difference in any argument still reads as not managed.

- One service, never two: installing `SapLens` while `SapLens2` exists (or the reverse) is refused.
- Account: the service's own virtual account (`NT SERVICE\<name>`), no password. Grants are added, never removed: modify on the data directory
  (inherited), read and execute on `ReleasesRoot`, read on the certificate, its password file and the backup key file.
- Command line (no secret): `SapLens.Api.exe --data-dir … --network --listen … --port … --allowed-hosts … --cert … --cert-password-file … [--trusted-proxies …]`.
  TLS, the Host allow-list, Origin/CSRF checks and the trusted-proxy restriction are the server's own and unchanged by the deployment.
- Processes: only the service is stopped, through the SCM. A port held by another process (for example `start-server-test.ps1`) is reported and left alone.

## Logs and artifacts

| Where | What |
| --- | --- |
| `${XDG_STATE_HOME:-~/.local/state}/saplens-deploy/<UTC>-<mode>-<host>.log` (Linux) | Complete remote output of each run |
| `WorkRoot\runs\<run id>\` | `deploy.log`, `build.log`, `RECOVERY-REQUIRED.txt` when needed |
| `WorkRoot\deployment-journal.json`, `WorkRoot\deployment.lock` | Phase history of the last run; one operation at a time |
| `WorkRoot\worktrees\<sha12>`, `WorkRoot\builds\<sha12>` | Isolated build checkouts and builder output |
| `ReleasesRoot\SAP-Lens-<version>-<UTC>-<sha7>-win-x64`, `ReleasesRoot\current` | Verified server deployment packages ([release packages](#release-packages-and-integrity)) and the junction the service runs |
| `ReleasesRoot\.staging\<release>` | Only after a failed publication: the unverified copy, kept for inspection |
| `BackupRoot` | Encrypted, verified pre-deployment backups (`.slbak`) |
| `<DataDirectory>\logs\server-*.log` | The server's own log when it runs as a service |

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Exit 64, nothing sent | Fix the option named in the message (`--help`) |
| Exit 255 / `No result line` | SSH or PowerShell failed: check `ssh -o BatchMode=yes deployer@host`, the key in `administrators_authorized_keys`, and `powershell.exe` on the host |
| `Deployment configuration not found` | Create the file in one of the lookup locations or pass `--config` |
| `needs an elevated session` | Use an administrator account for SSH |
| `runs …, not the managed release link` | First deployment: `--adopt-service`; arguments must match the configuration |
| `interrupted in phase …` | `--mode status`, then `--mode recover --yes` |
| `did not stop within …` (exit 4) | Investigate the service (Event Viewer, `<data-dir>\logs`); it was not killed. Retry when it is stopped |
| `Rollback is not safe` (exit 4) | Read `RECOVERY-REQUIRED.txt`: fix forward, or restore the pre-deployment backup into a new data directory with the previous release |
| Windows PowerShell 5.1 `[System.Char] … 'Trim'` | Fixed in c772eef; deploy a commit from after it |

## Installers

Built on Windows with Inno Setup 6 from a release folder written by `build-release.ps1`:

```powershell
cd C:\Users\example\Git\sap-lens\backend
powershell -NoProfile -File .\scripts\build-release.ps1 -Output C:\saplens\builds
$release = Get-ChildItem C:\saplens\builds -Directory -Filter 'SAP-Lens-*-win-x64' | Sort-Object Name | Select-Object -Last 1
powershell -NoProfile -File .\scripts\build-installers.ps1 -ReleasePath $release.FullName -Output C:\saplens\installers
```

| Installer | Scope and folder | Behavior |
| --- | --- | --- |
| `SAP-Lens-<version>-Setup.exe` (Desktop) | Per user, `%LOCALAPPDATA%\Programs\SAP Lens Desktop` | Own AppId; SAP Lens v1 (`%LOCALAPPDATA%\Programs\SAP Lens`, data `%LOCALAPPDATA%\SAP Lens`) is detected and left untouched. Requires WebView2. Waits for a running Desktop (it is never closed by Setup). Refuses downgrades. Data in `%LOCALAPPDATA%\SAP Lens Desktop` (or a kept `SAP Lens 2 Prototype` folder) is never deleted |
| `SAP-Lens-Server-<version>-Setup.exe` | Machine, `%ProgramFiles%\SAP Lens Server\server` | Own AppId. Never creates, reconfigures or deletes a service and never touches data. On upgrade, a `SapLens`/`SapLens2` service running from this folder is stopped with `net stop` and started again; uninstall is refused while one runs from it. Refuses downgrades |

Silent: `SAP-Lens-<version>-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=C:\saplens\install.log`. Installers are unsigned; signing,
publishing and tagging are separate, authorized release steps. Upgrades replace executables only: the server and Desktop back the database up
themselves before any schema migration.

## Local Service Manager

The release includes `Service-Manager.ps1` beside `server/`; the Server installer adds a local administration shortcut. It invokes the packaged
server binary directly, needs no SDK, opens no listener and never controls the service. Select the exact data directory and executable explicitly
when operating an older installation. Key export/provisioning stays local-only; no browser export endpoint exists.

```powershell
$manager='C:\sap-lens\releases\current\Service-Manager.ps1'
$exe='C:\sap-lens\releases\current\server\SapLens.Api.exe'
$data='C:\ProgramData\SapLens\data'
& $manager -Action Status -DataDirectory $data -Executable $exe
# Elevated, explicit local operations. Export refuses an existing destination.
& $manager -Action ExportKey -DataDirectory $data -Executable $exe -Path 'D:\private-recovery\host-copy.key' -Yes
& $manager -Action VerifyKey -DataDirectory $data -Executable $exe -Path 'D:\private-recovery\host-copy.key' -Yes
# One-use codes are shown locally; never transcript or redirect these commands:
& $manager -Action ActivationCode -DataDirectory $data -Executable $exe -Yes
& $manager -Action RecoveryCode -DataDirectory $data -Executable $exe -Username 'existing-admin' -Yes
```

`CreateKey` is for an unconfigured installation only and never replaces a configured key. Export to separately secured recovery storage,
then verify that copy before enabling automatic backups. Protect the full key directory; keep host and recovery keys out of data/releases/Git.
For virtual accounts provision before service installation grants read access; existing-service grants require explicit reviewed Reconfigure.
Do not change the service identity, regenerate a live key or weaken ACLs to make a key operation succeed. Accounts activation/recovery uses the
existing one-use-code mechanism; a missing data directory or invalid administrator is refused. The browser can verify an entered recovery copy
only after administrator/current-password reauthentication, with a session-bound one-use proof and CSRF; it cannot export or create the host key.

## Privacy and secrets

- Never commit `deploy.local.json`, certificates, password files, API tokens, backup keys, `.slbak` backups, data directories or real SAP extracts;
  `.gitignore` covers `*.local.json`, `*.key`, `*.pfx`, `*.sqlite3`, `api-token` and `cert-password`.
- Real host names, addresses, user names and paths belong only in the host's configuration and in your SSH configuration (`~/.ssh/config`).
- The scripts print paths, addresses, versions and commits, never a password, token or key. Server logs record method, path and peer, never
  headers, cookies or tokens.
- Before pushing: `python scripts/check-secrets.py` (tracked files) and `git diff --check`.

## Acceptance checklist (Windows, pending)

A controlled procedure for the dedicated Windows VM, in an authorized maintenance window, from an elevated Windows PowerShell 5.1 prompt in the
repository root. Nothing here runs automatically, and every step is **Pending** until its result is recorded. Do not rerun the SAP Lens 1 data
migration that is already activated on the VM; its data and migration backup must stay as they are.

```powershell
$entry = '.\backend\scripts\deploy\Deploy-SapLens.ps1'
$source = 'C:\private-operations\source.local.json'          # the running SapLens2 installation
$target = 'C:\private-operations\target.local.json'          # canonical C:\sap-lens and C:\ProgramData\SapLens roots
$inspector = 'C:\private-operations\verified-release\server\SapLens.Api.exe'
$admin = '.\backend\scripts\Service-Manager.ps1'
```

| # | Step | Command | Pass when |
| --- | --- | --- | --- |
| 1 | Preflight (read-only) | `& $entry -Action Status -ConfigFile $source` and `& $entry -Action PreflightMigration -ConfigFile $source -TargetConfigFile $target -InspectorExecutable $inspector` | `result.safe` true; every check passes; nothing changed (no journal, backup or service change) |
| 2 | Verified backup | Settings > Backup & Restore > Overview > create, then Backup History > verify and download | Archive verified; the download decrypts with `SapLens.Api --backup-verify <file> --data-dir <data>` |
| 3 | Recovery key | `& $admin -Action Status -DataDirectory <source data dir>`, then `-Action ExportKey -Path <new file>` and `-Action VerifyKey -Path <that file>` (same `-DataDirectory`; the default is the canonical `C:\ProgramData\SapLens\data`) | Same fingerprint; the recovery copy verifies; key material never appears in output |
| 4 | Service migration | `& $entry -Action MigrateService -ConfigFile $source -TargetConfigFile $target -InspectorExecutable $inspector -Yes`, then `& $entry -Action VerifyMigration -ConfigFile $source` | `SapLens` running with automatic start; `SapLens2` stopped and disabled, not deleted; verification passes |
| 5 | Startup | `Get-Service SapLens*`; `& $entry -Action Health -ConfigFile 'C:\sap-lens\deploy\deploy.local.json'` | Ready; identity shows version 2.0.0-alpha.1 and the expected commit; `binary_path_matches` true in Status |
| 6 | Functional validation | Sign in through the reverse proxy; open Dashboard, User Access, Account Review, SoD | Same data as before (source revisions, evidence snapshots, review and SoD decision counts unchanged) |
| 7 | Empty import guard | Data Sources > upload a header-only copy of a source and confirm the anomaly | Refused: "contains no usable records"; previous records remain |
| 8 | Backup after migration | Create, verify and download a backup on the migrated installation | Verified archive; downloadable |
| 9 | Automatic backups | Scheduling: daily (and weekly) at a near-future local time with an explicit zone; wait for the slot; restart the service once | One verified automatic archive per slot; next run shown in the chosen zone; settings survive the restart |
| 10 | Upgrade confirmation | Settings > Storage: run the integrity check, then confirm the upgrade | Confirmation recorded; the migration backup still exists |
| 11 | Rollback rehearsal | `& $entry -Action RollbackMigration -ConfigFile $source -Yes` only if step 4-6 failed; otherwise `& $entry -Action Rollback -ConfigFile 'C:\sap-lens\deploy\deploy.local.json' -Yes` after a later update deploy | The previous release or service returns ready; no data is overwritten |
| 12 | Installers | `build-installers.ps1`, then both setups interactively and with `/VERYSILENT` | Desktop starts as "SAP Lens"; Server upgrade restarts its service; uninstall keeps data |
| 13 | Desktop self-check | `"%LOCALAPPDATA%\Programs\SAP Lens Desktop\SapLens.exe" --self-check` | Exit 0; log written |

Also run the native test suites once on the VM: `Invoke-Pester backend\scripts\tests` (includes the Windows-only migration tests that Linux
skips) and `dotnet test backend\tests\SapLens.Tests -c Release`.

## Post-promotion infrastructure verification

Active tooling resolves the current checkout under `backend/`; only the historical
commit resolver recognizes `experiments/dotnet-backend` for older releases. No
service executable path, installed release, data directory, TLS setting, recovery
key or service name is changed by this infrastructure stabilization. Existing
semantic service-command comparison, manifest hashes, verified backup before
replacement and rollback gates remain in place. Frontend and backend now share
`backend/product-version.json`; no product version was incremented.

Safe native follow-up commands from the repository root (no service operations):

```powershell
git switch experiment/dotnet-backend
git pull --ff-only origin experiment/dotnet-backend
node scripts/product-version.mjs
powershell -NoProfile -File .\backend\scripts\check-powershell.ps1
pwsh -NoProfile -Command "Invoke-Pester -Path backend/scripts/tests -CI"
dotnet build backend/SapLens.slnx -c Release
dotnet test backend/tests/SapLens.Tests -c Release --no-build --filter "FullyQualifiedName~StartupTests|FullyQualifiedName~NetworkTests|FullyQualifiedName~ReverseProxyTests|FullyQualifiedName~DesktopLocationTests|FullyQualifiedName~InstallerTests|FullyQualifiedName~VersioningTests"
```

Pester requires version 5.7.1 (`Install-Module Pester -RequiredVersion 5.7.1 -Scope
CurrentUser` through the approved repository, if not already available). Respect
corporate signing/execution policy; do not disable WDAC or bypass script policy.
These checks do not certify native service restart, Desktop/WebView2, installer,
ACL/firewall, backup recovery or real-data migration acceptance. Those remain the
separate existing checklist above, and must use disposable installations/data.
The running service and all existing release/backup directories must stay untouched.
