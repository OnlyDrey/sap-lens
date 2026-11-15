# Desktop and Server: builds, run commands and packaging assessment

Nothing here changes the production Desktop launcher, installers, services, workflows or release artifacts. All output goes to isolated
directories outside the repository (`artifacts/`, `bin/`, `obj/`, `out/` are ignored in `experiments/dotnet-backend/.gitignore`).

## Status

| Target | Built | Ran | Evidence |
| --- | --- | --- | --- |
| Server, linux-x64, self-contained | Yes | Yes: health, readiness, imports, all endpoints, 15-client load, graceful and crash shutdown | [M], [T] |
| Server, win-x64, self-contained | Yes (cross-compiled on Linux) | **No** | [U] |
| Desktop, win-x64, self-contained single file (WinForms + WebView2) | Yes (cross-compiled on Linux) | **No** | [U] |

## Server

```bash
cd experiments/dotnet-backend
dotnet publish src/SapLens.Api -c Release -r linux-x64 --self-contained true -o <out>/server-linux-x64   # or -r win-x64
# run (no .NET or Python needed on the host)
SAP_LENS_V2_TOKEN=<at least 32 chars> <out>/server-linux-x64/SapLens.Api --data-dir /var/lib/saplens-v2 --port 18790 \
  [--frontend /path/to/frontend/dist] [--no-worker]
```

- **Data directory**: `--data-dir` or `SAP_LENS_V2_DATA_DIR`; must be absolute and local (UNC, `//host/share` and network drives refused).
- **Token**: `SAP_LENS_V2_TOKEN`, otherwise generated once into `<data>/api-token` (mode 0600 on Linux; on Windows it inherits the data
  directory ACL, which an installer must restrict to the service account [U]). Every `/api` request needs `X-SAP-Lens-Token`.
- **Binding**: `127.0.0.1` only. Any non-loopback URL is refused at startup, with or without a token, because the prototype has no TLS and
  no identity provider. Remote access is a deliberate blocker, not a configuration option.
- **Health**: `/health/live` (process up), `/health/ready` (database initialized, migrated, integrity-checked); `503` with the reason
  otherwise. **OpenAPI**: `/openapi/v1.json`.
- **Logging**: JSON lines on stdout with UTC timestamps, scopes (correlation id, job id, attempt). systemd/journald or the Windows service
  wrapper captures them. A rolling file sink is not implemented.
- **Shutdown**: SIGTERM / service stop. Measured 164 ms with data loaded; a running import is handed back (status Queued, attempt not
  counted, staging discarded) and resumes on the next start [M]. After a crash (SIGKILL) the job is recovered when its 30 s lease expires,
  staging is discarded and the import completes exactly once (35.7 s after restart in the test) [M].
- **Service wrappers** (not built): Linux systemd unit with `Type=notify` via `Microsoft.Extensions.Hosting.Systemd`; Windows service via
  `Microsoft.Extensions.Hosting.WindowsServices` (`UseWindowsService`), which removes the need for WinSW. Both are first-party packages.

## Desktop

```bash
dotnet publish src/SapLens.Desktop -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true \
  -p:IncludeNativeLibrariesForSelfExtract=true -o <out>/desktop-win-x64
cp -r ../../frontend/dist <out>/desktop-win-x64/frontend
```

Lifecycle as implemented (`Program.cs`, `MainWindow.cs`) [C]:

1. Single instance per Windows session (named mutex).
2. Private data directory `%LOCALAPPDATA%\SAP Lens 2 Prototype\data`, separate from v1.
3. Core starts in-process on `127.0.0.1:0`; a fresh 256-bit token per run.
4. Window is created only after the database is ready; otherwise a message with the reason and a non-zero exit code.
5. WebView2 profile in `%LOCALAPPDATA%\SAP Lens 2 Prototype\webview2`; DevTools and default context menus off; navigation confined to the
   loopback origin; new windows blocked.
6. The token is added to `/api` requests in `WebResourceRequested` by the host. Page script never sees it, which also removes the v1
   finding F1 (capability passed through the first page load).
7. Closing the window stops the host gracefully (job handed back, connections closed).

Prerequisites: Microsoft Edge WebView2 Runtime (present on supported Windows 10/11; missing runtime shows a message). No Python and no
system-wide .NET.

## Packaging assessment

| Criterion | Windows Desktop | Windows Server | Linux Server |
| --- | --- | --- | --- |
| Build complexity | One `dotnet publish`; cross-compiles from Linux. Low. | Same. Low. | Same. Low. |
| Runtime dependencies | WebView2 Runtime only | None | glibc, ICU optional (`InvariantGlobalization` on) |
| Size | 154 MB single exe + 7 MB frontend | 115 MB, 356 files | 114 MB, 353 files |
| Startup reliability | Not measured on Windows [U]. Single-file extracts native libraries to a temp folder on first run unless `IncludeNativeLibrariesForSelfExtract` is avoided; a one-dir layout avoids extraction entirely | Not measured [U] | Cold start to ready 1.3 to 1.8 s, warm 1.2 to 1.4 s [M] |
| Install / upgrade | Copy or MSIX/MSI (not built); data directory and schema migrations are independent of the binary, with a protected migration backup | Same; service registration via `UseWindowsService` + `sc.exe`/installer | Package + systemd unit |
| Logging | Console not visible in a WinExe; needs a file sink | Event Log or file sink | journald via stdout |
| AV / App Control | **Unsigned binaries face the same App Control enforcement v1 and the Go experiment hit.** .NET does not change this. Signing all shipped PE files and an IT publisher rule remain mandatory. Single-file reduces the number of PE files to sign but self-extraction of native libraries can trigger AV heuristics; one-dir is the safer default under App Control | Same | n/a |
| Signing | One exe (single-file) or every PE (one-dir) with Authenticode | Every PE | Optional (package signing) |
| Runtime lifecycle | Self-contained: the runtime is patched only by shipping a new build. .NET 10 LTS support ends November 2028; plan monthly servicing rebuilds | Same | Same |

## Native AOT (evaluation only, not built)

Not viable for this design today: EF Core does not support AOT for runtime model building and migrations, reflection-based
System.Text.Json would need source generators for every contract, and WinForms is not AOT-compatible. Expected benefit is smaller size and
faster cold start (the current cold start is already about 1.3 s). Revisit only for the Server if size or start time become requirements;
it would mean Dapper or hand-written SQL instead of EF Core.

## What has to happen on Windows before any GO

1. Run the Server package as a Windows service (start, stop, restart, crash recovery, reboot), with the data directory ACL.
2. Run the Desktop exe on a managed machine: WebView2 present/missing, first run, single instance, close during an import, App Control
   with a signed build.
3. Measure startup, memory and shutdown on Windows with the same harness.
