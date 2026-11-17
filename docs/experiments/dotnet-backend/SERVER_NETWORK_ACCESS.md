# Server network access (trusted LAN)

How the prototype Server can be reached from other devices on a trusted local network (desktop and mobile browsers) without weakening its
defaults. The Desktop stays loopback-only. Tags as in [README](README.md).

**Verification status:** the policy, HTTPS, cookies and CSRF checks are covered by automated tests, including a real HTTPS listener on this
machine's non-loopback interface [T] on Linux. On Windows 11 that test failed at `fe4a6e8` (in-memory TLS key, see below); the fix is
not yet re-run on Windows [U]. Access **from another device** (desktop or mobile) has **not** been verified, and nothing ran on
Windows [U]. Use the checklist at the end.

## 1. Secure defaults and fail-closed rules

| Rule | Behaviour |
| --- | --- |
| Default | `http://127.0.0.1:18790`, network access off |
| Non-loopback address without `--network` | Refused at startup |
| `--network` | Needs **one specific** address; `0.0.0.0` and `::` are always refused (never "all interfaces") |
| Address range | Only private or link-local unicast: 10/8, 172.16/12, 192.168/16, 169.254/16, fc00::/7, fe80::/10. Public addresses are refused |
| Protocol | HTTPS (TLS 1.2/1.3) is mandatory with `--network`; plain HTTP on a LAN address cannot be configured |
| Certificate | Must load, have a private key, be within its validity period, allow server authentication (if EKU present), RSA ≥ 2048, and its SAN must cover every `--allowed-hosts` entry. Expiry within 30 days is logged as a warning. Chain trust is the clients' decision |
| Host names | Requests are answered only for loopback names and the explicit `--allowed-hosts` list (421 otherwise): no wildcards |
| Desktop | Loopback only; network, certificate and host options are refused |
| Configuration errors | Unknown options, missing values, invalid ports or addresses: exit code 3 with the reason; nothing starts |
| Secrets | `--cert-password` and `--token` are refused on the command line (process lists are readable by other users) |

The operator cannot widen the address policy: no option or environment variable does it (tests replace it only through an internal hook).

### Windows TLS: keys must not be in-memory only

Windows 11 run of the LAN HTTPS test (`fe4a6e8`) [W]: the first HTTPS request failed with "Received an unexpected EOF or 0 bytes from the
transport stream" on every run, while Linux passed. Cause [C]: the test certificate came from `CertificateRequest.CreateSelfSigned`, whose
private key on Windows is an ephemeral (in-memory) CNG key. Windows' TLS stack (SChannel) cannot use such a key for a server, so Kestrel
aborted every handshake (logged only at Debug) and clients saw EOF; OpenSSL on Linux uses the in-memory key, hence "Linux passes". The
client already bypassed system proxies (`UseProxy = false`) and the listener was up (EOF, not "connection refused"), which excluded those.
The production CLI path converted PEM keys but the host itself did not guarantee it for any certificate object it receives.

Fix [T on Linux; U on Windows until re-run]:

- `CertificatePolicy.PrepareForServer`: on Windows, a certificate with an ephemeral key is re-imported through PKCS#12 into a key container
  of the process (removed when the host stops). Linux is unchanged. PEM loading uses the same function.
- **Startup TLS self-check**: before the host is built, the server performs a real TLS handshake with its certificate through the
  operating system's TLS stack on a private loopback socket. An unusable certificate stops startup (exit code 3) with the server-side
  error instead of producing EOFs for every client.
- Kestrel's TLS handshake failures (category `Microsoft.AspNetCore.Server.Kestrel.Https`, Debug) are kept in the console and service file
  logs: exception and connection id only, no secrets.
- If the self-check passes but LAN clients still see EOF, the cause is outside the certificate: endpoint security or TLS inspection on the
  port, or a firewall resetting connections. The server log shows whether the handshake reached Kestrel.

Windows re-validation (CMD, one command per line):

```bat
cd /d C:\src\sap-lens && git fetch origin experiment/dotnet-backend && git checkout experiment/dotnet-backend && git pull --ff-only
cd /d C:\src\sap-lens\experiments\dotnet-backend && dotnet build SapLens.slnx -c Release
dotnet test tests\SapLens.Tests -c Release --no-build --filter "FullyQualifiedName~In_memory_keys_are_prepared_for_the_windows_tls_stack" --logger "console;verbosity=detailed"
dotnet test tests\SapLens.Tests -c Release --no-build --filter "FullyQualifiedName~Startup_tls_self_check" --logger "console;verbosity=detailed"
dotnet test tests\SapLens.Tests -c Release --no-build --filter "FullyQualifiedName~LanHttpsTests" --logger "console;verbosity=detailed"
dotnet test tests\SapLens.Tests -c Release --no-build
dotnet publish src\SapLens.Api -c Release -r win-x64 --self-contained true -o C:\saplens2\server
powershell -NoProfile -Command "New-Item -ItemType Directory -Force C:\saplens2 | Out-Null; $c = New-SelfSignedCertificate -DnsName localhost -CertStoreLocation Cert:\CurrentUser\My -NotAfter (Get-Date).AddDays(30); Export-PfxCertificate -Cert $c -FilePath C:\saplens2\lab.pfx -Password (ConvertTo-SecureString 'lab-only-password' -AsPlainText -Force) | Out-Null; Remove-Item $c.PSPath"
set "SAP_LENS_V2_CERT_PASSWORD=lab-only-password"
C:\saplens2\server\SapLens.Api.exe --data-dir C:\saplens2\tls-data --port 18792 --cert C:\saplens2\lab.pfx
```

