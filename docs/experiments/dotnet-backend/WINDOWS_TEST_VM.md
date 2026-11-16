# Windows test VM: build, run and accept the Server

A runbook for one **isolated Windows 11 Pro test VM**: building a release natively, starting the Server by hand or with the test launcher,
checking HTTPS from the VM and from another machine, and recording what passed. The configuration reference (every option, environment
variable, default and refusal) is [SERVER_NETWORK_ACCESS.md, section 2](SERVER_NETWORK_ACCESS.md#2-configuration-reference); certificates
are in [section 4](SERVER_NETWORK_ACCESS.md#4-tls-certificates). The Windows service procedure is in
[section 5](SERVER_NETWORK_ACCESS.md#5-deployment); it has **not** been run natively yet.

## Example values and local configuration

The addresses and names in this runbook are **reserved examples** (`192.168.10.20`, `lens.example.com`), not product defaults and not any real
environment: the Server's own defaults are `127.0.0.1:18790` over HTTP with network access off, and `--data-dir` has no default. Nothing
environment-specific is built into the executables or the scripts; the same release runs with any address, host name and port.

Keep your environment's real values in a local file that is never committed: copy
`experiments\dotnet-backend\scripts\start-server-test.example.json` to `C:\saplens2\start-server-test.local.json` (or
`start-server-test.local.json` next to the script; `*.local.json` is git-ignored) and edit it. The launcher reads it automatically; explicit
parameters still win, and the file must not contain secrets (the certificate password stays in its own protected file). To keep your real values
out of future commits, list them one per line in `.secret-scan.local` at the repository root (git-ignored); `python scripts/check-secrets.py`
then reports any tracked file that contains them.

| Item | Example value |
| --- | --- |
| Server IP (a private address assigned to the VM) | `192.168.10.20` |
| HTTPS port | `18795` (any free port) |
| Test data directory (disposable, synthetic data only) | `C:\saplens2\runtime-test` |
| Releases built on the VM | `C:\saplens2\builds\<name>` |
| Certificate (PFX, SAN includes `192.168.10.20`) | `C:\ProgramData\SapLens2\tls\server.pfx` |
| Certificate password file | `C:\ProgramData\SapLens2\tls\cert-password` |
| Repository checkout | `C:\src\sap-lens` |

The certificate and password file are created once by an administrator with the commands in
[SERVER_NETWORK_ACCESS.md section 4](SERVER_NETWORK_ACCESS.md#windows-powershell-as-administrator), using `$ip = '192.168.10.20'` and a DNS name
of your choice. Nothing in this runbook creates or overwrites them.

## 1. Build a native release

Prerequisites: .NET 10 SDK, Node.js 24 or 25, Git. PowerShell 5.1 or 7.

```powershell
cd C:\src\sap-lens
git fetch origin experiment/dotnet-backend; git checkout experiment/dotnet-backend; git pull --ff-only
powershell -NoProfile -ExecutionPolicy Bypass -File .\experiments\dotnet-backend\scripts\build-release.ps1 -Output C:\saplens2\builds
```

`-ExecutionPolicy Bypass` on the `powershell -File` call applies to that one process only; it changes no machine or user policy. `-Output` is the
parent folder: each build creates a new folder `SAP-Lens-2-<version>-<UTC time>-<commit>-win-x64` inside it and never overwrites one.

`build-release.ps1` builds the UI and the solution, runs the tests, publishes both executables, validates the packages, writes `README.txt`,
`build-manifest.json` and `SHA256SUMS`, and verifies them with `verify-release.ps1`. It **does not install or start anything**. A completed build
proves compilation, the automated tests and the publish step; it says nothing about runtime behaviour on this VM (see
[section 8](#8-what-each-result-proves)).

Release layout (self-contained single-file executables; no .NET installation needed; no trimming, Native AOT or compression):

| Path in the release folder | Content |
| --- | --- |
| `server\SapLens.Api.exe` | Server: console process or Windows service. Everything managed, including the React UI, is inside the exe |
| `server\e_sqlite3.dll` | SQLite native library. It stays beside the exe (loaded from there, never extracted to a temporary folder, which a service account may not be allowed to use) |
| `desktop\SapLens2Prototype.exe` | Desktop (WebView2, loopback only). It extracts its native libraries (WebView2 loader, SQLite) to a temporary folder at start |
| `symbols\server\`, `symbols\desktop\` | `.pdb` debugging symbols; not needed at runtime |
| `build-manifest.json` | Commit, dirty flag, branch, version, build time (UTC), target platform, SDK and Node versions, publish settings, and the size and SHA-256 of every file |
| `README.txt` | Which executable to run and how to configure the Server |
| `SHA256SUMS` | SHA-256 of every file, `build-manifest.json` included (`sha256sum -c` format) |

Nothing else belongs in the release folder: no `appsettings.json`, data, logs, certificates or secrets. The Server refuses a data directory
inside its application folder (`startup refused: The data directory must be outside the application directory`), so a release folder can be
replaced or deleted without touching data.

```powershell
$release = Get-ChildItem C:\saplens2\builds -Directory -Filter 'SAP-Lens-2-*' | Sort-Object { (Get-Item (Join-Path $_.FullName 'build-manifest.json')).LastWriteTime } | Select-Object -Last 1
powershell -NoProfile -ExecutionPolicy Bypass -File C:\src\sap-lens\experiments\dotnet-backend\scripts\verify-release.ps1 -ReleasePath $release.FullName   # after copying a release, too
Get-Content (Join-Path $release.FullName 'build-manifest.json') | Select-Object -First 12
& (Join-Path $release.FullName 'server\SapLens.Api.exe') --version
& (Join-Path $release.FullName 'server\SapLens.Api.exe') --help
```

## 2. Start the Server with the test launcher (recommended)

`experiments\dotnet-backend\scripts\start-server-test.ps1` is a development and acceptance-testing utility, **not** a deployment mechanism.
It picks the newest complete release under `C:\saplens2\builds` (one with `build-manifest.json`, `server\SapLens.Api.exe` and `e_sqlite3.dll`;
earlier folder-publish releases with `manifest.json` and `server-win-x64\` are still recognized), validates the
configuration and runs the Server in the foreground.

```powershell
cd C:\src\sap-lens\experiments\dotnet-backend
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-server-test.ps1 -DryRun       # validate and show the command; starts nothing
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-server-test.ps1              # foreground; Ctrl+C stops it gracefully
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-server-test.ps1 -Background  # detached; logs and PID file in C:\saplens2\logs
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-server-test.ps1 -Stop        # stops exactly the process -Background started
.\scripts\start-server-test.ps1 -ListenAddress '192.168.10.20' -Port 18795 -DataDirectory 'C:\saplens2\runtime-test' `
    -AllowedHosts 'saplens2.test.example','192.168.10.20' -ReleasePath "C:\saplens2\builds\$name"
```

| Parameter | Default (example VM) | Notes |
| --- | --- | --- |
| `-ConfigFile` | see lookup order | Local JSON with environment values (`start-server-test.example.json` is the template); lookup: `-ConfigFile`, `%SAPLENS2_TEST_CONFIG%`, `C:\saplens2\start-server-test.local.json`, `start-server-test.local.json` next to the script |
| `-BuildsRoot` | `C:\saplens2\builds` | Searched when `-ReleasePath` is not given |
| `-ReleasePath` | none | A release folder, its `server` folder, or a plain `dotnet publish` folder |
| `-ListenAddress` | none (required, from the parameter or the local file) | Must be assigned to this machine; loopback and `0.0.0.0` are refused |
| `-Port` | `18790` | Must be free on that address |
| `-AllowedHosts` | the listen address | Host names or addresses clients type; the certificate SAN must cover each |
| `-TrustedProxies` | none | Reverse-proxy tests only: IP or CIDR of the proxy peer, passed as `--trusted-proxies` ([section 11](SERVER_NETWORK_ACCESS.md#11-reverse-proxy-pangolin-cloudflare)) |
| `-DataDirectory` | `C:\saplens2\runtime-test` | Absolute, local; refused inside `%ProgramData%\SapLens2`, `%ProgramData%\SAP Lens Server`, `%LOCALAPPDATA%\SAP Lens`, `%LOCALAPPDATA%\SAP Lens 2 Prototype`, Program Files, Windows or the release folder |
| `-CertificatePath` | `C:\ProgramData\SapLens2\tls\server.pfx` | Must exist; never created |
| `-CertificatePasswordFile` | `C:\ProgramData\SapLens2\tls\cert-password` | Must exist and be non-empty; the Server reads it, the launcher never does |
| `-DryRun` | off | Validates and prints the command without secrets |
| `-Background` / `-Stop` | off | Start detached (output to `<LogDirectory>\server-<UTC time>.out.log`/`.err.log`, identity in `saplens2-test-server.json`; waits until the port accepts connections, reports a startup refusal with its exit code and error log) / stop exactly that process (id and start time must match). A detached console process can only be stopped hard; a running import is recovered by its 30-second lease on the next start. Use the foreground or the Windows service for a graceful stop |
| `-LogDirectory` | `C:\saplens2\logs` | Background logs and PID file; refused inside the release folder |

The Server receives `--data-dir --network --listen --port --allowed-hosts --cert --cert-password-file`. Exit codes: `0` normal stop,
`2` the launcher refused the configuration (reason on stderr), `3` the Server refused it (`startup refused: <reason>`), anything else is the
Server's own exit code. The launcher never installs services, never changes firewall rules and never prints the certificate password. It
lists the names (not values) of inherited `SAP_LENS_V2_*` environment variables, because those still apply where no option is given (for
example `SAP_LENS_V2_AUTH` or `SAP_LENS_V2_TOKEN`).

Launcher tests (Pester 5; Windows ships Pester 3, so install 5 for the current user once):

```powershell
Install-Module Pester -MinimumVersion 5.5 -Scope CurrentUser -Force -SkipPublisherCheck
Invoke-Pester C:\src\sap-lens\experiments\dotnet-backend\scripts\tests -Output Detailed
```

On Windows the end-to-end block (a fake `SapLens.Api.exe` shell script) is skipped; it runs on Linux test hosts.

## 3. Start the Server manually

The same configuration without the launcher. The password stays in its file; it never appears on the command line.

```powershell
$server = Join-Path $release.FullName 'server\SapLens.Api.exe'
& $server --data-dir 'C:\saplens2\runtime-test' --network --listen 192.168.10.20 --port 18795 --allowed-hosts 192.168.10.20 `
  --cert 'C:\ProgramData\SapLens2\tls\server.pfx' --cert-password-file 'C:\ProgramData\SapLens2\tls\cert-password'
"exit code $LASTEXITCODE"
```

Startup is quiet until it succeeds. The console then shows JSON log lines, including `Listening on 192.168.10.20:18795 (https), network access
enabled, allowed hosts 192.168.10.20` and `TLS certificate CN=..., thumbprint ..., valid until ...`. A refusal prints `startup refused: <reason>`
and exits with code 3. Before listening, the Server performs a real TLS handshake with its certificate through SChannel, so a certificate
Windows cannot use is refused at startup instead of failing every client.

Without `--network` the Server binds only `127.0.0.1:18790` over HTTP. That is intended, not a fault (see the configuration reference).

### Accounts mode: first administrator

A fresh data directory starts with `setup_required`. Issue the one-time activation code on the VM (from the source checkout; the CLI is not
part of the release packages), then complete the setup in the browser:

```powershell
cd C:\src\sap-lens\experiments\dotnet-backend
dotnet run --project src\SapLens.Cli -c Release -- accounts-code --data C:\saplens2\runtime-test
```

## 4. Check HTTPS on the VM and from another machine

On the VM (PowerShell 7 `Invoke-WebRequest` or `curl.exe`; the CA must be trusted, see the next section):

```powershell
Get-NetTCPConnection -LocalPort 18795 -State Listen | Select-Object LocalAddress, LocalPort, OwningProcess   # only 192.168.10.20
curl.exe -s -o NUL -w "ready %{http_code}\n" https://192.168.10.20:18795/health/ready                            # 200
curl.exe -s -o NUL -w "ui %{http_code}\n" https://192.168.10.20:18795/                                          # 200
curl.exe -s -o NUL -w "api without credentials %{http_code}\n" https://192.168.10.20:18795/api/v1/roles          # 401
curl.exe -s -o NUL -w "auth state %{http_code}\n" https://192.168.10.20:18795/api/auth/state                    # 200
curl.exe -s -o NUL -w "foreign host %{http_code}\n" -H "Host: other.example" https://192.168.10.20:18795/health/ready   # 421
curl.exe -s -o NUL -w "plain http %{http_code}\n" http://192.168.10.20:18795/                                    # 000 or 400
```

From another machine on the same subnet, after the firewall rule in [section 6](#6-restricted-firewall-rule):

```powershell
Test-NetConnection 192.168.10.20 -Port 18795
curl.exe -s -o NUL -w "ready %{http_code}\n" https://192.168.10.20:18795/health/ready     # 200 with the CA trusted, never with -k
```

Then open `https://192.168.10.20:18795/` in a browser. It must show a valid lock, sign in, and run a Role Lookup after a synthetic import.

## 5. Validate the TLS certificate

```powershell
$pfx = Get-PfxData -FilePath C:\ProgramData\SapLens2\tls\server.pfx `
  -Password (ConvertTo-SecureString (Get-Content C:\ProgramData\SapLens2\tls\cert-password -Raw) -AsPlainText -Force)   # administrator prompt only
$cert = $pfx.EndEntityCertificates[0]
$cert | Format-List Subject, NotBefore, NotAfter, Thumbprint, HasPrivateKey
($cert.Extensions | Where-Object { $_.Oid.Value -eq '2.5.29.17' }).Format($true)    # SAN: must list 192.168.10.20 and every allowed host name
($cert.Extensions | Where-Object { $_.Oid.Value -eq '2.5.29.37' }).Format($true)    # EKU: Server Authentication
```

From a client, check the chain the browser will see (the CA certificate `saplens2-ca.cer` imported into the client's Trusted Root store):

```powershell
Import-Certificate -FilePath .\saplens2-ca.cer -CertStoreLocation Cert:\CurrentUser\Root
curl.exe -v -s -o NUL https://192.168.10.20:18795/health/ready 2>&1 | Select-String 'SSL|subject|issuer|expire'
```

The Server itself refuses certificates that have no private key, are outside their validity, are not for server authentication, have an RSA
key below 2048 bits, or whose SAN misses an allowed host. Chain trust is the client's decision.

## 6. Restricted firewall rule

The Server never changes the firewall. An administrator adds one rule: this program, this address and port, one trusted subnet, Domain and
Private profiles only.

```powershell
$exe = Join-Path $release.FullName 'server\SapLens.Api.exe'
New-NetFirewallRule -DisplayName 'SAP Lens 2 HTTPS (test VM)' -Direction Inbound -Action Allow -Protocol TCP `
  -LocalAddress 192.168.10.20 -LocalPort 18795 -RemoteAddress 192.168.10.0/24 -Profile Domain,Private -Program $exe
Get-NetFirewallRule -DisplayName 'SAP Lens 2 HTTPS (test VM)' | Get-NetFirewallAddressFilter
Remove-NetFirewallRule -DisplayName 'SAP Lens 2 HTTPS (test VM)'      # when the test is finished
```

The rule names one release's executable. Update `-Program` when you test a newer release.

## 7. Logs, stop, restart and persistence

| Mode | Where the log goes |
| --- | --- |
| Console (launcher or manual start) | JSON lines on the console only; redirect if you need a file: `... 2>&1 \| Tee-Object C:\saplens2\runtime-test-console.log` |
| Windows service | `<data-dir>\logs\server-YYYYMMDD.log` (same lines); Service Control Manager events in the System event log |

Stop: press **Ctrl+C** in the console. The host shuts down gracefully within 15 seconds: a running import is handed back as Queued and the
database is closed. Avoid `Stop-Process -Force` and `taskkill /f`: they skip the graceful path. After a hard stop, any running job is
recovered when its 30-second lease expires.

Restart and persistence check:

1. Import the synthetic roles and users CSVs (Data Sources), note the role and user counts, and record one review decision.
2. Stop with Ctrl+C. `Get-Process SapLens.Api -ErrorAction SilentlyContinue` returns nothing.
3. Start again with the same command. Sign in again (sessions do not survive a restart). The counts, the decision and its history are
   unchanged, and `/api/v1/admin/integrity` reports `database_ok: true` (shared-token client) or Settings → Data Health shows no integrity
   finding.
4. `C:\saplens2\runtime-test` holds `sap-lens-v2.sqlite3` (and `-wal`/`-shm` while running), `api-token` and the accounts store.

Reset: stop the Server and delete `C:\saplens2\runtime-test`. It holds only synthetic test data.

## 8. What each result proves

Record each level separately. A successful build is **never** runtime acceptance.

| Level | Proven by | Status for the current build |
| --- | --- | --- |
| 1 Compilation | `dotnet build` / `build-release.ps1` without errors | Reported for `ea09de2` on the VM |
| 2 Automated tests | `dotnet test` (Linux and Windows) and Pester launcher tests | Reported for `ea09de2` (238 tests); later commits validated on Linux only |
| 3 Publish | `server\` and `desktop\` produced, validated, checksummed and verified (`verify-release.ps1`) | Folder layout reported for `ea09de2` (Server 117 MB, Desktop 151 MB); single-file layout built and verified on Linux only (Server 108.5 MB, Desktop 150.1 MB) |
| 4 Native Server startup | Section 3: `Listening on ... (https)` and no refusal | Pending |
| 5 HTTPS connectivity | Section 4 from the VM and another machine; valid chain without `-k` | Pending |
| 6 Browser UI | React UI loads with a valid lock from another machine | Pending |
| 7 Authentication and API | First administrator activated, sign-in works, import and lookups return data, 401/421 refusals as listed | Pending |
| 8 Restart and persistence | Section 7 | Pending |
| 9 Desktop startup | `SapLens2Prototype.exe --self-check` exit 0, window and WebView2 ([checklist](DESKTOP_SERVER_DEPLOYMENT.md#acceptance-checklist-windows)) | Pending for the current build |
| 10 Windows service | [Section 5 procedure](SERVER_NETWORK_ACCESS.md#5-deployment): install, start, stop, restart, recovery, reboot, removal | Pending (never run) |
| 11 Full Windows acceptance | Levels 1 to 10 on one commit | Not achieved |

Levels 1 to 3 run without starting the product. Only levels 4 to 10, executed on Windows, count as runtime acceptance.
