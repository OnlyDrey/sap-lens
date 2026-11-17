# Windows deployment: SSH-driven test server and installers

How the SAP Lens .NET server is built, validated and deployed on a Windows test host from Linux over SSH, how an earlier `SapLens2` service is
migrated to `SapLens`, and how the Desktop and Server installers are built. Every value below is an example (`192.0.2.0/24`, `lens.example.com`,
`deployer`, `C:\Users\example`); real host names, addresses, paths and credentials stay in the host's own configuration file and are never committed.

Status: the scripts are tested on Linux with mocks (Pester) and a fake SSH (Bash). **Native Windows acceptance is pending**; see
[Acceptance checklist](#acceptance-checklist-windows-pending). Nothing here claims that a Windows run passed.

## Components

| Path (under `experiments/dotnet-backend`) | Role |
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

Copy `scripts\deploy\deploy.example.json` to a folder outside the repository and edit it. Lookup when `-ConfigFile`/`--config` is not given, first
match wins: `$env:SAPLENS_DEPLOY_CONFIG`, `$env:SAPLENS2_DEPLOY_CONFIG`, `C:\saplens\deploy.local.json`, `C:\saplens2\deploy.local.json`.

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
D=experiments/dotnet-backend/scripts/deploy/deploy-windows.sh
H=(--host 192.0.2.10 --user deployer --repo 'C:\Users\example\Git\sap-lens')
$D "${H[@]}" --mode status                       # service model, name, state, linked release, readiness, journal
$D "${H[@]}" --mode health                       # /health/ready and /product-version.json of the running server
$D "${H[@]}" --mode build --tests focused        # lock, build in a worktree, test, verify, publish to ReleasesRoot; no service change
$D "${H[@]}" --mode dry-run                      # lock the commit and print the plan; no build, backup or service change
$D "${H[@]}" --mode deploy --tests focused --yes # build, test, verify, back up, stop, switch, start, verify; roll back when safe
$D "${H[@]}" --mode deploy --commit 1a2b3c4d --tests full --yes
$D "${H[@]}" --mode rollback --yes               # previous release, only when it can open the current data
$D "${H[@]}" --mode recover --yes                # finish an interrupted deployment (Ctrl+C, dropped SSH)
$D "${H[@]}" --mode migrate-service --yes        # SapLens2 to SapLens (below)
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

## First deployment

**Host with a hand-installed server** (for example an earlier `SapLens2` service started from a build folder):

```bash
$D "${H[@]}" --mode status                                  # service_model windows-service, binary_path_matches false
$D "${H[@]}" --mode dry-run
$D "${H[@]}" --mode deploy --tests focused --adopt-service --yes
```

Adoption requires the service's arguments to equal the configuration exactly (data directory, network, TLS, hosts, proxies); otherwise it is
refused before any change. The original command line is recorded and restored if the adopted deployment fails.

**New host:** `--mode build`, then `--mode deploy --first-install --yes` (installs the `SapLens` service with automatic start, its virtual account,
restart on failure and least-privilege grants), then `--mode status`.

## Migrating SapLens2 to SapLens

`SapLens` is the service name for new installations. An existing `SapLens2` keeps working (it is detected) until it is migrated once:

```bash
$D "${H[@]}" --mode status                       # service_name SapLens2, legacy_service_name true, binary_path_matches true
$D "${H[@]}" --mode migrate-service --yes
$D "${H[@]}" --mode status                       # service_name SapLens, other_service null
```

Preconditions: `ServiceName`/`ServiceAccount` are not in the configuration (detection handles both names), `SapLens2` runs the managed release link
(adopt first), no interrupted run, and `SapLens` does not exist yet. Sequence: create `SapLens` (manual start, same command line, account
`NT SERVICE\SapLens`, restart on failure), grant that account the same access, stop `SapLens2` and disable it, start `SapLens`, verify readiness,
version and commit, then set `SapLens` to `SapLens2`'s start mode and delete `SapLens2`. Its previous settings are kept in `legacy-service.json` in
the run folder. Any failure before the end deletes `SapLens`, restores `SapLens2`'s start mode and starts it again (exit 1); if that also fails,
`RECOVERY-REQUIRED.txt` lists the commands (exit 4). Data, TLS files, release folders and configuration are never moved or renamed.

## Service model and permissions

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
| `WorkRoot\runs\<run id>\` | `deploy.log`, `build.log`, `legacy-service.json`, `RECOVERY-REQUIRED.txt` when needed |
| `WorkRoot\deployment-journal.json`, `WorkRoot\deployment.lock` | Phase history of the last run; one operation at a time |
| `WorkRoot\worktrees\<sha12>`, `WorkRoot\builds\<sha12>` | Isolated build checkouts and builder output |
| `ReleasesRoot\SAP-Lens-<version>-<UTC>-<sha7>-win-x64`, `ReleasesRoot\current` | Verified server releases (manifest, SHA-256) and the junction the service runs |
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
cd C:\Users\example\Git\sap-lens\experiments\dotnet-backend
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-release.ps1 -Output C:\saplens\builds
$release = Get-ChildItem C:\saplens\builds -Directory -Filter 'SAP-Lens-*-win-x64' | Sort-Object Name | Select-Object -Last 1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-installers.ps1 -ReleasePath $release.FullName -Output C:\saplens\installers
```

| Installer | Scope and folder | Behavior |
| --- | --- | --- |
| `SAP-Lens-<version>-Setup.exe` (Desktop) | Per user, `%LOCALAPPDATA%\Programs\SAP Lens Desktop` | Own AppId; SAP Lens v1 (`%LOCALAPPDATA%\Programs\SAP Lens`, data `%LOCALAPPDATA%\SAP Lens`) is detected and left untouched. Requires WebView2. Waits for a running Desktop (it is never closed by Setup). Refuses downgrades. Data in `%LOCALAPPDATA%\SAP Lens Desktop` (or a kept `SAP Lens 2 Prototype` folder) is never deleted |
| `SAP-Lens-Server-<version>-Setup.exe` | Machine, `%ProgramFiles%\SAP Lens Server\server` | Own AppId. Never creates, reconfigures or deletes a service and never touches data. On upgrade, a `SapLens`/`SapLens2` service running from this folder is stopped with `net stop` and started again; uninstall is refused while one runs from it. Refuses downgrades |

Silent: `SAP-Lens-<version>-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=C:\saplens\install.log`. Installers are unsigned; signing,
publishing and tagging are separate, authorized release steps. Upgrades replace executables only: the server and Desktop back the database up
themselves before any schema migration.

## Privacy and secrets

- Never commit `deploy.local.json`, certificates, password files, API tokens, backup keys, `.slbak` backups, data directories or real SAP extracts;
  `.gitignore` covers `*.local.json`, `*.key`, `*.pfx`, `*.sqlite3`, `api-token` and `cert-password`.
- Real host names, addresses, user names and paths belong only in the host's configuration and in your SSH configuration (`~/.ssh/config`).
- The scripts print paths, addresses, versions and commits, never a password, token or key. Server logs record method, path and peer, never
  headers, cookies or tokens.
- Before pushing: `python scripts/check-secrets.py` (tracked files) and `git diff --check`.

## Acceptance checklist (Windows, pending)

Run in this order on the Windows test host and record the result of each step. Until then every item is **Pending**.

| # | Check | Command | Pass when |
| --- | --- | --- | --- |
| 1 | SSH and status | `$D "${H[@]}" --mode status` | Exit 0; `service_model` and `service_name` describe the host |
| 2 | Windows PowerShell 5.1 dry-run | `$D "${H[@]}" --mode dry-run` | Exit 0; `"dry_run":true`; locked commit printed; nothing changed |
| 3 | Focused build | `$D "${H[@]}" --mode build --tests focused` | Exit 0; release in `ReleasesRoot` passes `verify-release.ps1` |
| 4 | Adoption deploy | `$D "${H[@]}" --mode deploy --tests focused --adopt-service --yes` | Exit 0; `binary_path_matches` true; HTTPS through the reverse proxy works |
| 5 | Service migration | `$D "${H[@]}" --mode migrate-service --yes` | Exit 0; only `SapLens` exists (`Get-Service SapLens*`); same data; sign-in works |
| 6 | Update deploy | `$D "${H[@]}" --mode deploy --tests focused --yes` (newer commit) | Exit 0; identity is the new commit |
| 7 | Rollback | `$D "${H[@]}" --mode rollback --yes` | Exit 0; identity is the previous commit |
| 8 | Interruption | Ctrl+C during step 6's stop/start, then `--mode status` and `--mode recover --yes` | Recover ends ready on the previous release |
| 9 | Failure rollback | Deploy a release whose start fails (for example an invalid `AllowedHosts` entry in a copy of the configuration) | Exit 1; previous release ready |
| 10 | Installers | `build-installers.ps1`, then both setups interactively and with `/VERYSILENT` | Desktop starts with the icon and title "SAP Lens"; Server upgrade restarts its service; uninstall keeps data |
| 11 | Desktop self-check | `"%LOCALAPPDATA%\Programs\SAP Lens Desktop\SapLens.exe" --self-check` | Exit 0; log in `%LOCALAPPDATA%\SAP Lens Desktop\logs` (or the kept prototype folder) |