Expected: the first test confirms the premise (the original key is ephemeral, the prepared one is not); all tests pass; the last command logs
`Listening on 127.0.0.1:18792 (https)` and a `TLS certificate ...` line (the startup self-check has already completed a real SChannel
handshake; a failure would print `startup refused: The TLS certificate cannot be used by this system's TLS stack (...)` and exit 3). Stop it
with Ctrl+C, then `set SAP_LENS_V2_CERT_PASSWORD=`. The lab PFX and password are for this check only.

## 2. Configuration reference

Source of truth: `ServerConfiguration.cs` (parsing), `HostSettings.cs` (validation), `SapLensHost.cs` (startup), covered by `NetworkPolicyTests`,
`LanHttpsTests` and `PublishTests`. `SapLens.Api --help` prints the same list; `SapLens.Api --version` prints the version and source commit.
Both exit 0 without reading any configuration.

| Setting | Option | Environment variable | Default |
| --- | --- | --- | --- |
| Data directory (absolute, local) | `--data-dir` | `SAP_LENS_V2_DATA_DIR` | **required**, no default |
| Listen address (IP literal) | `--listen` | `SAP_LENS_V2_LISTEN` | `127.0.0.1` |
| Port (HTTPS when a certificate is set) | `--port` | `SAP_LENS_V2_PORT` | `18790` |
| Network access enabled | `--network` | `SAP_LENS_V2_NETWORK=true` | disabled |
| Host names / addresses clients use | `--allowed-hosts a,b` | `SAP_LENS_V2_ALLOWED_HOSTS` | none |
| Certificate (`.pfx`/`.p12`, or PEM) | `--cert` | `SAP_LENS_V2_CERT` | none (HTTP) |
| PEM private key | `--cert-key` | `SAP_LENS_V2_CERT_KEY` | none |
| Certificate password file | `--cert-password-file` (preferred) | `SAP_LENS_V2_CERT_PASSWORD_FILE` | none |
| Certificate password | (never an option) | `SAP_LENS_V2_CERT_PASSWORD`, used only without a password file | none |
| Access token (API clients, at least 32 characters) | (never an option) | `SAP_LENS_V2_TOKEN` | generated once into `<data-dir>/api-token` |
| Browser authentication | `--auth accounts\|shared-token` | `SAP_LENS_V2_AUTH` | `accounts` |
| Name recorded for API clients that use the access token | | `SAP_LENS_V2_PRINCIPAL` | `server-operator` |
| Background worker off | `--no-worker` | | on |
| Trusted reverse proxies (IP or CIDR; needs `--network`) | `--trusted-proxies a,b` | `SAP_LENS_V2_TRUSTED_PROXIES` | none: forwarded headers ignored |
| Trusted proxy hops to walk back through | `--trusted-proxy-hops 1-5` | `SAP_LENS_V2_TRUSTED_PROXY_HOPS` | `1` |
| Help / version | `--help`, `-h` / `--version` | | |

Rules:

- **Precedence:** an option wins over its environment variable; an empty variable counts as unset. `--network` is on when the option is given
  or `SAP_LENS_V2_NETWORK` is `true` (case-insensitive).
- **Required:** only the data directory. A bare `SapLens.Api.exe` therefore refuses to start: `--data-dir (or SAP_LENS_V2_DATA_DIR) is
  required.` This is deliberate: no implicit data location.
- **Loopback start:** without `--network` the Server listens on `http://127.0.0.1:18790` (or `--port`), reachable only from the same machine.
  A certificate without `--network` gives HTTPS on loopback.
- **LAN binding** (`--network`): one specific private or link-local address with `--listen` (10/8, 172.16/12, 192.168/16, 169.254/16,
  fc00::/7, fe80::/10; never `0.0.0.0`, `::`, loopback or a public address), a fixed non-zero port, `--cert`, and `--allowed-hosts`.
- **HTTPS:** TLS 1.2 or 1.3. The certificate must load, have a private key, be valid now, allow server authentication (if it has an EKU), use
  RSA of at least 2048 bits, and list every allowed host in its SAN (IP entries for addresses, DNS entries for names; `*.example` covers one
  label). It is proven by a real TLS handshake through the operating system's stack before the listener starts. Expiry within 30 days is
  logged as a warning.
- **Allowed hosts:** requests whose `Host` is not `localhost`, `127.0.0.1`, `::1` or (with `--network`) an `--allowed-hosts` entry receive
  `421 Unexpected host.` Entries are exact names or addresses: no wildcards, schemes, paths or ports. On unsafe requests (anything but
  GET, HEAD, OPTIONS) an `Origin` header must equal the request's own `scheme://host[:port]`, otherwise `403 Cross-origin request refused.`;
  without the access-token header such a request also needs that same-origin `Origin` (or no `Origin` and `Sec-Fetch-Site: same-origin`),
  otherwise `403 State-changing requests need a same-origin signal.` Accounts mode adds its per-session CSRF token.
- **Origin comparison** is exact: scheme, host (DNS names case-insensitive, IP literals by value, IPv6 with brackets) and port, with 443/80
  filled in for an origin or Host without a port. `https://lens.example` equals Host `lens.example` or `lens.example:443`, never
  `lens.example:18795`, `sub.lens.example` or `lens.example.evil`. An Origin with a path, query, user info or the value `null` never matches.
