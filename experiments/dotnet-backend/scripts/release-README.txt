SAP Lens 2 (.NET experiment) {{VERSION}}, commit {{SHA}}, built {{BUILT}} UTC, {{PLATFORM}}.
Development and acceptance testing only; not a production release.

WHICH EXECUTABLE
  desktop\SapLens2Prototype.exe  One user on this PC. Double-click; needs the Microsoft Edge WebView2 Runtime. Data and logs go to
                                 %LOCALAPPDATA%\SAP Lens 2 Prototype. It extracts its native libraries to a temporary folder at start.
  server\SapLens.Api.exe         Browser access from this PC or the LAN. Keep e_sqlite3.dll and libSkiaSharp.dll next to it. Console or Windows service.
  No .NET installation is needed. Requires Windows 10 1903 / Windows Server 2019 or later (system ICU for Unicode text).
  symbols\ holds debugging symbols only.

SERVER QUICK START
  server\SapLens.Api.exe --help        all options and environment variables
  server\SapLens.Api.exe --version
  server\SapLens.Api.exe --data-dir C:\saplens2\data
      Loopback only: http://127.0.0.1:18790/ on this PC.
  LAN (HTTPS required; all values are examples):
  server\SapLens.Api.exe --data-dir C:\saplens2\data --network --listen 192.168.10.20 --port 18795 --allowed-hosts 192.168.10.20
      --cert C:\ProgramData\SapLens2\tls\server.pfx --cert-password-file C:\ProgramData\SapLens2\tls\cert-password
  Behind a reverse proxy, add --trusted-proxies <the proxy's address as seen by this server>.
  First administrator: issue a one-time code with SapLens.Cli accounts-code --data <data-dir> (from the source checkout).

KEEP OUTSIDE THIS FOLDER
  The data directory (database, access token, accounts, logs), certificates and password files. The Server refuses a data directory inside its
  application folder. Replacing this release folder with a newer one never touches data.

VERIFY
  build-manifest.json lists the size and SHA-256 of every file; SHA256SUMS covers all files. Check with scripts\verify-release.ps1 -ReleasePath <this folder>.

DOCUMENTATION (repository)
  docs/experiments/dotnet-backend/WINDOWS_TEST_VM.md, SERVER_NETWORK_ACCESS.md (configuration reference, reverse proxy, Windows service).
