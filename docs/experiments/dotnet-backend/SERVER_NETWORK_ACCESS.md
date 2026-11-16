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

## 2. Configuration

| Setting | Option | Environment variable | Default |
| --- | --- | --- | --- |
| Data directory (absolute, local) | `--data-dir` | `SAP_LENS_V2_DATA_DIR` | required |
| Listen address (IP literal) | `--listen` | `SAP_LENS_V2_LISTEN` | `127.0.0.1` |
| Port (HTTPS when a certificate is set) | `--port` | `SAP_LENS_V2_PORT` | `18790` |
| Network access enabled | `--network` | `SAP_LENS_V2_NETWORK=true` | disabled |
| Host names / addresses clients use | `--allowed-hosts a,b` | `SAP_LENS_V2_ALLOWED_HOSTS` | none |
| Certificate (`.pfx`/`.p12`, or PEM) | `--cert` | `SAP_LENS_V2_CERT` | none |
| PEM private key | `--cert-key` | `SAP_LENS_V2_CERT_KEY` | none |
| Certificate password | `--cert-password-file` (preferred) | `SAP_LENS_V2_CERT_PASSWORD_FILE`, or `SAP_LENS_V2_CERT_PASSWORD` | none |
| Access token | (never an option) | `SAP_LENS_V2_TOKEN` | generated once into `<data-dir>/api-token` |
| Browser authentication | `--auth accounts\|shared-token` | `SAP_LENS_V2_AUTH` | `accounts` |
| Name recorded for API clients that use the access token | | `SAP_LENS_V2_PRINCIPAL` | `server-operator` |
| Background worker off | `--no-worker` | | on |

Nothing secret is stored in committed files. The startup log states the address, port, scheme, network mode, allowed hosts and the
certificate subject, thumbprint and expiry, never a password or token.

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
| Roles | `administrator`, `reviewer`, `viewer`, enforced per route by the v1 permission map (deny by default; unknown writes are refused for everyone). Viewers read and export; reviewers additionally record review decisions; administrators manage settings, data sources, saved filters and accounts. The Access Package preview and export are open to every signed-in role (v1 maps them to no permission at all, which refuses them for everyone in session mode; they never change data) |
| Brute force | Per client digest: the fifth failure locks for 30 s, each further failure doubles the lock up to 15 min; separate counters for password-reset codes |
| Audit | Account, role, password, session and policy events in the store's `audit` table with the actor's public identity; never verifiers, tokens or codes. Unauthenticated denial events are capped at the newest 10 000 |
| Transport | Plain HTTP only from a loopback peer; on the network the server is HTTPS-only (`secure_transport_required`) |
| Attribution | Every write (imports, confirmations, settings, saved filters, review decisions) records the signed-in username |
| API clients | The protected access token (`X-SAP-Lens-Token`) still authenticates automation as the operator principal (`SAP_LENS_V2_PRINCIPAL`, provenance `access-token`). It cannot administer accounts, because account operations need a real session |

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
| Authorization | **None beyond authentication**: everyone signed in can import, confirm held imports, record decisions and create backups |

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