- **Reverse proxies** (`--trusted-proxies`): opt-in, see [section 11](#11-reverse-proxy-pangolin-cloudflare). Without it, `X-Forwarded-*` and
  `Forwarded` headers are ignored, from every peer including loopback.
- **Authentication:** `accounts` (default) uses individual v1-compatible accounts with server sessions and roles; `shared-token` is one
  operator identity for everyone holding the token (isolated tests only). API clients always may use the `X-SAP-Lens-Token` header.
- **Certificate password file:** read once at startup; trailing CR/LF removed. A missing file stops startup. Restrict it to administrators
  and the service account. `--cert-password` and `--token` are refused on the command line, where other local users could read them.
- **Data directory:** absolute and local (UNC paths, `//host/share` and mapped network drives are refused, because SQLite locking is
  unreliable there). It is created if missing, with the `api-token` file inside, as soon as the options parse; a later validation failure
  (for example a missing `--allowed-hosts`) can leave that new directory behind. Use a separate directory per Server instance; never share
  one with the Desktop or v1.
- **Invalid configuration** stops startup before anything listens: the process prints `startup refused: <reason>` on stderr and exits with
  code **3**. Examples: `Unknown option '--bind'.`, `--port needs a value.`, `--port must be between 1 and 65535.`, `--listen must be an IP
  address, not 'server.lan'.`, `--data-dir must be an absolute path.`, `Listening on 192.168.10.20 needs network access to be enabled explicitly
  (--network) with HTTPS.`, `Network access requires HTTPS: configure a certificate (--cert).`, `Network access needs the host names or
  addresses clients use (--allowed-hosts).`, `The certificate password file '...' does not exist.`, `The certificate '...' could not be opened
  (wrong password, missing key or damaged file).`, `The TLS certificate is not usable: Its subject alternative names do not include '...'.`

Examples (replace every address, name and path):

```powershell
# Windows: loopback only (local checks)
& .\SapLens.Api.exe --data-dir C:\saplens2\local-test
# Windows: LAN HTTPS, password from a protected file
& .\SapLens.Api.exe --data-dir C:\saplens2\runtime-test --network --listen 192.168.10.20 --port 18795 `
  --allowed-hosts saplens2.test.example,192.168.10.20 --cert C:\ProgramData\SapLens2\tls\server.pfx `
  --cert-password-file C:\ProgramData\SapLens2\tls\cert-password
# Windows: the same through environment variables (current session only)
$env:SAP_LENS_V2_DATA_DIR = 'C:\saplens2\runtime-test'; $env:SAP_LENS_V2_NETWORK = 'true'; $env:SAP_LENS_V2_LISTEN = '192.168.10.20'
$env:SAP_LENS_V2_PORT = '18795'; $env:SAP_LENS_V2_ALLOWED_HOSTS = '192.168.10.20'; $env:SAP_LENS_V2_CERT = 'C:\ProgramData\SapLens2\tls\server.pfx'
$env:SAP_LENS_V2_CERT_PASSWORD_FILE = 'C:\ProgramData\SapLens2\tls\cert-password'
& .\SapLens.Api.exe
```

```bash
# Linux: loopback only
./SapLens.Api --data-dir /var/tmp/saplens2-local
# Linux: LAN HTTPS with a PEM certificate and key
./SapLens.Api --data-dir /var/lib/saplens2 --network --listen 192.168.10.20 --port 18791 \
  --allowed-hosts saplens2.corp.example,192.168.10.20 --cert /etc/saplens2/tls/server.crt --cert-key /etc/saplens2/tls/server.key
```

Nothing secret is stored in committed files. The startup log states the address, port, scheme, network mode, allowed hosts and the
certificate subject, thumbprint and expiry, never a password or token. For a step-by-step test on one Windows VM see
[WINDOWS_TEST_VM.md](WINDOWS_TEST_VM.md).

## 3. Authentication and authorization review

### Accounts mode (default)

The Server uses the SAP Lens v1 account model, ported to .NET on the same SQLite schema (`<data-dir>/security/accounts.sqlite3`, directory
`0700`, file `0600`), so an existing v1 account store can be adopted by copying it there while the server is stopped.

| Aspect | Implementation |
| --- | --- |
| First administrator | The server creates an empty store at its first start (`/api/auth/state` reports `setup_required`). A local operator runs `SapLens.Cli accounts-code --data <data-dir>`; it prints a single-use code (15 minutes, 5 attempts, stored only as a SHA-256). The React sign-in page completes activation with the code; setup then closes for good |
| Recovery | `SapLens.Cli accounts-code --data <data-dir> --recover-administrator <username>`: a local recovery code for an existing administrator; sign-in with the old password is blocked until it is used. The API can consume codes but never issue them |
| Passwords | Argon2id (`m=65536, t=3, p=2`, 16-byte salt, 32-byte hash, PHC string format compatible with Python argon2-cffi); 12 to 1024 characters; v1 PBKDF2 verifiers are accepted and replaced with Argon2id at the next sign-in; unknown users take the same hashing path |
| Sessions | Random token in an `HttpOnly`, `SameSite=Strict` cookie (`Secure` over HTTPS); only its SHA-256 is stored. Idle (default 30 min) and absolute (default 12 h) lifetimes are an administrator policy. Password, role or status changes and password resets end every session of the account |
| CSRF | A per-session secret in a readable `sap-lens-csrf` cookie that the React client echoes in `X-SAP-Lens-CSRF` on every write (only its digest is stored), in addition to the same-origin check below |
| Roles | `administrator`, `reviewer`, `viewer`, enforced per route by the v1 permission map (deny by default; unknown writes are refused for everyone). Deliberate differences from v1: `PUT`, `PATCH` and `DELETE` on administrator paths are administrator writes (v1 refused them for every session, so the retention policy, SoD reference library, report branding and group renames could not be saved in Server account mode), and reads under `/api/v1/admin` are administrator reads. Viewers read and export; reviewers additionally record review decisions; administrators manage settings, data sources, saved filters and accounts. The Access Package preview and export are open to every signed-in role (v1 maps them to no permission at all, which refuses them for everyone in session mode; they never change data) |
| Brute force | Per client digest: the fifth failure locks for 30 s, each further failure doubles the lock up to 15 min; separate counters for password-reset codes |
| Audit | Account, role, password, session and policy events in the store's `audit` table with the actor's public identity; never verifiers, tokens or codes. Unauthenticated denial events are capped at the newest 10 000 |
| Transport | Plain HTTP only from a loopback peer; on the network the server is HTTPS-only (`secure_transport_required`) |
| Attribution | Every write (imports, confirmations, settings, saved filters, review decisions) records the signed-in username |
| API clients | The protected access token (`X-SAP-Lens-Token`) still authenticates automation as the operator principal (`SAP_LENS_V2_PRINCIPAL`, provenance `access-token`). It cannot administer accounts, because account operations need a real session |
| Backups, storage, retention | On a Server these need a signed-in administrator account (as in v1); the shared token and a token-only API client are refused (403), including `POST /api/v1/admin/backups`. Archives are AES-256-GCM (SLBAK3) with Argon2id passphrases or the host key; the host key file lives outside the data directory with owner-only permissions, its recovery copy is escrowed and verified, and keys and passphrases are never logged or written to reports. Restores apply at the next start with an encrypted recovery backup of the current data and automatic rollback |
| SAP Lens 1 migration | Local operation of the server binary (`--migrate-v1`); the v1 data is only read, a `.slbak` is authenticated and checked against its manifest before use, the secret is typed without echo or read from the recovery key file, and all intermediate data stays in the private data directory. See [V1_MIGRATION.md](V1_MIGRATION.md) |

`--auth shared-token` restores the earlier single-secret browser sign-in described next (for isolated tests only).

### Shared-token mode (`--auth shared-token`)

| Aspect | Implementation |
| --- | --- |
| API clients | `X-SAP-Lens-Token` header, constant-time comparison. Browsers never send this header cross-site, so token requests need no CSRF token |
| Browsers | `/login.html` posts the token once (plain HTML form, no script handles it) to `/auth/login`; the server answers with a random session id cookie: `HttpOnly`, `SameSite=Strict`, `Path=/`, and over HTTPS `Secure` with the `__Host-` name prefix (no `Domain`). The cookie never contains the token; only a SHA-256 of the session id is kept, in memory, 8 h |
| CSRF / origin | Every state-changing request that is not header-authenticated (sign-in, sign-out, cookie API calls) must carry `Origin` equal to this server or `Sec-Fetch-Site: same-origin`; any foreign `Origin` is refused. `SameSite=Strict` is the second layer. No CORS is offered |
| Brute force | Failed sign-ins: 5 per minute per client address and 30 per minute in total, then 429 |
| Exposure of credentials | Token never in URLs (form POST body), never in page script (Desktop injects it outside the page; the browser holds only an HttpOnly cookie), never logged; `autocomplete="off"` on the token field |
| Transport | HSTS (`max-age=31536000`) on HTTPS responses; CSP `script-src 'self'`, `frame-ancestors 'none'`, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: same-origin` |
| Authorization | **None beyond authentication**: everyone signed in can import, confirm held imports and record decisions. On a Server, application backups, restore, storage and retention are refused in this mode |

### Limitations of the shared token (why this is a trusted-LAN prototype only)

- One secret for everyone: no individual identity, so every review decision is attributed to `SAP_LENS_V2_PRINCIPAL`. **Not acceptable for
  real audit evidence.**
- No roles or separation of duties (reviewer, approver, administrator).
- Rotation means changing the token and restarting; all users sign in again. Sessions are lost on every restart.
- Throttling state is in memory per process. A device on the LAN can trigger the per-address limit for its own address and, with 30
  failures, delay sign-ins for others for a minute (a deliberate trade-off against brute force).
- Typing a 43-character token on a phone is error-prone; people will be tempted to store it insecurely.

### Future identity model (required before production use)

OpenID Connect against the corporate identity provider (for example Microsoft Entra ID) for browsers and mobile devices, or Windows
Integrated Authentication (Negotiate) on domain networks; per-user identity in every decision; roles (viewer, reviewer, approver,
administrator) enforced per endpoint; MFA through the identity provider; short sessions with server-side revocation; the shared token kept
only for automation, scoped and rotatable.

## 4. TLS certificates

Prefer a certificate from the company CA (for example AD CS) with the DNS name users will type and the server's IP address in the SAN. The
commands below create a small private CA for a lab; keep the CA private key off the server.

### Windows (PowerShell as administrator)

```powershell
$dns = 'saplens2.corp.example'; $ip = '192.168.10.20'
New-Item -ItemType Directory -Force C:\ProgramData\SapLens2\tls | Out-Null
$ca = New-SelfSignedCertificate -Subject 'CN=SAP Lens 2 LAN CA' -KeyUsage CertSign,CRLSign,DigitalSignature -KeyLength 3072 -HashAlgorithm SHA256 `
  -NotAfter (Get-Date).AddYears(5) -CertStoreLocation Cert:\CurrentUser\My -KeyExportPolicy Exportable `
  -TextExtension @('2.5.29.19={critical}{text}ca=1&pathlength=0')
$server = New-SelfSignedCertificate -Subject "CN=$dns" -Signer $ca -KeyLength 2048 -HashAlgorithm SHA256 -NotAfter (Get-Date).AddDays(397) `
  -CertStoreLocation Cert:\CurrentUser\My -KeyExportPolicy Exportable `
  -TextExtension @("2.5.29.17={text}DNS=$dns&IPAddress=$ip", '2.5.29.37={text}1.3.6.1.5.5.7.3.1')
# Random PFX password, written only to an ACL-protected file the service reads (--cert-password-file).
$bytes = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes); $plain = [Convert]::ToBase64String($bytes)
Export-PfxCertificate -Cert $server -FilePath C:\ProgramData\SapLens2\tls\server.pfx -Password (ConvertTo-SecureString $plain -AsPlainText -Force) | Out-Null
Set-Content -Path C:\ProgramData\SapLens2\tls\cert-password -Value $plain -NoNewline -Encoding ASCII; Remove-Variable plain
Export-Certificate -Cert $ca -FilePath C:\ProgramData\SapLens2\tls\saplens2-ca.cer | Out-Null   # public CA certificate for clients
# Lab only: remove the CA and server keys from the user store (export the CA with a password to offline media first if you need it again).
Remove-Item $server.PSPath; Remove-Item $ca.PSPath
```

### Linux (OpenSSL 3)

```bash
DNS=saplens2.corp.example; IP=192.168.10.20; sudo install -d -m 0750 -o root -g saplens2 /etc/saplens2/tls; cd "$(mktemp -d)"
openssl req -x509 -newkey rsa:3072 -sha256 -days 1825 -noenc -keyout ca.key -out ca.crt -subj "/CN=SAP Lens 2 LAN CA" \
  -addext "basicConstraints=critical,CA:TRUE,pathlen:0" -addext "keyUsage=critical,keyCertSign,cRLSign"
