# Production React UI on the .NET server (Phase 1)

The AuthLens UI from `origin/work` (`frontend/`, unchanged) is built with its own npm scripts and served by the ASP.NET Core host on Desktop
and Server. The earlier simplified prototype UI was removed. Status tags as in [README](../migration/README.md).

## How it works

- **Build**: `AuthLens.Api.csproj` embeds `frontend/dist/**` under `wwwroot/` (`ManifestEmbeddedFileProvider`). When `frontend/dist/index.html`
  is missing, or with `-p:BuildFrontend=true`, the build runs `npm ci` and `npm run build` first. Node.js 24 or 25 is a build-time requirement
  only; no Node.js, Python or loose UI files ship. Releases remove `frontend/dist` and let this target rebuild it once; the publishes reuse it
  ([build and publish flow](../development/README.md#build-and-publish-flow)).
- **Embedding** (the cause of the Windows release failures, "The user interface is incomplete in this build"):
  - Every UI file (`frontend/dist/**` and the sign-in page in `wwwroot/`) is a manifest resource with the explicit name
    `AuthLensUi/<relative path>`; `EmbeddedUiFileProvider` (`UiAssets.cs`) serves them, normalizes `\` to `/` (MSBuild's `RecursiveDir` uses
    the build machine's separator) and refuses `..`, empty and drive segments.
  - The embedded-files manifest (`GenerateEmbeddedFilesManifest`, `ManifestEmbeddedFileProvider`) is no longer used. It splits paths on the
    build machine's separator only, so a `wwwroot/...` path became a flat root entry on Windows, and its regeneration check ignores changes
    other than the file list, so an existing `obj` folder could keep a broken manifest after the fix.
  - The list of embedded UI names is a compile input (`obj/.../AuthLensUi.files`); adding or removing a UI file always rebuilds the assembly.
  - Guards: `BuildIntegrationTests` (resource names and layout of the built assembly; Windows-style names; path traversal; a clean build and two
    incremental builds with a replaced and a removed asset, checked by loading the built assembly) and both release scripts (`AuthLensUi/index.html`
    and `AuthLensUi/assets` in every published binary).
- **Serving**: `/` serves the React `index.html`; assets, icons and `theme.js` are served without credentials (they contain no data). The
  Content Security Policy is v1's policy for this UI (`script-src 'self'`, inline styles allowed as React needs them, no framing).
- **Authentication** (unchanged rules):
  - Desktop: the WebView2 shell adds the per-run token to `/api` requests outside page script. The React client's own `X-SAP-Lens` header
    carries no authority.
  - Server (Accounts mode, the default): the React app loads, `/api/auth/state` reports `local-sessions`, and the React sign-in page handles
    activation (code from `AuthLens.Cli accounts-code`), sign-in, password reset and recovery against the v1 account API. Roles hide and
    refuse what the account may not do. See [SERVER_NETWORK_ACCESS.md](../deployment/SERVER_NETWORK_ACCESS.md#accounts-mode-default).
  - Server with `--auth shared-token`: a browser without a session is redirected to `/login.html` and signs in with the access token.
  - Host allow-list, origin/CSRF checks, TLS and the private-LAN policy apply to every request, including the v1 routes.
- **API adapter**: a server-side compatibility layer (`V1Compatibility.cs`) serves the v1 routes the UI calls, in the v1 response shapes, from
  the C# domain. The UI code is not changed and no backend-specific logic is added to it. Every route not migrated answers
  `501` with `{"code":"not_migrated","detail":"This AuthLens function is not available in the .NET server yet (...). No data was changed."}`;
  the UI shows that text where the function is used. `X-Data-Revision` follows v1's `boot.publication.directory` format.

## Served now

| Route | Source |
| --- | --- |
| `GET /api/auth/state` | Host mode: `desktop`, `local-sessions` (Server, Accounts mode, with `setup_required`) or `shared-token` |
| `GET /api/configuration`, `/api/presentation` | v1 default settings (read-only), exported from Python v1 by `tools/export_v1_reference.py`, plus a notice explaining the .NET state |
| `GET /api/registry/modules` | v1 SAP area registry (49 areas, icons, colours), exported from Python v1 |
| `GET /api/version`, `/api/application-info`, `/api/runtime` | .NET host |
| `GET /api/modules`, `/api/roles`, `/api/roles/{agr_name}` | C# catalogue and Role Lookup (equivalence-tested against v1) |
| `POST /api/configuration`, `/api/configuration/theme` | Settings document in SQLite with optimistic revision (409 on conflict), strict validation; source paths only through imports |
| `POST /api/server/uploads/{source}/activate`, `/api/data-sources/{source}/select` | Phase 2A import workflow for roles, users and SoD: staged import, profiles, held-import confirmation, refresh report; Server accepts uploads only |
| `GET /api/data-sources/history`, `/api/data-sources/{source}/preview`, `POST /api/data/cancel` | Import history (refresh reports), active-source preview, cancel the running import |
| `GET /api/access/users`, `/api/access/users/{username}` | Phase 2B User Access list and user detail from the C# domain; unmigrated filters answer 501 |
| `GET /api/user-comparison`, `/api/user-comparison/evidence` | Phase 2B Compare Users with summary, areas and evidence |
| `GET /api/data-health` | Data Health findings (equal to Python v1 on the synthetic set), coverage, sources, review continuity |

Data is loaded through the UI (Settings → Data Sources: upload, or a local path on the Desktop), or through the .NET import API. See [FEATURE_PARITY.md](../migration/FEATURE_PARITY.md) for everything else.

## Evidence (Linux) [M][T]

- 96 automated tests pass, including contract tests for every served v1 route, 501 handling for not-migrated routes (GET and POST),
  authentication of v1 routes, the sign-in redirect, the React entry point and every asset it references, and publish tests showing the
  React build inside the Server DLL and the Desktop single-file exe.
- Browser check in Chromium (the WebView2 engine) against the server: sign-in page, sign-in, the React shell (header, navigation, sidebar,
  theme) and the configuration notice render; Role Lookup lists the 227 imported synthetic roles with SAP area badges, counts and filters.
  The only failed API calls were the not-migrated `dashboard`, `data-health`, `diagnostics`, `data-sources/history` and `saved-filters`
  (each 501, handled by the UI).
- The frontend's own unit tests (41) still pass; the frontend sources are unchanged.
- One intermittent failure was observed twice in the published-server test before an unrelated change and not again in 7 later runs; the probe
  message now includes the start of the served page so a recurrence is diagnosable. Cause unknown [U].

Not verified: anything on Windows, the Desktop window with the React UI, mobile browsers [U].

## Windows VM: fetch, build, test, publish, validate (CMD)

Prerequisites: Git, .NET 10 SDK, Node.js 24 or 25 (`node --version`; the frontend refuses 26). The running lab deployment is not touched:
the new package runs side by side with its own data directory and port.

> Historical milestone commands (folder layout `server-win-x64`/`desktop-win-x64`). Current builds create a versioned folder with `server\` and
> `desktop\`: see [WINDOWS_TEST_VM.md](../deployment/WINDOWS_TEST_VM.md#1-build-a-native-release).

```bat
cd /d C:\src\sap-lens && git fetch origin && git checkout experiment/dotnet-backend && git pull --ff-only
cd /d C:\src\sap-lens\backend
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build-release.ps1 -Output C:\AuthLens-Test\release-next
```

At that milestone the script ran `npm ci`, `npm run build`, `dotnet build`, `dotnet test` (add `-SkipPublishTests` to skip the slow publish
tests) and published `C:\AuthLens-Test\release-next\server-win-x64` and `C:\AuthLens-Test\release-next\desktop-win-x64`. Today the UI is built by the
.NET build itself ([build and publish flow](../development/README.md#build-and-publish-flow)). The same steps one by one:

```bat
cd /d C:\src\sap-lens\backend && dotnet build AuthLens.slnx -c Release -p:BuildFrontend=true
dotnet test tests\AuthLens.Tests -c Release --no-build
dotnet publish src\AuthLens.Api -c Release -r win-x64 --self-contained true -o C:\AuthLens-Test\release-next\server-win-x64
dotnet publish src\AuthLens.Desktop -c Release -o C:\AuthLens-Test\release-next\desktop-win-x64
```

Validate the new server package side by side over HTTPS (replace the certificate paths with the lab's; port 18795 is free for this test and
needs no firewall change when tested from the VM itself):

```bat
start "AuthLens validation" C:\AuthLens-Test\release-next\server-win-x64\AuthLens.Api.exe --data-dir C:\AuthLens-Test\validation-data --network --listen 192.168.10.20 --port 18795 --allowed-hosts 192.168.10.20 --cert <path-to-server.pfx> --cert-password-file <path-to-cert-password>
curl.exe -s -o NUL -w "sign-in page %{http_code}\n" https://192.168.10.20:18795/login.html
curl.exe -s -o NUL -w "app without session %{http_code} (302 expected)\n" https://192.168.10.20:18795/
curl.exe -s -o NUL -w "api without token %{http_code} (401 expected)\n" https://192.168.10.20:18795/api/roles
set /p TOKEN=<C:\AuthLens-Test\validation-data\api-token
curl.exe -s -H "X-SAP-Lens-Token: %TOKEN%" https://192.168.10.20:18795/api/version
curl.exe -s -o NUL -w "not migrated %{http_code} (501 expected)\n" -H "X-SAP-Lens-Token: %TOKEN%" https://192.168.10.20:18795/api/dashboard
curl.exe -s -X POST -H "X-SAP-Lens-Token: %TOKEN%" -H "Content-Type: text/csv" --data-binary @%TEMP%\sap-lens-csv\roles.csv https://192.168.10.20:18795/api/v1/imports/roles
set TOKEN=
```

The synthetic `roles.csv` comes from the PowerShell snippet in
[DESKTOP_SERVER_DEPLOYMENT.md](../deployment/DESKTOP_SERVER_DEPLOYMENT.md#b-interactive-desktop-session-powershell-51-or-7-window-webview2-import-shutdown). Then
open `https://192.168.10.20:18795/` in a browser on the VM (and, with a temporary firewall rule for port 18795 restricted to the trusted subnet,
from another device): expected are the sign-in page, then the AuthLens UI with the .NET notice, and Role Lookup listing the imported roles.
Stop the validation server by closing its window. Only after this passes, replace the running lab service's binaries
(`Stop-Service AuthLens`, copy `server-win-x64`, `Start-Service AuthLens`; see [SERVER_NETWORK_ACCESS.md](../deployment/SERVER_NETWORK_ACCESS.md#9-secure-shutdown-and-restart)).

Desktop: `C:\AuthLens-Test\release-next\desktop-win-x64\AuthLens.exe --self-check` (exit code 0), then start it normally; the window shows
the same React UI without a sign-in.

## Limitations of this milestone

- Only boot and Role Lookup are served; most screens show the not-migrated message (see the parity matrix).
- Settings are read-only defaults; the UI's Settings pages render but saving answers 501.
- Data can only be loaded through the `/api/v1` import API, not through the UI's Data Sources page.
- v1 local accounts, roles and the React account sign-in are not migrated; Server sign-in is the shared access token.
- Not verified on Windows or from another device.
