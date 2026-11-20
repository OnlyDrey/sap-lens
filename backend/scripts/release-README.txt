AuthLens (.NET) {{VERSION}}, commit {{SHA}}, built {{BUILT}} UTC, {{PLATFORM}}.
Development and acceptance testing only; not a production release.

WHICH EXECUTABLE
  desktop\AuthLens.exe            One user on this PC. Double-click; needs the Microsoft Edge WebView2 Runtime. Data and logs go to
                                 %LOCALAPPDATA%\AuthLens. Folders of SAP Lens (v1, Desktop, prototype) are never used or changed;
                                 bring their data over by restoring a backup. It extracts its native libraries to a temporary folder at start.
  server\AuthLens.Api.exe         Browser access from this PC or the LAN. Keep e_sqlite3.dll and libSkiaSharp.dll next to it. Console or Windows service.
  No .NET installation is needed. Requires Windows 10 1903 / Windows Server 2019 or later (system ICU for Unicode text).
  symbols\ holds debugging symbols only.

SERVER QUICK START
  server\AuthLens.Api.exe --help        all options and environment variables
  server\AuthLens.Api.exe --version
  server\AuthLens.Api.exe --data-dir C:\ProgramData\AuthLens\data
      Loopback only: http://127.0.0.1:18790/ on this PC.
  LAN (HTTPS required; all values are examples):
  server\AuthLens.Api.exe --data-dir C:\ProgramData\AuthLens\data --network --listen 192.0.2.10 --port 18795 --allowed-hosts lens.example.com,192.0.2.10
      --cert C:\ProgramData\AuthLens\tls\server.pfx --cert-password-file C:\ProgramData\AuthLens\tls\cert-password
  Behind a reverse proxy, add --trusted-proxies <the proxy's address as seen by this server>.
  Local administration (no SDK): open an elevated PowerShell and run .\Service-Manager.ps1 -DataDirectory <data-dir>.
  It shows key status, creates the initial key, exports/verifies a recovery copy, and issues administrator activation/recovery codes.
  Recovery exports are new private files; an existing key is never rotated. Keep copies off the server and verify them in Settings.
  Activation and recovery codes are displayed locally once. Do not record or redirect code operations to logs.

KEEP OUTSIDE THIS FOLDER
  The data directory (database, access token, accounts, logs), certificates and password files. The Server refuses a data directory inside its
  application folder. Replacing this release folder with a newer one never touches data.

VERIFY
  build-manifest.json lists the size and SHA-256 of every file; SHA256SUMS covers all files. Check with scripts\verify-release.ps1 -ReleasePath <this folder>.

DOCUMENTATION (repository)
  docs/deployment/WINDOWS_TEST_VM.md, SERVER_NETWORK_ACCESS.md (configuration reference, reverse proxy, Windows service).