openssl req -newkey rsa:2048 -noenc -keyout server.key -out server.csr -subj "/CN=$DNS"
printf "subjectAltName=DNS:%s,IP:%s\nextendedKeyUsage=serverAuth\nkeyUsage=critical,digitalSignature,keyEncipherment\nbasicConstraints=CA:FALSE\n" "$DNS" "$IP" > ext.cnf
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 397 -sha256 -extfile ext.cnf -out server.crt
sudo install -m 0644 server.crt /etc/saplens2/tls/server.crt
sudo install -m 0600 -o root -g root server.key /etc/saplens2/tls/server.key    # delivered to the service via systemd LoadCredential
cp ca.crt ~/saplens2-ca.crt                                                        # distribute to clients; move ca.key offline
```

397 days keeps the leaf within the validity limits that Apple and browsers enforce.

## 5. Deployment

### Windows Server (PowerShell as administrator)

**Status:** this procedure uses only standard Windows tooling (`New-Service`, `sc.exe`, `icacls`); SAP Lens ships no installer or service
tool. The executable contains the service host (`AddWindowsService`, service name `SapLens2`), but the procedure has **not been run on
Windows yet** [U]. Treat every step as pending acceptance.

```powershell
# On the build machine
dotnet publish experiments\dotnet-backend\src\SapLens.Api -c Release -r win-x64 --self-contained true -o C:\Build\saplens2-server

