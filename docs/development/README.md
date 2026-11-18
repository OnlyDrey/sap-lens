# Development and testing (SAP Lens .NET)

How to build and test SAP Lens. Deployment: [deployment](../deployment/README.md). Architecture: [architecture](../architecture/README.md).
SAP Lens 1 development (Python, `legacy/v1/scripts/run-tests.py`) is documented in [legacy v1 development](../legacy/v1/development/README.md).

## Everyday commands

```bash
# .NET backend (from the repository root)
cd backend && dotnet build SapLens.slnx -c Release
dotnet test tests/SapLens.Tests -c Release --no-build --filter "FullyQualifiedName~V1DataMigrationTests"   # affected classes first
dotnet test tests/SapLens.Tests -c Release --no-build                                                       # whole suite at checkpoints

# Frontend (from frontend/)
npm ci && npm run check:types && npm run lint && npm run test:unit && npm run build

# Deployment and release scripts (from backend/)
pwsh -NoProfile -Command "Invoke-Pester scripts/tests"        # Pester: deployment state machine and test launcher
bash scripts/tests/deploy-windows.test.sh                     # SSH orchestrator with a fake ssh (end to end through pwsh)

# Repository checks (from the repository root)
python scripts/check-docs.py && python scripts/check-secrets.py && git diff --check
```

Run the smallest relevant selection while developing and the whole suite at checkpoints (AGENTS.md, progressive validation). The .NET build
embeds `frontend/dist`: build the frontend first, or the server serves the previously built UI.

**Browser tests:** `npm --prefix frontend run test:browser` starts the test-only
.NET host (`backend/tests/SapLens.BrowserHost`) through `scripts/browser-server.mjs`.
It embeds the current `frontend/dist`; build the frontend first. One worker, one
loopback port and a new disposable data directory per Playwright process. Readiness
uses `/health/ready`; an occupied port fails without contacting or terminating its
owner. Shutdown is bounded, waits for the owned child and removes only its temp
directory. `SAP_LENS_BROWSER_TEST_PORT` selects a separate port when needed.
`npm run dev:backend` uses the same disposable host on 18744 (Vite on 18743).
These are synthetic Desktop-capability fixtures, not a deployed Accounts server.
The synthetic capability is injected by Playwright/Vite only; production hosts
retain their normal token/session policy.

Migration gaps are explicit: four Python-runtime specs are preserved under
`legacy/v1/frontend/tests` ([inventory](../../legacy/v1/frontend/README.md)).
Two active specs still use optional Python reference generators. Run the .NET
smoke with `npm --prefix frontend run test:browser -- tests/dotnet-host.spec.ts`.
The rest of the preserved suite is available for discovering API/UI parity gaps;
passing the smoke is not a claim that every migrated browser workflow passes.

## Backend layout

The .NET backend lives in [`backend/`](../../backend):

