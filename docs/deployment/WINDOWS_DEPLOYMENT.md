# Windows deployment: SSH-driven test server and installers

How AuthLens is installed, updated and restored as the `AuthLens` Windows service under one installation root (`C:\ProgramData\AuthLens`), driven
from Linux over SSH or locally, how a SAP Lens installation is migrated (a fresh AuthLens installation plus a restore of a SAP Lens backup), and how
the Desktop and Server installers are built. Every value below is an example (`192.0.2.0/24`, `lens.example.com`, `deployer`, `C:\Users\example`);
real host names, addresses, paths and credentials stay in the host's own configuration file and are never committed.

Status: the deployment state machine is tested with mocked SCM/network operations (Pester), the SSH orchestrator with a fake SSH (Bash), and the
restore of SAP Lens backups into a fresh installation, also on another machine, by the .NET suite (`LegacyRestoreTests`). **Native Windows
acceptance is pending** ([acceptance checklist](#acceptance-checklist-windows-pending)); nothing here has run on Windows from this environment.

## Components

| Path (under `backend/`) | Role |
| --- | --- |
| `scripts/deploy/deploy-windows.sh` | Linux entry point. Validates input, sends one PowerShell bootstrap over SSH (`-EncodedCommand`), keeps a local log, maps exit codes |
| `scripts/deploy/Deploy-AuthLens.ps1` | Windows entry point (Windows PowerShell 5.1 and PowerShell 7): actions, elevation and `-Yes` checks, result line `AUTHLENS-RESULT: <json>` |
| `scripts/deploy/AuthLens.Deploy.psm1` | Install, update and restore: installation layout, commit lock, isolated worktree build, release verification, backup, service control, rollback, recovery |
| `scripts/deploy/AuthLens.Acl.ps1`, `scripts/deploy/AuthLens.Paths.ps1` | NTFS audit and remediation; path safety (no reparse points, disjoint roots) |
| `scripts/deploy/deploy.example.json` | Configuration template (copy it outside the repository) |
| `installer/AuthLens-Desktop.iss`, `installer/AuthLens-Server.iss`, `scripts/build-installers.ps1` | Inno Setup installers and their build script |
| `scripts/tests/AuthLens.Deploy.Tests.ps1`, `scripts/tests/deploy-windows.test.sh` | Pester (mocked operating system) and Bash (fake SSH, real PowerShell) tests |

The bootstrap resolves the branch or commit **on the Windows host**, locks the full SHA, extracts the deployment scripts of exactly that commit with
`git archive` and runs them. A developer checkout is never copied to the host. A commit that predates AuthLens (without
`backend/scripts/deploy/Deploy-AuthLens.ps1`) is refused.

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

Copy `backend\scripts\deploy\deploy.example.json` to `C:\ProgramData\AuthLens\config\deploy.json` (or elsewhere, outside the repository) and edit it.
Lookup when `-ConfigFile`/`--config` is not given: `$env:AUTHLENS_DEPLOY_CONFIG`, then `C:\ProgramData\AuthLens\config\deploy.json`. No other
location, and no configuration of an earlier product, is read.

| Setting | Default | Notes |
| --- | --- | --- |
| `Root` | `C:\ProgramData\AuthLens` | The installation root; every path below defaults to its [layout](#installation-layout) |
| `RepositoryPath` | required | The clone on the host (build time only; nothing runs from it) |
| `WorkRoot`, `ReleasesRoot`, `BackupRoot`, `DataDirectory` | `<Root>\deployment`, `\releases`, `\backups\predeploy`, `\data` | Set one explicitly only to move that path |
| `CertificatePath`, `CertificatePasswordFile` | `<Root>\tls\server.pfx`, `<Root>\tls\cert-password` | Provided by the operator before installing |
| `ServiceName`, `ServiceAccount` | `AuthLens`, `NT SERVICE\AuthLens` | Set only for an isolated test service |
| `ListenAddress`, `Port` | required | The server's HTTPS endpoint (`--listen`, `--port`) |
| `AllowedHosts`, `TrustedProxies` | `[]` | `--allowed-hosts` (every name the browser uses) and `--trusted-proxies` (only the reverse proxy's address) |
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
$D "${H[@]}" --mode restore --backup 'D:\transfer\SAP-Lens-manual-<id>.slbak' --key-file 'D:\transfer\recovery.key' --yes
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

Implemented and tested on Linux (Pester `verify-release.Tests.ps1`); awaiting Windows acceptance.

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
- `Deploy -Release <folder>` verifies with `-Scope Server` before anything else.
- **Packages published before this contract** (for example the `SapLens2` release of commit `5096382`) contain `server\`, `README.txt`,
  `build-manifest.json` and `SHA256SUMS` only. They verify with `-Scope Server` as *undeclared*: every server artifact and the manifest still
  have to match the recorded checksums, and the absent Desktop and symbol files are listed by name. The default full scope correctly reports them
  missing. Do not add, edit or regenerate files in such a folder. If the full build is needed (Desktop, symbols), use the builder output under
  `WorkRoot\builds\<sha12>` when it still exists (verify it with the full scope), or rebuild that commit into a new folder.
- A package published by an older script from a build that contained `Service-Manager.ps1` lacks that file and fails `-Scope Server`: republish
  it from its verified full build with the current scripts.

## Installation layout

One root, `C:\ProgramData\AuthLens` (setting `Root`). Nothing runs from the repository or a build folder; the service runs the verified release
under `releases\current`.

```text
C:\ProgramData\AuthLens\              protected DACL: SYSTEM and Administrators (not inherited from ProgramData)
  releases\<release>\, releases\current   verified server packages and the junction the service runs; service: read and execute
  data\                               authlens.sqlite3, accounts, uploads (sources\), application backups (backups\), logs\; service: modify
  config\deploy.json                  deployment configuration (no secrets)
  tls\server.pfx, tls\cert-password    TLS certificate and its password file; service: read
  keys\                               host backup key (selected with --backup-key use); service: read
  backups\predeploy\                   encrypted, verified pre-deployment backups
  deployment\                         journal, lock, runs (logs), worktrees and builds
```

Adjustments to the originally proposed layout, with the reason: application backups (automatic 90 days, manual until deleted, migration until
confirmed) stay in `data\backups\`, where the server manages and restores them; server logs stay in `data\logs\`; `app\` is used only by the
installer, scripted deployments use `releases\` (versioned, with rollback). A new root is created with its protected DACL by the first
install; an existing root must pass `-Action AuditAcl` (prepare it with `-Action ProtectAcl`, [NTFS permissions](#ntfs-permissions)).

## Install

```bash
$D "${H[@]}" --mode build --tests focused                   # verified release under releases\, no service change
$D "${H[@]}" --mode deploy --first-install --tests focused --yes
$D "${H[@]}" --mode status                                  # service AuthLens running, binary_path_matches true, ready
```

`--first-install` creates the root and its folders, installs the `AuthLens` service (automatic start, `NT SERVICE\AuthLens`, restart on failure,
per-folder grants) and starts it on a new, empty `authlens.sqlite3`. Then create the first administrator (Accounts mode) or restore a backup.
`--adopt-service` remains for a hand-installed `AuthLens` service with equivalent arguments (compared semantically; any difference is refused
before a change). Services of earlier products are never looked at, adopted, stopped or changed.

## Restore

`-Action Restore -Backup <file.slbak> [-KeyFile <recovery key>]` (`--mode restore --backup ... --key-file ...`) restores an AuthLens or SAP Lens
backup into this installation: the key that sealed it is copied into `keys\` (never overwritten) and selected, `AuthLens.Api --restore` stages and
validates the archive (authenticated decryption, manifest checksums, SQLite integrity, known migrations, an enabled administrator), the service
restarts, and the server applies the restore before the database opens. The current data is first saved as an encrypted recovery backup (a fresh
installation has nothing to save). Any failure is rolled back by the server and reported with exit code 1; the previous data is unchanged.
A passphrase-protected backup takes `AUTHLENS_BACKUP_PASSPHRASE` instead of `-KeyFile`.

## Migrating from SAP Lens

The supported path is a **fresh AuthLens installation plus a restore** of a SAP Lens backup. The SAP Lens service (`SapLens2`, `sap-lens` or
`SapLens`), its data, keys, TLS files and releases are not changed and stay available for rollback until AuthLens is accepted.

1. **On the SAP Lens installation:** Settings > Backup & Restore, create a backup, verify it and download it (`SAP-Lens-manual-<id>.slbak`).
   Export the host recovery key (`Service-Manager.ps1 -Action ExportKey -Path <new file>` with the SAP Lens data directory, then `-Action VerifyKey`).
   Transfer both to the AuthLens host over a private channel; the key decrypts every backup it sealed.
2. **On the AuthLens host:** install AuthLens ([Install](#install)) with a TLS certificate under `tls\`. If AuthLens must use the same port as the
   running SAP Lens service, install it on another port first, or stop SAP Lens yourself in the maintenance window (AuthLens never stops it).
3. **Restore:** `--mode restore --backup <file> --key-file <key> --yes`. The archive's `sap-lens-v2.sqlite3` becomes `authlens.sqlite3`; migration
   history, tables, accounts, review history, SoD decisions and branding are restored unchanged. Nothing depends on the original paths, service name or
   machine.
4. **Verify:** `--mode status` and `--mode health` (version `2.0.0-alpha.1`, expected commit); sign in and compare Dashboard, User Access, Account
   Review and SoD with the SAP Lens installation; create and verify a new AuthLens backup.
5. **Activate:** point the reverse proxy (or DNS) at AuthLens. Keep the SAP Lens installation stopped but intact until AuthLens is accepted.
6. **If anything fails:** the restore rolls back by itself; remove the AuthLens service and root if wanted, and keep using SAP Lens. Nothing of
   SAP Lens was changed.

A single SAP Lens data directory (for example a Desktop folder) can instead be converted in place with `AuthLens.Api --adopt-legacy-database
--data-dir <dir>` while SAP Lens is stopped: the SAP Lens file is kept, and the copy is verified (integrity, migration history, row counts) before
it becomes `authlens.sqlite3`. AuthLens refuses to start on a directory that holds only `sap-lens-v2.sqlite3`.

## NTFS permissions

Implemented and tested on Linux with synthetic ACLs (Pester `AuthLens.Acl.Tests.ps1`, including ProtectAcl/RestoreAcl with Windows-only
descriptor types replaced, and `AuthLens.Deploy.Tests.ps1`); **awaiting Windows acceptance** (no real ACL was read or changed from this
environment; `AuthLens.Acl.Native.Tests.ps1` and `AuthLens.Junction.Tests.ps1` run only on Windows).

**Broad principals** (matched by well-known SID, so localized account names do not matter): Everyone `S-1-1-0`, Authenticated Users
`S-1-5-11`, Users `S-1-5-32-545`, Interactive `S-1-5-4`, Network `S-1-5-2`, Anonymous Logon `S-1-5-7`, Guests `S-1-5-32-546`, Domain Users and
Domain Guests (`S-1-5-21-…-513`/`-514`). An allow rule counts when it applies to the object itself or, on a folder, to new children
(container/object inherit, also inherit-only): that is what a folder created later inherits. Deny rules and individual accounts are not findings.
*Read* is ReadData/ListDirectory, GENERIC_READ or GENERIC_ALL; *write* is any of WriteData/CreateFiles, AppendData/CreateDirectories, WriteEA,
WriteAttributes, DeleteSubdirectoriesAndFiles, Delete, ChangePermissions, TakeOwnership, GENERIC_WRITE or GENERIC_ALL.

| Class | Paths of the installation (role) | Broad read | Broad write | Required identities |
| --- | --- | --- | --- | --- |
| Private | `data` and every descendant (database, logs, application backups, accounts); `backups\predeploy`; `tls` (certificate, password file); the folder of the host backup key (`keys`); `deployment` | refused | refused | SYSTEM and Administrators full control; the service's virtual account modify on `data`, read on `tls` and `keys`, nothing on the others (an `NT SERVICE\…` account only: `LocalSystem` is SYSTEM) |
| Binaries | `releases`; the configuration file and its folder (`config`) | allowed on `releases` (read and execute), refused on configuration | refused | SYSTEM and Administrators full control; service read and execute on `releases` |

`C:\ProgramData` normally grants Users read and inherited create rights. It is **never changed**; `Initialize-ALInstallation` creates
`C:\ProgramData\AuthLens` with a protected DACL instead. A path that does not exist yet is reported (`exists: false`) without findings.
Secure provisioning refuses a parent with broad delete/replacement or DACL/owner rights. `AuditAcl` reports every finding with path, role,
principal, access, rights mask, inherited or explicit, and what it applies to.

This is a conservative allow-rule policy audit, not a Windows Authz effective-access calculation for every possible token. A broad allow remains
a finding even when a deny might cancel it for a particular user; individual account membership is not expanded. Native fixtures verify the SID
and inheritance representation Windows returns. Do not weaken these findings because an interactive administrator happens to have access.

### Audit and remediation

```powershell
$entry = '.\backend\scripts\deploy\Deploy-AuthLens.ps1'
$config = 'C:\ProgramData\AuthLens\config\deploy.json'
# Read-only: every finding for the installation (exit 0 safe, 2 unsafe). Changes nothing.
& $entry -Action AuditAcl -ConfigFile $config
# Only after approval and verified application/recovery backups. Review all roots first.
$approvedRoots = @('C:\ProgramData\AuthLens', 'C:\ProgramData\AuthLens-acl-recovery')
$aclBackupRoot = 'C:\ProgramData\AuthLens-acl-recovery'   # dedicated, outside affected trees; never ProgramData itself
# Explicit, approved remediation in an elevated session (does not stop or reconfigure the service):
& $entry -Action ProtectAcl -ConfigFile $config -ApprovedAclRoot $approvedRoots -AclBackupRoot $aclBackupRoot -Yes
# Undo exactly what ProtectAcl changed:
& $entry -Action RestoreAcl -ConfigFile $config -AclBackup <printed-backup-folder> -ApprovedAclRoot $approvedRoots -Yes
```

`ProtectAcl` changes only existing paths with broad grants or missing required access:

1. Requires explicit `-ApprovedAclRoot` application-owned roots and a disjoint `-AclBackupRoot` outside every affected tree. It rejects system
   roots, unapproved paths and reparse points before any change. Creates the backup storage with a protected DACL (SYSTEM, Administrators) and saves every affected ACL with its
   descendants into verified, icacls-compatible UTF-16 path/DACL inventories using in-process ACL reads, without recursive native traversal or per-object backup processes. Schema-2 `acl-backup.json` retains file checksums and original DACL inventories. All inventories and the manifest are flushed before application ACL changes.
2. For each path: `icacls /inheritance:r` with SYSTEM and Administrators full control (and the service's virtual account where the table says
   so), removes explicit grants to the broad SIDs (including the actual Domain Users/Guests SIDs found by the audit), grants authenticated users read and execute again on release folders only, and resets the
   inventoried physical descendants of private folders individually to inherit (their earlier explicit entries are in the backup). Ordinary files use a file-handle native reset; directories retain individual `icacls /reset /L /C /Q` calls. The native reset opens the final object with `OPEN_REPARSE_POINT`, rejects directory/reparse handles and supplies a real empty DACL with inheritance enabled, never a null DACL. Owner, group and SACL are outside this DACL-only operation.
3. New protected folders (the ACL backup storage, and the installation root through `Initialize-ALInstallation`) receive their DACL in the
   native exclusive [CreateDirectoryW operation](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createdirectoryw); ACE
   bytes/protection and required SYSTEM/Administrators access are verified before any file is written. Creation failure, a raced existing path,
   unsupported storage or verification failure refuses further writes.
4. Verifies required SYSTEM/Administrators full control and audits again; an unsafe result fails closed and retains the ACL backup.

It refuses drive roots, `%ProgramData%`, `%ProgramFiles%`, the Windows folder, `%SystemDrive%\Users` and user profiles. The running service
keeps its access (SYSTEM for `LocalSystem`, its own grant otherwise), so it is not stopped. Before running it on the production host: take a
verified application backup, run `AuditAcl` and review each listed path, run in a quiet window, and keep the printed backup folder.
`RestoreAcl` requires the independently approved roots again. Before its first restore command it validates all checksums and every UTF-16
path/DACL record against the saved inventory, rejecting path escapes. It replays saved ACLs newest first and verifies every original DACL afterward;
exit 4 indicates an unverified restore requiring manual recovery. Backup storage is retained; target-parent records of older backups are kept, never deleted. Schema-1 backups remain
untouched and require reviewed manual restoration; they lack the inventories required for an automated verified restore.
An elevated Windows token is required for native remediation/restore acceptance. An unprivileged `icacls /restore` can fail with exit 1300
(missing privilege); that is an infrastructure limitation, not evidence that restoration passed. Keep the original ACL backup and investigate.

### Release junction boundary

The source service may run through `<Source.ReleasesRoot>\current`. The former ACL backup path was
`Invoke-ALProtectAcl` -> `Get-ALAclSnapshot` -> `Get-ALTreeFiles`; the last helper intentionally rejects all reparse points, so snapshotting the
releases or installation folder rejected its legitimate release junction. Every other installation-tree traversal keeps that strict behavior.

ACL inventory alone accepts the exact `current` **directory junction** directly below the explicitly configured source releases root. Its target
must be an existing direct physical child of that root, contain a release manifest and Server directory, and have no linked ancestors or linked
descendants. Symbolic links, ordinary directories at `current`, missing/external/looping targets, additional aliases and nested reparse points
are refused. Approved roots must themselves remain physical; the exception never grants access through `current` or expands an approved root.
The exception compares configured paths and approved-root spelling exactly, including case, rather than accepting case-folded aliases. Use the
same physical path spelling in the source configuration, junction target and approved roots; a mismatch is refused without changing the junction.

The junction is validated and omitted from ACL inventory. Physical release files are inventoried through their real directory; overlapping plan roots can save the same physical object in separate inventories. ACL backup reads physical DACLs directly and writes UTF-16 restore records; it never invokes recursive native save or follows `current`.
Reset operations name individual physical descendants without wildcards or `/T`. Restore validates every recorded destination, rejects any path
through a link and uses `/restore /L`. See the [icacls command contract](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/icacls).
Neither ACL remediation nor restoration deletes, recreates or redirects `current`. The physical target remains subject to its approved ACL policy.

New schema-2 backup entries for source release/installation roots record `releases_root` and the observed `junction` path/target. Binding and tree
checks run before commands and again before success. A changed binding, new unexpected link or unsafe target blocks further operations; a failed
post-operation check requires manual review (exit 4), retaining the backup. Do not run concurrent release switching during ACL operations. These
checks are fail-closed observations, not an atomic lock against a privileged administrator changing the filesystem concurrently.
Older backups receive no inferred junction exemption: link-free inventories remain supported, while an unrecorded junction requires manual review.
The release's historical build manifest is never regenerated for this procedure.

Read-only inspection from the updated checkout on the actual Windows host:

```powershell
Import-Module .\backend\scripts\deploy\AuthLens.Deploy.psm1 -Force
$source = Read-AuthLensSettings 'C:\ProgramData\AuthLens\config\deploy.json'
Get-ALReleaseJunction $source.ReleasesRoot | ConvertTo-Json
# ACL metadata only: validates the whole installation tree and omits the validated current junction.
@(Get-ALAclSnapshot (Split-Path $source.ConfigFile) $source.ReleasesRoot).Count
```

Run `AuthLens.Junction.Tests.ps1` on isolated Windows fixtures. It covers allowed and rejected junctions, nonrecursive native ACL save, restore
binding/path boundaries and strict tree traversal. The native junction restore round trip additionally requires elevation; a skipped check is
pending acceptance, not a production-ready result. See the measured implementation and interruption procedure below; performance measurements do not establish production acceptance.

Windows junction checkpoint (2026-11-19, Windows PowerShell 5.1 / Pester 5.9.1): complete suite **208 passed, 0 failed, 11 skipped**,
0 failed containers (219 discovered). Nine skips are Linux-only fixtures and two require elevated native ACL restore. The final focused junction
spec passed 15 tests with its elevated restore case explicitly skipped. The 5.1 parser accepted all 24 active scripts; documentation links passed.
No production service, ACL, release pointer or private state was modified, and no full .NET/browser run was required for this PowerShell change.


### ACL performance and interrupted operations

The `8ee1cc6` backup invoked one `icacls /save` process **per snapshot object**, including duplicates in overlapping source roots. Private-state remediation then invoked another process per descendant, plus two or three commands per changed root. Restore already used one process per saved inventory, but validation searched the whole snapshot for each record (quadratic work). Repeated PowerShell ancestor/provider checks and tree/audit walks added time before the backup directory appeared. A changing `04.acl.part` in that implementation contained only the most recently saved object, not a cumulative or complete fourth backup. The startup-only deployment log contained no phase/count progress. An unsafe audit does not prove that no partial change occurred.

Backup now uses zero native processes per object, rechecks every ancestor through filesystem attribute APIs and compares the current DACL against the snapshot. It streams UTF-16 records to an exclusive `.part`, flushes to disk and renames without replacement. A failed write retains its partial output; it cannot be retried into the same filename. Completed records are validated with an indexed path lookup before the manifest is published. Root approval checks remain mandatory; descendant checks require containment within that approved root and physical, link-free ancestors. There is no cross-phase cache that would hide newly introduced links.

Recovery-path validation also covers a drive-root parent: the earlier `Parent.Length + 1` offset dropped the first character when the parent already ended in a separator (for example a source installation immediately under the drive). The writer now normalizes that offset, and validates the published inventory before permitting any ACL change. UTF-8 manifests are read explicitly as UTF-8 on Windows PowerShell 5.1 so Unicode filenames retain their exact paths. Old recovery artifacts are never rewritten to apply either correction; malformed historical inventories require reviewed manual recovery.

Ordinary file resets use a handle-based [SetSecurityInfo](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-setsecurityinfo) operation, validated against `icacls /reset` with protected parents, inherited ACEs and repeated resets. Directory resets remain individual `/L` commands: directory `SetSecurityInfo` can propagate inheritable permissions to children, so it is not a safe replacement without further traversal analysis. For a changed private tree containing F files and D descendant directories, reset process launches drop from F+D to D. Root commands and one restore process per inventory remain. No wildcards or recursive native ACL switches were introduced.

Progress is printed to the terminal and the deployment log at stage boundaries and approximately every five seconds between objects: phase, stage, processed/total, elapsed seconds and ETA. Enumeration totals and ETA are `unknown` until measurable; ETA is a stage-local linear estimate only after 100 objects and five seconds. An individual native call or filesystem call can block longer than the reporting interval; no synthetic ETA or timeout hides that condition.

Each new operation writes a flushed append-only `acl-operation.jsonl` in its unique timestamp/GUID backup directory. The `backups_complete` checkpoint follows all inventories and the manifest; `mutation_started=true` is flushed **before** the first application ACL change. Normal failures append `failed`; abrupt termination leaves the last checkpoint, possibly an incomplete trailing JSON line. `Get-ALAclOperationStatus` reads this evidence without modifying it and treats truncated/absent journals conservatively. No automatic resume or rollback is implemented. Restore validates every inventory before changing any ACL, writes a separate new `acl-restore-<GUID>.jsonl`, and verifies original DACLs afterward. Recovery artifacts, created parents and prior journals are retained. The journal is a diagnostic checkpoint, not a replacement for inventory checksums, a verified application backup or explicit recovery approval.

Measured on the isolated Windows workstation checkout (Windows PowerShell 5.1, NTFS; **not the production VM**), using `Measure-AclPerformance.ps1`:

| Fixture/stage | Original | Optimized | icacls processes, original to optimized |
| --- | --- | --- | --- |
| 100 files + 11 directories, backup | 10.715 s | 0.961 s | 111 to 0 |
| 100 file resets | 9.097 s | 0.895 s | 100 to 0 |
| 2,000 files + 11 directories, inventory | not repeated | 13.850 s | 0 |
| Same large fixture, backup / indexed validation | not repeated | 14.804 s / 2.477 s | 0 |
| Same large fixture, file resets | not repeated | 8.048 s | 0 |

Small-fixture backup output was byte-identical to the original native-save output. Process counts cover deployment `icacls` calls; first-use `Add-Type` may invoke the framework compiler once on Windows PowerShell 5.1, independently of the object count. File reset timing includes first-use native helper compilation. Large-fixture native baselines were deliberately not repeated. At the small measured rate, 82,422 backup records alone would need roughly 2.2 hours with the original algorithm; an earlier 101-object measurement projected 2.6 hours. Duplicated inventories, disk/antivirus load and prevalidation increase the total. Large optimized measurements suggest minutes per pass at that scale, **not a promised VM completion time**. Overlapping snapshots, repeated physical/junction validation, in-memory snapshots/JSON manifests and directory process launches remain costs; an 82,422-object production-shaped elevated acceptance run remains pending.

Repeat only on fresh synthetic fixtures (the script accepts no installation path and retains its measurements under `build/test-artifacts/acl-benchmark-<GUID>`):

```powershell
& .\backend\scripts\tests\Measure-AclPerformance.ps1 -Objects 100
& .\backend\scripts\tests\Measure-AclPerformance.ps1 -Objects 2000 -SkipBaseline
```

Windows performance checkpoint (2026-11-19, Windows PowerShell 5.1 / Pester 5.9.1): **219 passed, 0 failed, 11 skipped**, 0 failed containers, 230 discovered, 452.42 seconds. The ten new performance/recovery tests cover a 1,000-file tree, zero backup process launches, partial read failures and non-overwrite, changed DACLs, drive-root/Unicode recovery paths, reset equivalence/idempotency, junction substitution and interrupted/corrupt journal status. A separate remediation fault-injection test retains all completed inventories and verifies the restoration control flow. The final direct performance/junction run passed **25**, failed **0**, skipped **1**; the broader focused deployment/migration regression passed **139**, failed **0**, skipped **2** before the final recovery-path additions. Nine complete-suite skips are Linux-only fixtures; two are elevated native restore acceptance. The 5.1 parser accepted all 26 active scripts; documentation links and main-only workflow contracts passed. An earlier checkpoint attempt was cancelled to add the drive-root regression; the figures above are from the one completed final checkpoint. PowerShell 7 and elevated production-shaped restore were unavailable. No full .NET/browser suite or production operation ran.

#### An interrupted ACL operation on the SAP Lens VM

An earlier `ProtectAcl` run against the SAP Lens installation on the VM was interrupted. With the AuthLens migration path (fresh installation plus
restore) the SAP Lens installation needs **no** ACL change. Leave that operation's recovery directory, `.part` files, service and junction
exactly as they are; do not restart, resume, delete or reuse them. Inspect it read-only only if needed:

```powershell
Import-Module .\backend\scripts\deploy\AuthLens.Deploy.psm1 -Force
Get-ALAclOperationStatus (Read-Host 'Exact existing ACL recovery directory (read only)') | ConvertTo-Json -Depth 5
```

These commands do not remediate findings or verify a complete restore. Do not weaken the junction boundary or global Windows ACLs to improve throughput. Active-service permissions, databases/WAL, TLS, encryption keys and historical migration evidence remain outside this development task.

### Windows script validation

Use Pester 5 in a fresh PowerShell process. Windows PowerShell 5.1 is supported for these deployment tests; PowerShell 7 is not required merely
to launch child scripts. `scripts/tests/TestHelpers.ps1` resolves the current edition's executable under `$PSHOME` by absolute path. To explicitly
test another installed edition, set `AUTHLENS_TEST_POWERSHELL` to its absolute executable path. An invalid override fails instead of falling back
or skipping. Run the suite from each installed edition to exercise that edition's parser and module behavior too.

```powershell
powershell.exe -NoProfile -File .\backend\scripts\check-powershell.ps1
# In a fresh Windows PowerShell 5.1 session with Pester 5 installed/importable:
Import-Module Pester -MinimumVersion 5.0
Invoke-Pester -Path .\backend\scripts\tests\TestHelpers.Tests.ps1 -Output Detailed
Invoke-Pester -Path .\backend\scripts\tests\AuthLens.Acl.Tests.ps1,.\backend\scripts\tests\AuthLens.Acl.Native.Tests.ps1 -Output Detailed
# Phase checkpoint, after affected groups pass (not after every edit):
Invoke-Pester -Path .\backend\scripts\tests -Output Detailed
```

`Import-Module -Force` reloads one path but leaves same-name copies from other checkouts loaded. Pester's name-based mocks then fail with
"Multiple script or manifest modules named 'AuthLens.Deploy' are currently loaded." Repeated canonical imports alone do not imply that defect.
The shared test helper removes loaded copies and imports the resolved canonical module globally at each container's setup. Tests run serially;
do not share that process with operator actions. The regression creates a synthetic second module and proves the mock becomes unambiguous.
The test launcher protects `ProgramData\AuthLens` and every earlier product's production and Desktop data roots. The real NTFS fixtures touch only TestDrive. Their restore test explicitly reports a skip without elevation; mocked remediation is reported
separately. Linux shell-server fixtures remain Windows skips. Missing `pwsh` never skips deployment or release-contract tests.

Windows script checkpoint, 2026-11-19: Windows PowerShell 5.1 with Pester 5.9.1 discovered 203 tests: **193 passed, 0 failed, 10 skipped,
0 failed containers**. Nine skips were Linux shell-server fixtures; one was native ACL restoration without an elevated token. The 5.1 parser
accepted all 23 active scripts. Focused .NET StartupTests (5) and installer contracts (6) also passed. PowerShell 7 was unavailable. Real NTFS secure-at-creation, SID/inheritance and ACL-save tests passed; full native remediation/restore,
SCM, service continuity and production preflight remain unverified. The test workstation did not contain the active VM installation, so this run
did not prepare its target directories, verify its installed release, build a new production package or establish `safe: true`. Keep the existing
release manifest unchanged and obtain the actual VM connection before continuing the preparation checklist.

## Service model and permissions

- **Managed or not:** a service counts as managed (`binary_path_matches` in status) when its executable is the release link's
  `current\server\AuthLens.Api.exe` and its arguments are equivalent to the configuration. Both are compared normalized (quotes, separators and
  case of the path; option and list order of the arguments, as in [adoption](#install)), never as raw strings: Windows can store an
  equivalent command line differently (for example without the quotes around the executable when Windows PowerShell 5.1 passes `binPath=` to
  `sc.exe`). A real difference in any argument still reads as not managed.

- One service: `AuthLens`. Services of earlier products (`SapLens2`, `sap-lens`, `SapLens`) are never looked at, adopted, stopped or changed; AuthLens runs beside them.
- Account: the service's own virtual account (`NT SERVICE\<name>`), no password. Grants are added, never removed: modify on the data directory
  (inherited), read and execute on `ReleasesRoot`, read on the certificate, its password file and the backup key file.
- Command line (no secret): `AuthLens.Api.exe --data-dir … --network --listen … --port … --allowed-hosts … --cert … --cert-password-file … [--trusted-proxies …]`.
  TLS, the Host allow-list, Origin/CSRF checks and the trusted-proxy restriction are the server's own and unchanged by the deployment.
- Processes: only the service is stopped, through the SCM. A port held by another process (for example `start-server-test.ps1`) is reported and left alone.

## Logs and artifacts

| Where | What |
| --- | --- |
| `${XDG_STATE_HOME:-~/.local/state}/authlens-deploy/<UTC>-<mode>-<host>.log` (Linux) | Complete remote output of each run |
| `WorkRoot\runs\<run id>\` | `deploy.log`, `build.log`, `RECOVERY-REQUIRED.txt` when needed |
| `WorkRoot\deployment-journal.json`, `WorkRoot\deployment.lock` | Phase history of the last run; one operation at a time |
| `WorkRoot\worktrees\<sha12>`, `WorkRoot\builds\<sha12>` | Isolated build checkouts and builder output |
| `ReleasesRoot\AuthLens-<version>-<UTC>-<sha7>-win-x64`, `ReleasesRoot\current` | Verified server deployment packages ([release packages](#release-packages-and-integrity)) and the junction the service runs |
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
powershell -NoProfile -File .\scripts\build-release.ps1 -Output C:\AuthLens-Build\builds
$release = Get-ChildItem C:\AuthLens-Build\builds -Directory -Filter 'AuthLens-*-win-x64' | Sort-Object Name | Select-Object -Last 1
powershell -NoProfile -File .\scripts\build-installers.ps1 -ReleasePath $release.FullName -Output C:\AuthLens-Build\installers
```

| Installer | Scope and folder | Behavior |
| --- | --- | --- |
| `AuthLens-<version>-Setup.exe` (Desktop) | Per user, `%LOCALAPPDATA%\Programs\AuthLens Desktop`; data `%LOCALAPPDATA%\AuthLens` | New AppId; SAP Lens 1 and the SAP Lens Desktop are detected and left untouched (their data comes over by restoring a backup) |
| `AuthLens-Server-<version>-Setup.exe` | Machine, `C:\ProgramData\AuthLens\app\server` | New AppId; installs beside SAP Lens. Stops and restarts only the `AuthLens` service when it runs from `{app}`; never creates or deletes a service |

Silent: `AuthLens-<version>-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=C:\ProgramData\AuthLens\install.log`. Installers are unsigned; signing,
publishing and tagging are separate, authorized release steps. Upgrades replace executables only: the server and Desktop back the database up
themselves before any schema migration.

## Local Service Manager

The release includes `Service-Manager.ps1` beside `server/`; the Server installer adds a local administration shortcut. It invokes the packaged
server binary directly, needs no SDK, opens no listener and never controls the service. Select the exact data directory and executable explicitly
when operating an older installation. Key export/provisioning stays local-only; no browser export endpoint exists.

```powershell
$manager='C:\ProgramData\AuthLens\releases\current\Service-Manager.ps1'
$exe='C:\ProgramData\AuthLens\releases\current\server\AuthLens.Api.exe'
$data='C:\ProgramData\AuthLens\data'
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

**Status: not executed.** Nothing below has run on Windows yet; record each result before calling a step passed. Linux results (unit, Pester,
browser, release build) are reported separately in [release status](../migration/RELEASE_STATUS.md) and are not Windows evidence.

Ground rules: an elevated **Windows PowerShell 5.1** prompt in a clean checkout of `experiment/dotnet-backend`; synthetic data first, a real backup
only as a **copy** in an isolated root; the existing SAP Lens services (`SapLens2`, `sap-lens`, `SapLens`), their folders, ports, certificates and
firewall rules are never stopped, changed or reused. Keep the evidence files of each step under `C:\AuthLens-Acceptance\evidence` (no secrets,
codes, passwords or keys in them).

### 0. Baseline of the existing installations (read only)

```powershell
New-Item -ItemType Directory -Force C:\AuthLens-Acceptance\evidence | Out-Null
$ev = 'C:\AuthLens-Acceptance\evidence'
Get-CimInstance Win32_Service | Where-Object Name -in 'SapLens2','sap-lens','SapLens','AuthLens' |
  Select-Object Name, DisplayName, State, StartMode, StartName, PathName | ConvertTo-Json | Set-Content "$ev\00-services-before.json"
Get-NetTCPConnection -State Listen | Select-Object LocalAddress, LocalPort, OwningProcess | Sort-Object LocalPort | Out-File "$ev\00-ports-before.txt"
```

Pass: the file lists the SAP Lens services as they are; **no** `AuthLens` service yet. Choose a free port for AuthLens (for example `18796`).

### 1. Release build, verification and installers

```powershell
git status --short; git rev-parse HEAD                                      # clean, expected commit
Import-Module .\backend\scripts\deploy\AuthLens.Deploy.psm1 -Force; $filter = Get-ALTestFilter focused
& .\backend\scripts\build-release.ps1 -Output C:\AuthLens-Acceptance\builds -TestFilter $filter
$release = Get-ChildItem C:\AuthLens-Acceptance\builds -Directory -Filter 'AuthLens-*-win-x64' | Sort-Object Name | Select-Object -Last 1
& .\backend\scripts\verify-release.ps1 -ReleasePath $release.FullName *>&1 | Tee-Object "$ev\01-verify.txt"
& .\backend\scripts\build-installers.ps1 -ReleasePath $release.FullName -Output C:\AuthLens-Acceptance\installers
Get-ChildItem $release.FullName\server, $release.FullName\desktop | Select-Object Name, Length | Out-File "$ev\01-files.txt"
```

Pass: `Release verified` for win-x64; `server\AuthLens.Api.exe` and `desktop\AuthLens.exe` exist; manifest product `AuthLens`, version
`2.0.0-alpha.1`; `AuthLens-2.0.0-alpha.1-Setup.exe` and `AuthLens-Server-2.0.0-alpha.1-Setup.exe` are produced.

### 2. Native test suites

```powershell
Invoke-Pester .\backend\scripts\tests -Output Detailed *>&1 | Tee-Object "$ev\02-pester.txt"   # includes the Windows-only ACL, junction and native tests
dotnet test .\backend\tests\AuthLens.Tests -c Release *>&1 | Tee-Object "$ev\02-dotnet.txt"
```

Pass: no failures. The native ACL restore round trip needs elevation; record any skip with its reason.

### 3. Fresh installation (canonical service and root)

Create `C:\ProgramData\AuthLens\config\deploy.json` from `deploy.example.json` with `Root` `C:\ProgramData\AuthLens`, this checkout as
`RepositoryPath`, the VM's own address as `ListenAddress`, the free port, `AllowedHosts` with that address (and a test host name). Put a TLS
certificate for that name in `C:\ProgramData\AuthLens\tls` (`server.pfx`, `cert-password`; see
[certificates](SERVER_NETWORK_ACCESS.md#4-tls-certificates)).

```powershell
$entry = '.\backend\scripts\deploy\Deploy-AuthLens.ps1'; $config = 'C:\ProgramData\AuthLens\config\deploy.json'
& $entry -Action Deploy -FirstInstall -ConfigFile $config -DryRun                      # plan only
& $entry -Action Deploy -FirstInstall -ConfigFile $config -Tests focused -Yes *>&1 | Tee-Object "$ev\03-install.txt"
& $entry -Action Status -ConfigFile $config | Tee-Object "$ev\03-status.txt"
& $entry -Action AuditAcl -ConfigFile $config | Tee-Object "$ev\03-acl.txt"; "exit $LASTEXITCODE"
Get-CimInstance Win32_Service -Filter "Name='AuthLens'" | Select-Object Name, DisplayName, State, StartMode, StartName, PathName | Format-List
Get-ChildItem C:\ProgramData\AuthLens, C:\ProgramData\AuthLens\data | Select-Object FullName
foreach ($d in 'data','tls','keys','backups\predeploy','deployment','releases','config') { icacls "C:\ProgramData\AuthLens\$d" } | Out-File "$ev\03-icacls.txt"
Invoke-WebRequest -UseBasicParsing "https://<host>:<port>/health/ready" | Select-Object StatusCode, Content
```

Pass:

| Check | Expected |
| --- | --- |
| Service | Name `AuthLens`, DisplayName `AuthLens`, `Auto` start, `NT SERVICE\AuthLens`, running `C:\ProgramData\AuthLens\releases\current\server\AuthLens.Api.exe` |
| Layout | `releases`, `data`, `config`, `tls`, `keys`, `backups\predeploy`, `deployment` under `C:\ProgramData\AuthLens` |
| Database | `data\authlens.sqlite3` (plus `-wal`/`-shm`), no `sap-lens-v2.sqlite3`; `/health/ready` 200 |
| ACLs | `AuditAcl` exit 0; root protected (SYSTEM, Administrators); service modify on `data`, read on `tls` and `keys`, read/execute on `releases`; no Users/Authenticated Users write anywhere and no read on private folders or `config` |
| TLS and network | HTTPS on the configured address and port only; an unlisted host name is refused; the SAP Lens ports are unchanged |

### 4. Service lifecycle

```powershell
Restart-Service AuthLens; (Get-Service AuthLens).Status
Get-Content C:\ProgramData\AuthLens\data\logs\server-*.log -Tail 20     # graceful stop, then start and ready
Restart-Computer                                                       # then, after sign-in:
(Get-Service AuthLens).Status; Invoke-WebRequest -UseBasicParsing "https://<host>:<port>/health/ready"
```

Pass: stop is graceful (log shows shutdown, no integrity warning), the service starts automatically after a reboot and is ready.

### 5. Backup and restore (synthetic first)

On the fresh installation: activate the first administrator, import the synthetic CSVs from `examples\`, create a manual backup in
Settings > Backup & Restore, download it and export the recovery key (Service Manager). Then:

```powershell
& $entry -Action Restore -ConfigFile $config -Backup <synthetic AuthLens.slbak> -KeyFile <exported.key> -Yes; "exit $LASTEXITCODE"
& $entry -Action Restore -ConfigFile $config -Backup <SAP Lens .slbak copy> -KeyFile <SAP Lens recovery key copy> -Yes; "exit $LASTEXITCODE"
Get-ChildItem C:\ProgramData\AuthLens\data -Filter *.sqlite3; Get-ChildItem C:\ProgramData\AuthLens\data\backups\archives -Filter 'destination-*'
```

Pass: exit 0; `authlens.sqlite3` only; a `destination-*` recovery backup of the replaced data; users, roles, account reviews, SoD decisions,
saved filters and settings match the source; Data Health shows no integrity finding; `/health/ready` 200. Source paths of the SAP Lens host may
not exist here: the imported records are still present, and a refresh reports such a source as failed without replacing its data.

Failure cases (each must leave the current data unchanged and no `data\restore\pending.json`):

| Case | How | Expected |
| --- | --- | --- |
| Wrong key | `-KeyFile` of another installation | Refused, exit 1 or 2 |
| Missing key | No `-KeyFile`, key not configured | Refused |
| Corrupted backup | A copy with one changed byte | Refused before staging |
| Newer schema | Covered by `LegacyRestoreTests` on Linux; not reproducible with a real archive | — |
| Interrupted restore | `Stop-Service AuthLens` right after the restore stage, then `Start-Service` | Applied or rolled back as a whole |
| Existing data | Restore over the installation that already has data | Recovery backup first, then replaced |

### 6. Updates, rollback and earlier products

```powershell
& $entry -Action Deploy -ConfigFile $config -Tests focused -Yes          # a newer commit
& $entry -Action Rollback -ConfigFile $config -Yes
Get-CimInstance Win32_Service | Where-Object Name -in 'SapLens2','sap-lens','SapLens' |
  Select-Object Name, DisplayName, State, StartMode, StartName, PathName | ConvertTo-Json | Set-Content "$ev\06-services-after.json"
Compare-Object (Get-Content "$ev\00-services-before.json") (Get-Content "$ev\06-services-after.json")    # no output
```

Pass: data kept across update and rollback; the SAP Lens services are identical to step 0.

### 7. Installers and Desktop

Run `AuthLens-Server-2.0.0-alpha.1-Setup.exe` only on a VM without the canonical installation from step 3 (it installs to
`C:\ProgramData\AuthLens\app`), and `AuthLens-2.0.0-alpha.1-Setup.exe` for the current user.

```powershell
& "$env:LOCALAPPDATA\Programs\AuthLens Desktop\AuthLens.exe" --self-check; "exit $LASTEXITCODE"
Get-ChildItem "$env:LOCALAPPDATA\AuthLens" -Recurse -Depth 1 | Select-Object FullName
```

Pass: both setups install beside SAP Lens (own AppIds, SAP Lens entries unchanged in Apps & features); self-check exit 0 and a log under
`%LOCALAPPDATA%\AuthLens\logs`; the Desktop window opens, imports a synthetic CSV, and exports (CSV, PDF, DOCX, backup) arrive as normal downloads.
Uninstall removes the programs and keeps data.

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
dotnet build backend/AuthLens.slnx -c Release
dotnet test backend/tests/AuthLens.Tests -c Release --no-build --filter "FullyQualifiedName~StartupTests|FullyQualifiedName~NetworkTests|FullyQualifiedName~ReverseProxyTests|FullyQualifiedName~DesktopLocationTests|FullyQualifiedName~InstallerTests|FullyQualifiedName~VersioningTests"
```

Pester requires version 5.7.1 (`Install-Module Pester -RequiredVersion 5.7.1 -Scope
CurrentUser` through the approved repository, if not already available). Respect
corporate signing/execution policy; do not disable WDAC or bypass script policy.
These checks do not certify native service restart, Desktop/WebView2, installer,
ACL/firewall, backup recovery or real-data migration acceptance. Those remain the
separate existing checklist above, and must use disposable installations/data.
The running service and all existing release/backup directories must stay untouched.