# On the server
$app = 'C:\Program Files\SapLens2\server'; $data = 'C:\ProgramData\SapLens2\data'; $tls = 'C:\ProgramData\SapLens2\tls'
New-Item -ItemType Directory -Force $app, $data | Out-Null
Copy-Item C:\Build\saplens2-server\* $app -Recurse -Force
$bin = "`"$app\SapLens.Api.exe`" --data-dir `"$data`" --network --listen 192.168.10.20 --port 18791 " +
       "--allowed-hosts saplens2.corp.example,192.168.10.20 --cert `"$tls\server.pfx`" --cert-password-file `"$tls\cert-password`""
New-Service -Name SapLens2 -DisplayName 'SAP Lens 2 prototype server' -BinaryPathName $bin -StartupType Automatic
sc.exe config SapLens2 obj= "NT SERVICE\SapLens2"                 # virtual service account, no password
sc.exe failure SapLens2 reset= 86400 actions= restart/60000
foreach ($dir in $data, $tls) {                                     # only the service and administrators
  icacls $dir /inheritance:r /grant:r 'Administrators:(OI)(CI)F' 'SYSTEM:(OI)(CI)F' 'NT SERVICE\SapLens2:(OI)(CI)M' | Out-Null }
icacls "$tls\cert-password" /inheritance:r /grant:r 'Administrators:F' 'NT SERVICE\SapLens2:R' | Out-Null
Start-Service SapLens2; Get-Service SapLens2
Get-Content "$data\logs\server-*.log" -Tail 20                       # startup line: address, port, https, certificate expiry
Get-Content "$data\api-token"                                        # the token users enter at sign-in; share it through a secure channel
```

### Linux (systemd)

```bash
dotnet publish experiments/dotnet-backend/src/SapLens.Api -c Release -r linux-x64 --self-contained true -o /tmp/saplens2-server
sudo useradd --system --home-dir /var/lib/saplens2 --shell /usr/sbin/nologin saplens2
sudo install -d -m 0755 /opt/saplens2 && sudo cp -r /tmp/saplens2-server /opt/saplens2/server
sudo tee /etc/systemd/system/saplens2.service >/dev/null <<'UNIT'
[Unit]
Description=SAP Lens 2 prototype server
Wants=network-online.target
After=network-online.target

[Service]
Type=notify
User=saplens2
Group=saplens2
StateDirectory=saplens2
StateDirectoryMode=0700
LoadCredential=server.key:/etc/saplens2/tls/server.key
ExecStart=/opt/saplens2/server/SapLens.Api --data-dir /var/lib/saplens2 --network --listen 192.168.10.20 --port 18791 \
  --allowed-hosts saplens2.corp.example,192.168.10.20 --cert /etc/saplens2/tls/server.crt --cert-key %d/server.key
