# Development and testing (AuthLens .NET)

How to build and test AuthLens. Deployment: [deployment](../deployment/README.md). Architecture: [architecture](../architecture/README.md).
SAP Lens 1 (Python) is archived outside the repository; its historical development guide is in [legacy v1 development](../legacy/v1/development/README.md).

## Everyday commands

```bash
# .NET backend (from the repository root)
cd backend && dotnet build AuthLens.slnx -c Release
dotnet test tests/AuthLens.Tests -c Release --no-build --filter "FullyQualifiedName~V1DataMigrationTests"   # affected classes first
dotnet test tests/AuthLens.Tests -c Release --no-build                                                       # whole suite at checkpoints

# Frontend (from frontend/)
npm ci && npm run check:types && npm run lint && npm run test:unit && npm run build

# Deployment and release scripts (from backend/)
pwsh -NoProfile -Command "Invoke-Pester scripts/tests"        # Pester: deployment state machine, migration, NTFS policy, release verification, test launcher
bash scripts/tests/deploy-windows.test.sh                     # SSH orchestrator with a fake ssh (end to end through pwsh)

# Repository checks (from the repository root)
python scripts/check-docs.py && python scripts/check-secrets.py && git diff --check
```

Run the smallest relevant selection while developing and the whole suite at checkpoints (AGENTS.md, progressive validation). The .NET build
embeds `frontend/dist` as it is; it builds the frontend itself only when `dist` is missing or with `-p:BuildFrontend=true`. After a frontend change,
run `npm run build` (or pass `-p:BuildFrontend=true`), or the server keeps serving the previously built UI. Releases always rebuild it
([build and publish flow](#build-and-publish-flow)).

Windows deployment tests support Windows PowerShell 5.1 with Pester 5; child scripts use that edition's executable under `$PSHOME`, without
requiring `pwsh` on PATH. See [Windows script validation](../deployment/WINDOWS_DEPLOYMENT.md#windows-script-validation) for explicit executable
selection, duplicate-module isolation and the elevated native NTFS restore gate. PowerShell 7 compatibility is checked separately when installed.

## Repository ownership

| Path | Owns | Not here |
| --- | --- | --- |
| `backend/src/` | Application source: the seven .NET projects (business rules, persistence, application services, API and Server host, Desktop host, documents, `AuthLens.Cli` for `accounts-code` and developer tools) | Build, release or test logic |
| `backend/AuthLens.slnx`, `Directory.Build.props`, `product-version.json` | The .NET build: one solution, shared compiler settings, the only product version ([versioning](../architecture/VERSIONING.md)) | |
| `backend/src/AuthLens.Api/AuthLens.Api.csproj` | **The frontend build and embedding** (`AuthLensBuildFrontend`, `AuthLensEmbedFrontend`): the only place that turns `frontend/` into the shipped UI | npm steps in scripts |
| `backend/tests/` | `AuthLens.Tests` (xUnit, fixtures) and `AuthLens.BrowserHost` (the test-only .NET host Playwright starts) | |
| `backend/scripts/` | Release (`build-release.ps1`/`.sh`, `verify-release.ps1`, `build-installers.ps1`), Windows deployment (`deploy/`), operator tools (`Service-Manager.ps1`, `start-server-test.ps1`) and their Pester/Bash tests (`scripts/tests/`) | Application code |
| `backend/installer/` | Inno Setup scripts; built only from a verified release folder | |
| `backend/tools/` | Historical SAP Lens 1 reference generators, synthetic data and benchmarks; never run by a build or test | |
| `frontend/` | React/Vite source (`src/`), its configs, unit tests and the Playwright suite (`tests/`, which drives the .NET host) | .NET code |
| `scripts/` (root) | Repository-wide checks (`check-*.py`, `product-version.mjs`, `sync-lucide-catalog.mjs`) and `browser-server.mjs` (starts `AuthLens.BrowserHost` for Playwright and `npm run dev`) | Release or deployment |
| `docs/`, `examples/`, `assets/` | Documentation, synthetic sample files, the product icon and logo (used by the projects and installers) | Private data |
| `.github/workflows/validate.yml` | The only CI workflow, on push to `main` only ([CI](CI.md)) | |

## Build and publish flow

MSBuild is the only frontend build of a release; the scripts orchestrate and verify.

1. **Checks** (`build-release.ps1` on Windows, `build-release.sh` on Linux): Node.js 24 or 25, a valid `product-version.json`, the commit and
   whether the tree is dirty (recorded as `source_dirty`), and that no release folder is overwritten.
2. **One build:** the script removes `frontend/dist` and runs `dotnet build AuthLens.slnx -c Release -p:SourceRevisionId=<commit> -p:BuildFrontend=true`.
   `AuthLensBuildFrontend` runs `npm ci` and `npm run build` once (the `prebuild` step checks the version mirror and writes `dist/product-version.json`
   with the commit); `AuthLensEmbedFrontend` embeds `dist` into `AuthLens.Api.dll`. The script checks that `dist` exists and carries this commit.
3. **Tests:** `dotnet test --no-build` on exactly that build (skippable for development builds; `-TestFilter` for deployment's focused selection).
4. **Publish:** Server (`win-x64`; Linux also `linux-x64`) and Desktop (`win-x64`) are published without `BuildFrontend`: they find this run's
   `dist` and embed it without rebuilding the frontend.
5. **Validation:** exact file lists, the version and commit in every executable, the embedded UI present, and **freshness**: each executable
   must contain this run's `index.html` (which names the content-hashed bundles) and `product-version.json` (with this commit). A stale UI fails.
6. **Manifest and verification:** `build-manifest.json` and `SHA256SUMS`, the secret scan, then `verify-release.ps1`, which checks the shared
   manifest contract (below) independently of the builder. The Linux script runs it when PowerShell 7 is installed and warns otherwise.

**Manifest contract (schema 1, `verify-release.ps1`, Pester `Release verification`):** required fields `schema`, `product`, `version`, `channel`,
`file_version`, `ui_source_version`, `source_sha` (40 hex), `source_dirty` (boolean), `source_committed_at`, `branch`, `build_timestamp_utc`,
`target_platform`, `dotnet_sdk`, `node`, `publish`, `executables` and `artifacts`; channel and file version follow from the version; the folder name
carries version and platform; every artifact has a relative path, its size and SHA-256, and `SHA256SUMS` covers every file. Platform rules:
`win-x64` lists `server/AuthLens.Api.exe`, a Desktop executable and `publish.desktop_native_libraries`; `linux-x64` lists only `server/AuthLens.Api`.
Releases built before the rename to AuthLens keep verifying (naming register in [versioning](../architecture/VERSIONING.md)). The builders' texts
may differ where the platform does (for example the native-library note).

Release folders on a Windows host are **server deployment packages** (no `desktop/`, no `symbols/`, a `deployment-package.json`): verify them
with `verify-release.ps1 -Scope Server` ([release packages](../deployment/WINDOWS_DEPLOYMENT.md#release-packages-and-integrity)). Script tests:
`verify-release.Tests.ps1` (manifest contract, server packages, publication; shared fixtures in `ReleaseFixture.ps1`), `AuthLens.Acl.Tests.ps1`
(NTFS policy by SID, audit, ProtectAcl/RestoreAcl with replaced ACL reads and icacls), `AuthLens.Deploy.Tests.ps1` (configuration, install layout, service, deploy/rollback/recover/restore state machine; tests that need `C:\` paths, real ACLs or robocopy are skipped on Linux).

Development builds: `dotnet build` uses an existing `dist` as it is. CI builds the frontend once in its frontend job and passes `dist` to the .NET
and browser jobs, so their builds embed it without rebuilding.

**Browser tests:** `npm --prefix frontend run test:browser` starts the test-only
.NET host (`backend/tests/AuthLens.BrowserHost`) through `scripts/browser-server.mjs`.
It embeds the current `frontend/dist` (built only when missing); build the frontend first after a change. One worker, one
loopback port and a new disposable data directory per Playwright process. Readiness
uses `/health/ready`; an occupied port fails without contacting or terminating its
owner. Shutdown is bounded, waits for the owned child and removes only its temp
directory. `AUTHLENS_BROWSER_TEST_PORT` selects a separate port when needed.
`npm run dev:backend` uses the same disposable host on 18744 (Vite on 18743).
These are synthetic Desktop-capability fixtures, not a deployed Accounts server.
The synthetic capability is injected by Playwright/Vite only; production hosts
retain their normal token/session policy.

## Browser tests

`npm run test:browser` runs the Playwright suite against the isolated .NET host (`scripts/browser-server.mjs`, `backend/tests/AuthLens.BrowserHost`):
one host and disposable data directory per Playwright process, the Desktop-mode access token on every request, one worker. No Python and no
SAP Lens 1 server are involved; fixtures are versioned files in `frontend/tests/fixtures` (synthetic CSV and SoD reference workbooks).
CI runs the focused smoke: `npm --prefix frontend run test:browser -- tests/dotnet-host.spec.ts tests/component-library.spec.ts`.

Tests that exercised SAP Lens 1 itself were removed with it: its Python server process and identity codes, its desktop startup document, and its
backup format. The remaining suite is kept and run in full at checkpoints. Specs never change a source file through a settings save (AuthLens refuses
`*_csv_path` in `POST /api/configuration`: "Source files change through Data Sources"): they call `postConfiguration` in
`frontend/tests/support.ts`, which saves ordinary settings and activates each changed source through `POST /api/data-sources/{source}/select`,
the call the UI makes. In the UI, specs use the browser picker, the source location field (`activateSourcePath`, `activateCSV`) or real
downloads; the SAP Lens 1 desktop bridge no longer exists.

## Backend layout

The .NET backend lives in [`backend/`](../../backend):

| Path | Purpose |
| --- | --- |
| `src/AuthLens.Domain` | Ported v1 business rules: CSV import, normalization, catalogue, users, lookups, comparison, SoD, import checks |
| `src/AuthLens.Persistence` | EF Core SQLite: schema, migrations, immutability triggers, write coordinator, integrity, online backup |
| `src/AuthLens.Application` | Import pipeline, persistent job queue and worker, snapshot service, review service, accounts, application backups and crypto, SAP Lens 1 archive validation, data retention |
| `src/AuthLens.Api` | ASP.NET Core host and Server entry point: `/api/v1`, OpenAPI, problem details, health, security boundary, embedded production React UI (`frontend/dist`) and sign-in page, v1 compatibility API (`V1Compatibility.cs`), startup probe |
| `src/AuthLens.Desktop` | Windows shell: WinForms + WebView2, in-process core, loopback, per-run token |
| `src/AuthLens.Cli` | `accounts-code` (administrator activation and recovery code, an operator command), plus developer tools: equivalence writer, benchmark, cross-process database probes |
| `tests/AuthLens.Tests` | xUnit tests (418 at the last full run): domain, SQLite, imports, jobs, reviews, multi-process concurrency, HTTP integration, UI serving, sign-in, startup, network policy, certificates, LAN HTTPS, v1 compatibility contracts (Data Sources, Access, Data Health, Dashboard, Saved Filters, Access Packages, accounts and sessions, Employee Directory, Account Review, SoD source metadata, catalogue, reference workbook and analysis), build integration (embedded UI, incremental embedding, release script order), publish acceptance (`Category=Publish`, slow) |
| `tools/` | Synthetic data generators, Python v1 reference runner, comparers, benchmark harnesses, v1 reference-data export |
| `installer/` | Inno Setup installers: `AuthLens-Desktop.iss` (per user) and `AuthLens-Server.iss` (machine), built by `scripts/build-installers.ps1` ([installers](../deployment/WINDOWS_DEPLOYMENT.md#installers)) |
| `scripts/` | `build-release.ps1` (Windows) and `build-release.sh` (Linux): one .NET build that builds and embeds the UI, tests, self-contained single-file packages in a versioned release folder (`server/`, `desktop/`, `symbols/`, `build-manifest.json`, `README.txt`, `SHA256SUMS`); `verify-release.ps1`; `start-server-test.ps1` (test launcher); `deploy/` (SSH-driven Windows deployment); Pester and Bash tests in `scripts/tests` |

## Reproduce

Prerequisites: .NET SDK 10 (LTS), Node.js 24 or 25 (frontend), PowerShell 7 with Pester 5 (script tests), Python 3 for the repository checks
(`scripts/requirements-checks.txt`). Builds and tests never need SAP Lens 1. Only regenerating a v1 comparison fixture with `tools/*_reference.py`
does: a Python 3.12 environment with SAP Lens 1's requirements and `SAP_LENS_V1_BACKEND` pointing at a SAP Lens 1 checkout
(`tools/v1_location.py`; for example a worktree of commit `604f21e`).

```bash
cd backend
dotnet build AuthLens.slnx -c Release
dotnet test tests/AuthLens.Tests -c Release

# Functional equivalence (synthetic data only)
D=$(mktemp -d)
for v in base changed shrunk; do for s in small large; do
  python -I tools/generate_dataset.py --size $s --variant $v --out $D/$s$([ $v = base ] || echo -$v); done; done
python -I tools/generate_malformed.py $D/malformed
python -I tools/python_reference.py --data $D --scenarios tools/scenarios.json --malformed $D/malformed --out $D/python.json
dotnet src/AuthLens.Cli/bin/Release/net10.0/AuthLens.Cli.dll equivalence --data $D --scenarios tools/scenarios.json --malformed $D/malformed --out $D/dotnet.json
python -I tools/compare_equivalence.py $D/python.json $D/dotnet.json        # exit code 1 on any mismatch
# large: add --dataset large and use tools/scenarios-large.json on both sides

# Benchmarks
python -I tools/bench_algorithms.py --data $D --out $D/python-alg.json
dotnet src/AuthLens.Cli/bin/Release/net10.0/AuthLens.Cli.dll bench --data $D --out $D/dotnet-alg.json
dotnet publish src/AuthLens.Api -c Release -r linux-x64 --self-contained true -o $D/server-linux-x64
python -I tools/bench_http.py --data $D --dotnet $D/server-linux-x64 --out $D/http.json
```

Generated data, publish output and benchmark JSON stay outside the repository.

## Testing

- **Suite:** `dotnet test tests/AuthLens.Tests -c Release` runs every xUnit test; the release scripts run the same suite. During development,
  select the affected classes, for example `--filter "FullyQualifiedName~V1DataMigrationTests|FullyQualifiedName~ApplicationBackupTests"`.
- **Python v1 references:** tests that compare with SAP Lens 1 read fixtures written by `tools/*_reference.py` from the real v1 code
  (`SAP_LENS_V1_BACKEND` pointing at a SAP Lens 1 checkout); a test that compares with v1 is also checked by tampering its fixture once (it must fail).
- **SAP Lens 1 installation fixture:** `tests/AuthLens.Tests/Fixtures/v1-data` is written by `tools/v1_data_fixture.py`
  (`python -I tools/v1_data_fixture.py $SAP_LENS_V1_BACKEND <out>`). It is a v1 data directory with SoD decisions, periods, remediation,
  legacy reviews and Account Review history, plus its host-key and passphrase `.slbak` backups and `expected.json` (synthetic secrets
  included). The repository `.gitignore` excludes private v1 data patterns, so these fixture paths (and the build-970d219 account store) are
  re-included explicitly; check `git status --ignored` after regenerating.
- **Migration procedure:** `pwsh -File scripts/tests/v1-migration-procedure.ps1 -Exe <AuthLens.Api> -Root <new folder>` runs the documented
  Windows procedure ([V1_MIGRATION.md](../migration/V1_MIGRATION.md)) against that fixture with 12 checks.
- **Not covered by automated tests here:** native Windows (Desktop, service, ACLs, PowerShell 5.1), WebView2, and real SAP Lens 1 data.

## Infrastructure commands and compatibility

The SDK selector in `global.json` uses the latest installed .NET 10 feature band;
Node 24 is the CI baseline (24/25 satisfy the frontend engine). Product versions
are checked by `node scripts/product-version.mjs`, independently of SDK selection.
For CI contracts/security checks see [CI](CI.md).

```bash
# Parse active PowerShell without running Windows operations:
pwsh -NoProfile -File backend/scripts/check-powershell.ps1
# Fake SSH + local PowerShell: temporary clone only, no remote connection/service:
bash backend/scripts/tests/deploy-windows.test.sh
# Pester 5.7.1, mocked platform/deployment operations:
pwsh -NoProfile -Command "Invoke-Pester -Path backend/scripts/tests -CI"
```

Build/release scripts remain in `backend/scripts`. Historical
`experiments/dotnet-backend` references survive only in the deployment compatibility
resolver and its older-commit tests. They are needed for verified rollback and
inspection of pre-promotion commits, and are not competing current entrypoints.
The release scripts now read the frontend mirror, not archived v1 metadata. Their
checksum, source identity, no-overwrite, backup/restore and private-data guards
remain intact. No installed service or release is modified by repository checks.

## Windows SQLite and clock fixtures

Read-only migration inspection must copy the database plus WAL/journal into private scratch and open only the copy. Do not copy live SHM on Windows:
its byte-range locks cause access failures; SQLite reconstructs that disposable index in scratch. Hash durable source files before/after the copy and
refuse concurrent changes. Never call global ClearAllPools from inspection: it can close unrelated pooled connections and checkpoint their live WAL.
Tests asserting unchanged sidecars keep a leased non-pooled source connection open across inspection, independently of other fixtures' pool cleanup.

A fixture expecting UTC must explicitly supply a TimeProvider whose LocalTimeZone is UTC. Production schedule preview/execution use the provider's
actual local zone; hardcoding UTC hides timezone/DST defects on a Paris Windows development PC. Test gaps and repeated wall times with synthetic clocks,
never by changing a host clock. PowerShell 5.1 native stderr becomes ErrorRecords: negative subprocess tests must preserve exit code and raw ToString()
lines instead of letting ErrorActionPreference=Stop or formatted Out-String terminate/wrap the expected refusal.