| Path | Purpose |
| --- | --- |
| `src/SapLens.Domain` | Ported v1 business rules: CSV import, normalization, catalogue, users, lookups, comparison, SoD, import checks |
| `src/SapLens.Persistence` | EF Core SQLite: schema, migrations, immutability triggers, write coordinator, integrity, online backup |
| `src/SapLens.Application` | Import pipeline, persistent job queue and worker, snapshot service, review service, accounts, application backups and crypto, SAP Lens 1 archive validation, data retention |
| `src/SapLens.Api` | ASP.NET Core host and Server entry point: `/api/v1`, OpenAPI, problem details, health, security boundary, embedded production React UI (`frontend/dist`) and sign-in page, v1 compatibility API (`V1Compatibility.cs`), startup probe |
| `src/SapLens.Desktop` | Windows shell: WinForms + WebView2, in-process core, loopback, per-run token |
| `src/SapLens.Cli` | Equivalence writer, benchmark, cross-process database probes |
| `tests/SapLens.Tests` | xUnit tests (418 at the last full run): domain, SQLite, imports, jobs, reviews, multi-process concurrency, HTTP integration, UI serving, sign-in, startup, network policy, certificates, LAN HTTPS, v1 compatibility contracts (Data Sources, Access, Data Health, Dashboard, Saved Filters, Access Packages, accounts and sessions, Employee Directory, Account Review, SoD source metadata, catalogue, reference workbook and analysis), build integration (embedded UI, incremental embedding, release script order), publish acceptance (`Category=Publish`, slow) |
| `tools/` | Synthetic data generators, Python v1 reference runner, comparers, benchmark harnesses, v1 reference-data export |
| `installer/` | Inno Setup installers: `SapLens-Desktop.iss` (per user) and `SapLens-Server.iss` (machine), built by `scripts/build-installers.ps1` ([installers](../deployment/WINDOWS_DEPLOYMENT.md#installers)) |
| `scripts/` | `build-release.ps1` (Windows) and `build-release.sh` (Linux): UI build, .NET build and tests, self-contained single-file packages in a versioned release folder (`server/`, `desktop/`, `symbols/`, `build-manifest.json`, `README.txt`, `SHA256SUMS`); `verify-release.ps1`; `start-server-test.ps1` (test launcher); `deploy/` (SSH-driven Windows deployment); Pester and Bash tests in `scripts/tests` |

## Reproduce

Prerequisites: .NET SDK 10 (LTS), Node.js 24 or 25 (frontend), PowerShell 7 with Pester 5 (script tests). The v1 reference tools need the
repository's Python 3.12 venv with `legacy/v1/backend/requirements-dev.txt`.

```bash
cd backend
dotnet build SapLens.slnx -c Release
dotnet test tests/SapLens.Tests -c Release

# Functional equivalence (synthetic data only)
D=$(mktemp -d)
for v in base changed shrunk; do for s in small large; do
  python -I tools/generate_dataset.py --size $s --variant $v --out $D/$s$([ $v = base ] || echo -$v); done; done
python -I tools/generate_malformed.py $D/malformed
python -I tools/python_reference.py --data $D --scenarios tools/scenarios.json --malformed $D/malformed --out $D/python.json
dotnet src/SapLens.Cli/bin/Release/net10.0/SapLens.Cli.dll equivalence --data $D --scenarios tools/scenarios.json --malformed $D/malformed --out $D/dotnet.json
python -I tools/compare_equivalence.py $D/python.json $D/dotnet.json        # exit code 1 on any mismatch
# large: add --dataset large and use tools/scenarios-large.json on both sides

# Benchmarks
python -I tools/bench_algorithms.py --data $D --out $D/python-alg.json
dotnet src/SapLens.Cli/bin/Release/net10.0/SapLens.Cli.dll bench --data $D --out $D/dotnet-alg.json
dotnet publish src/SapLens.Api -c Release -r linux-x64 --self-contained true -o $D/server-linux-x64
python -I tools/bench_http.py --data $D --dotnet $D/server-linux-x64 --out $D/http.json
```

Generated data, publish output and benchmark JSON stay outside the repository.

## Testing

- **Suite:** `dotnet test tests/SapLens.Tests -c Release` runs every xUnit test; the release scripts run the same suite. During development,
  select the affected classes, for example `--filter "FullyQualifiedName~V1DataMigrationTests|FullyQualifiedName~ApplicationBackupTests"`.
- **Python v1 references:** tests that compare with SAP Lens 1 read fixtures written by `tools/*_reference.py` from the real v1 code
  (`.venv` with `legacy/v1/backend/requirements-dev.txt`); a test that compares with v1 is also checked by tampering its fixture once (it must fail).
- **SAP Lens 1 installation fixture:** `tests/SapLens.Tests/Fixtures/v1-data` is written by `tools/v1_data_fixture.py`
  (`.venv/bin/python -I tools/v1_data_fixture.py ../legacy/v1/backend <out>`). It is a v1 data directory with SoD decisions, periods, remediation,
  legacy reviews and Account Review history, plus its host-key and passphrase `.slbak` backups and `expected.json` (synthetic secrets
  included). The repository `.gitignore` excludes private v1 data patterns, so these fixture paths (and the build-970d219 account store) are
  re-included explicitly; check `git status --ignored` after regenerating.
- **Migration procedure:** `pwsh -File scripts/tests/v1-migration-procedure.ps1 -Exe <SapLens.Api> -Root <new folder>` runs the documented
  Windows procedure ([V1_MIGRATION.md](../migration/V1_MIGRATION.md)) against that fixture with 12 checks.
- **Not covered by automated tests here:** native Windows (Desktop, service, ACLs, PowerShell 5.1), WebView2, and real SAP Lens 1 data.

## Infrastructure commands and compatibility

The SDK selector in `global.json` uses the latest installed .NET 10 feature band;
Node 24 is the CI baseline (24/25 satisfy the frontend engine). Product versions
are checked by `node scripts/product-version.mjs`, independently of SDK selection.
For CI contracts/security checks see [CI](CI.md); containers are optional
([Docker](../deployment/DOCKER.md)).

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