Restart=on-failure
TimeoutStopSec=30
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadWritePaths=/var/lib/saplens2

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload && sudo systemctl enable --now saplens2
systemctl status saplens2 --no-pager; journalctl -u saplens2 -n 20 --no-pager
sudo cat /var/lib/saplens2/api-token
```

## 6. Firewall: one trusted subnet, one port, nothing automatic

The Server never creates firewall rules. An administrator adds exactly one inbound rule for the trusted subnet.

```powershell
# Windows: only from 192.168.10.0/24, only to this address and port, only on Domain/Private profiles, only for this program
New-NetFirewallRule -DisplayName 'SAP Lens 2 HTTPS (trusted LAN)' -Direction Inbound -Action Allow -Protocol TCP `
  -LocalAddress 192.168.10.20 -LocalPort 18791 -RemoteAddress 192.168.10.0/24 -Profile Domain,Private `
  -Program 'C:\Program Files\SapLens2\server\SapLens.Api.exe'
Get-NetFirewallRule -DisplayName 'SAP Lens 2 HTTPS (trusted LAN)' | Get-NetFirewallAddressFilter
# Remove: Remove-NetFirewallRule -DisplayName 'SAP Lens 2 HTTPS (trusted LAN)'
```

```bash
# Linux, ufw
sudo ufw allow in from 192.168.10.0/24 to 192.168.10.20 port 18791 proto tcp comment 'SAP Lens 2 trusted LAN'
# Linux, firewalld
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="192.168.10.0/24" destination address="192.168.10.20" port port="18791" protocol="tcp" accept'
sudo firewall-cmd --reload
# Linux, nftables (inet filter table with a default-drop input chain)
sudo nft add rule inet filter input ip saddr 192.168.10.0/24 ip daddr 192.168.10.20 tcp dport 18791 accept
```

Never publish the port on an internet-facing router or reverse proxy. The private-address rule prevents binding a public address, but NAT
port forwarding would still expose the service: do not configure it.

## 7. LAN connectivity verification (from another device)

Clients resolve `saplens2.corp.example` through DNS (or the hosts file on desktops) and trust `saplens2-ca` (Windows: import into
"Trusted Root Certification Authorities"; Linux: `--cacert` or the system store).

```powershell
# Windows client (CA imported: Import-Certificate -FilePath saplens2-ca.cer -CertStoreLocation Cert:\CurrentUser\Root)
Test-NetConnection saplens2.corp.example -Port 18791
curl.exe -s -o NUL -w "ready %{http_code}\n" https://saplens2.corp.example:18791/health/ready          # 200
curl.exe -s -o NUL -w "api without token %{http_code}\n" https://saplens2.corp.example:18791/api/v1/roles   # 401
curl.exe -s -o NUL -w "plain http %{http_code}\n" http://saplens2.corp.example:18791/                    # 000 or 400: no page over HTTP
```

```bash
# Linux/macOS client
curl --cacert saplens2-ca.crt -s -o /dev/null -w "ready %{http_code}\n" https://saplens2.corp.example:18791/health/ready
curl --cacert saplens2-ca.crt -s -o /dev/null -w "api without token %{http_code}\n" https://saplens2.corp.example:18791/api/v1/roles
curl --cacert saplens2-ca.crt -s -o /dev/null -w "foreign host %{http_code}\n" -H "Host: other.example" https://192.168.10.20:18791/   # 421
openssl s_client -connect 192.168.10.20:18791 -servername saplens2.corp.example -CAfile saplens2-ca.crt -verify_return_error </dev/null | grep -E "Verify return code|Protocol"
# On the server: only the configured address listens
ss -ltn 'sport = :18791'          # Linux; Windows: Get-NetTCPConnection -LocalPort 18791 -State Listen
```

From a device **outside** the trusted subnet the connection must time out (firewall).

## 8. Mobile browser testing

1. Copy the **public** CA certificate (`saplens2-ca.cer`/`.crt`, never the PFX or a key) to the device (mail, MDM, AirDrop).
2. iOS/iPadOS: open it, Settings → Profile Downloaded → Install; then Settings → General → About → Certificate Trust Settings → enable full
   trust for "SAP Lens 2 LAN CA". Android: Settings → Security → Encryption & credentials → Install a certificate → CA certificate
   (Chrome honours user CAs; menu names vary by vendor). Managed devices: deploy the CA through MDM instead.
3. Connect to the corporate Wi-Fi in the trusted subnet (not a guest network), open `https://saplens2.corp.example:18791/`: the browser must
   show a valid lock without warnings. Never accept a certificate warning: it means the trust setup is wrong.
4. Sign in with the token, check the status line shows "server", run a Role Lookup, rotate the device (layout is responsive), sign out by
   closing the browser or after 8 h.
5. Remove the CA profile from test devices afterwards.

## 9. Secure shutdown and restart

```powershell
Stop-Service SapLens2      # graceful: running import handed back (Queued), SQLite closed; Start-Service / Restart-Service SapLens2
Get-Content 'C:\ProgramData\SapLens2\data\logs\server-*.log' -Tail 5
```

Windows service operation (pending native verification [U]):

```powershell
Get-Service SapLens2 | Format-List Name, Status, StartType
Get-CimInstance Win32_Service -Filter "Name='SapLens2'" | Format-List State, StartName, PathName, ProcessId   # identity and command line
Restart-Service SapLens2
# Service Control Manager: start/stop (7036), failures to start (7000, 7009), unexpected exits and recovery (7031, 7034)
Get-WinEvent -FilterHashtable @{ LogName = 'System'; ProviderName = 'Service Control Manager'; StartTime = (Get-Date).AddHours(-1) } |
  Where-Object Message -like '*SAP Lens 2*' | Format-Table TimeCreated, Id, Message -Wrap
# Application log: the Windows service host can write warnings and errors under the source of the executable; not observed yet [U].
Get-WinEvent -FilterHashtable @{ LogName = 'Application'; StartTime = (Get-Date).AddHours(-1) } | Where-Object ProviderName -like 'SapLens*'
```

The authoritative application log is `<data-dir>\logs\server-YYYYMMDD.log`; a refused startup writes `startup refused: <reason>` to stderr,
which a service does not show, so reproduce a start failure by running the same command line in a console as the service account would.

Safe removal (keeps data, certificates and the firewall rule unless removed explicitly):

```powershell
Stop-Service SapLens2
sc.exe delete SapLens2                                        # removes the registration only
Remove-NetFirewallRule -DisplayName 'SAP Lens 2 HTTPS (trusted LAN)' -ErrorAction SilentlyContinue
# Data (C:\ProgramData\SapLens2\data) and TLS files stay; back them up or delete them deliberately.
```

```bash
sudo systemctl stop saplens2      # SIGTERM, graceful within TimeoutStopSec; start / restart likewise
journalctl -u saplens2 -n 20 --no-pager
```

After a restart all browser sessions are gone (sign in again); data and decisions persist in SQLite. Token rotation: stop, replace
`api-token` (or `SAP_LENS_V2_TOKEN`), start. Certificate renewal: replace the files, restart; the startup log shows the new expiry.

## 10. Acceptance checklist (another device required)

| # | Check | Status |
| --- | --- | --- |
| 1 | Service starts with `--network`; log shows the LAN address, `https`, allowed hosts, certificate expiry | Pending |
| 2 | Only the configured address listens on the port | Pending |
| 3 | Desktop browser on another machine: valid lock, sign-in, Role Lookup, import | Pending |
| 4 | iOS and Android browser: valid lock after CA install, sign-in, lookup | Pending |
| 5 | `/api` without token 401; foreign Host 421; plain HTTP gives no page | Pending |
| 6 | Device outside the trusted subnet cannot connect | Pending |
| 7 | Stop/start: data persists, sessions require sign-in again | Pending |
| 8 | Windows service and Linux systemd variants both pass 1 to 7 | Pending |

## 11. Reverse proxy (Pangolin, Cloudflare)

Status: implemented and tested on Linux through the real Kestrel and TLS pipeline (`ReverseProxyTests`, `OriginPolicyTests`) [T]. A live
Pangolin deployment has **not** been verified [U].

### Public and internal origin

A browser that opens `https://lens.example` (the **public origin**) sends `Origin: https://lens.example` on every state change. The proxy then
opens its own connection to the **internal endpoint**, for example `https://192.168.10.20:18795`, and the Host it sends there may be the public
name, the public name with the internal port (`lens.example:18795`), or the internal address. The Server accepts a state-changing request only
when its Origin equals the request's effective `scheme://host:port`, so the public origin must be **established** on the Server, never guessed:

| Request arrives from | Effective scheme and host | Forwarded headers |
| --- | --- | --- |
| Any peer, no `--trusted-proxies` (default) | The TLS connection's scheme and the Host header | Ignored |
| A peer outside `--trusted-proxies` | Same | Ignored (logged as present, not applied) |
| A peer inside `--trusted-proxies` | `X-Forwarded-Proto` and `X-Forwarded-Host` (rightmost value per trusted hop), client address from `X-Forwarded-For` | Applied by ASP.NET Core `ForwardedHeadersMiddleware` before the request boundary |

Rules for trusted proxies:

- Only addresses or networks you list are trusted: single addresses, or networks no wider than /24 (IPv4) or /64 (IPv6). Loopback,
  unspecified and multicast are refused; private ranges, Docker networks and Cloudflare are never trusted implicitly. Requires `--network`.
- `X-Forwarded-Host` is applied only if its host is one of `--allowed-hosts` (exact; the port may differ, it is then part of the origin, for
  example `lens.example:8443`). Otherwise the request is judged on its own Host.
- `X-Forwarded-Proto` must end up `https`: a proxy reporting a plain-HTTP client gets `403 HTTPS is required.`, so cookies never lose
  `Secure`/`__Host-`.
- Hops (`--trusted-proxy-hops`, default 1): the middleware walks back through `X-Forwarded-For` at most that many entries and only while each
  hop is itself a trusted proxy; client-supplied entries further left are never used. Raise it only for a chain of proxies you control and list.
- The RFC 7239 `Forwarded` header is not processed. Cloudflare headers (`CF-Connecting-IP`, `CF-Visitor`) are not used.
- Host allowlisting (421), Origin and CSRF checks, Accounts sessions and CSRF tokens, HTTPS-only transport, secure cookies, security headers
  and correlation ids are unchanged; they operate on the effective values.
- Sign-in throttling uses the effective client address: with one trusted hop behind Cloudflare that is normally the Cloudflare edge address
  Pangolin connected from, so the per-client limit is shared by users of that edge; the global limit still applies.

### Example configuration

Public origin `https://lens.example.com`, backend `https://192.168.10.20:18795`, certificate SAN `lens.example.com` and `192.168.10.20`.
`<PANGOLIN_PEER_IP>` is a placeholder for the address the backend actually sees as the TCP peer of Pangolin's connections. It is not
necessarily the Pangolin server's public address, a Cloudflare address, the gateway or the VM's own address. With a Newt site connector it is
normally the LAN address of the machine running Newt (the VM's own address if Newt runs on the VM). Determine it as shown below before
configuring it.

```powershell
& .\SapLens.Api.exe --data-dir C:\saplens2\runtime-test --network --listen 192.168.10.20 --port 18795 `
  --allowed-hosts lens.example.com,192.168.10.20 --cert C:\ProgramData\SapLens2\tls\server.pfx `
  --cert-password-file C:\ProgramData\SapLens2\tls\cert-password --trusted-proxies <PANGOLIN_PEER_IP>
```

With the test launcher: `.\scripts\start-server-test.ps1 -AllowedHosts 'lens.example.com','192.168.10.20' -TrustedProxies '<PANGOLIN_PEER_IP>'`.

Finding the peer address and what the proxy sends (before trusting anything): start without `--trusted-proxies`, sign in through
`https://lens.example.com`, and read the warning the refusal logs:

```text
Request refused (403 Cross-origin request refused.): POST /api/auth/login; peer 192.168.10.30 trusted proxy False; client 192.168.10.30;
forwarded headers present True applied False; raw https://lens.example.com:18795; effective https://lens.example.com:18795;
origin https://lens.example.com:443 comparison PortMismatch
```

`peer` is the address to trust, `raw` is the Host Pangolin sends upstream, `forwarded headers present True` shows Pangolin sends `X-Forwarded-*`.
On the VM, `Get-NetTCPConnection -LocalPort 18795 -State Established | Select-Object RemoteAddress` shows the same peers while connections are open.

### Pangolin settings

Pangolin is built on Traefik; field names differ between versions, so check them against your Pangolin version.

| Setting | Required value |
| --- | --- |
| Resource domain | `lens.example.com` (HTTP resource, TLS at Pangolin) |
| Target | method `https`, address `192.168.10.20`, port `18795` |
| Upstream TLS | verify the backend certificate: add the private CA (`saplens2-ca.cer`) to the trust store Traefik uses for upstream connections, and use a server name (SNI) that the SAN covers (`lens.example.com` or `192.168.10.20`). Skipping verification is acceptable only for a short diagnostic run, never as the configuration |
| Host header | leave Traefik's default (pass the client's Host) or set a custom Host of `lens.example.com`; either works once the proxy is trusted, because `X-Forwarded-Host` carries the public host |
| Forwarded headers | keep `X-Forwarded-Proto`, `X-Forwarded-Host` and `X-Forwarded-For` (Traefik sets them by default); do not strip them |
| Pangolin authentication | optional. With Pangolin's resource authentication on, unauthenticated requests get Pangolin's own (plain-text) 401 before reaching SAP Lens; SAP Lens accounts still apply after it |

Cloudflare: use SSL mode "Full (strict)" so Cloudflare to Pangolin is verified HTTPS. SAP Lens does not trust Cloudflare directly.

### Troubleshooting 403 and 421

| Response (title) | Meaning | Check |
| --- | --- | --- |
| `421 Unexpected host.` | The effective Host is not loopback and not in `--allowed-hosts` | Add the public name to `--allowed-hosts` (and to the certificate SAN); check `raw`/`effective` in the log |
| `403 Cross-origin request refused.` with `trusted proxy False` | Forwarded headers ignored: the peer is not trusted | Add the logged `peer` to `--trusted-proxies` |
| `403 Cross-origin request refused.` with `trusted proxy True`, `applied False` | Proxy trusted, but no allowed `X-Forwarded-Host` | Make Pangolin send `X-Forwarded-Host: lens.example.com`; check the name is in `--allowed-hosts` |
| `403 Cross-origin request refused.` with `comparison PortMismatch` | Host and Origin differ by port (for example `:18795` against the public 443) | Same as above: the public host must come from the trusted proxy |
| `403 HTTPS is required.` | A trusted proxy reported `X-Forwarded-Proto: http` | Serve the resource over HTTPS only |
| `403 State-changing requests need a same-origin signal.` | No Origin and no `Sec-Fetch-Site: same-origin` on a state change | Expected for non-browser clients; use the access-token header |
| Plain-text 401 not in JSON | Pangolin's authentication layer, not SAP Lens | Sign in to Pangolin first or disable its resource authentication |

A 401 from `/api/auth/login` with an error `code` means the request passed the boundary and the credentials were wrong; it is not a
successful sign-in. A successful sign-in returns 200 with the account and sets `sap-lens-session` (Secure, HttpOnly, SameSite=Strict).

### Verification (Windows PowerShell, after configuring the trusted proxy)

```powershell
$body = Join-Path $env:TEMP 'saplens-login.json'
Set-Content -Path $body -Value '{"username":"nobody","password":"wrong-password"}' -Encoding ASCII -NoNewline   # synthetic, not an account
# Direct LAN access still works (boundary passes; JSON 401 with a code = wrong credentials, as intended)
curl.exe -s -w "`n%{http_code}`n" -X POST https://192.168.10.20:18795/api/auth/login -H "Origin: https://192.168.10.20:18795" -H "Content-Type: application/json" --data "@$body"
# Spoofed forwarding from a machine that is not the trusted proxy is ignored: 403 Cross-origin
curl.exe -s -w "`n%{http_code}`n" -X POST https://192.168.10.20:18795/api/auth/login -H "Origin: https://lens.example.com" -H "X-Forwarded-Host: lens.example.com" `
  -H "X-Forwarded-Proto: https" -H "Content-Type: application/json" --data "@$body"
# Through Pangolin (add Pangolin's own sign-in first if its resource authentication is on)
curl.exe -s -w "`n%{http_code}`n" -X POST https://lens.example.com/api/auth/login -H "Origin: https://lens.example.com" -H "Content-Type: application/json" --data "@$body"   # JSON 401 with a code, not 403
curl.exe -s -w "`n%{http_code}`n" -X POST https://lens.example.com/api/auth/login -H "Origin: https://evil.example" -H "Content-Type: application/json" --data "@$body"  # 403
Remove-Item $body
```

Then sign in with a real account in a browser at `https://lens.example.com/` and confirm in the server log that no `Request refused` line appears.
