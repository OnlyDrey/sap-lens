# SAP Lens 2.0: .NET backend prototype

Status: architecture experiment on branch `experiment/dotnet-backend`. Not a product release, not merged into `work` or `main`, and not a
replacement of any production installer, launcher, workflow or version. Production code under `backend/`, `frontend/`, `scripts/` and
`.github/` is unchanged.

Evidence tags used in every document: **[M]** measured on Linux x64 in this environment (4 vCPU, 15 GiB), **[C]** read from code,
**[T]** proven by an automated test in this branch, **[U]** not verified (in particular: nothing here ran on Windows).

## Documents

| Document | Content |
| --- | --- |
| [FEATURE_PARITY.md](FEATURE_PARITY.md) | Phase 0 inventory: every UI area, v1 implementation, .NET status, gaps, complexity, tests |
| [ROUTE_AUDIT.md](ROUTE_AUDIT.md) | Generated route-by-route status of every API route the React UI references |
| [RELEASE_STATUS.md](RELEASE_STATUS.md) | Phase 3 to 6 status, release decision (NO-GO), remaining work, next commands |
| [UI_INTEGRATION.md](UI_INTEGRATION.md) | The production React UI served by .NET: build, adapter, authentication, Windows VM commands |
| [PHASE1_DECISION.md](PHASE1_DECISION.md) | Recommendation (CONDITIONAL GO), evidence, blockers, open questions |
| [ARCHITECTURE_ASSESSMENT.md](ARCHITECTURE_ASSESSMENT.md) | What v1 is, read from source and tests; what a C# backend must preserve |
| [DEPENDENCY_MAPPING.md](DEPENDENCY_MAPPING.md) | Every Python runtime dependency classified: replace, redesign, or keep isolated |
| [TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md) | Modular monolith, module boundaries, request and job flows |
| [DATABASE_DESIGN.md](DATABASE_DESIGN.md) | SQLite schema, write coordination, immutability, migrations, backups |
| [FUNCTIONAL_EQUIVALENCE.md](FUNCTIONAL_EQUIVALENCE.md) | Python v1 versus .NET on identical synthetic data: 68/68 small, 68/68 large |
| [PERFORMANCE_BENCHMARK.md](PERFORMANCE_BENCHMARK.md) | Algorithm and service benchmarks, concurrency under import, memory, sizes |
| [DESKTOP_SERVER_DEPLOYMENT.md](DESKTOP_SERVER_DEPLOYMENT.md) | Desktop (WebView2) and Server builds, run commands, packaging assessment |
| [SERVER_NETWORK_ACCESS.md](SERVER_NETWORK_ACCESS.md) | Trusted-LAN access: HTTPS, binding policy, authentication review, firewall, deployment and verification |
| [MIGRATION_STRATEGY.md](MIGRATION_STRATEGY.md) | How v1 data, decisions and evidence would move, with rollback |

## Code

Everything lives in [`experiments/dotnet-backend`](../../../experiments/dotnet-backend):

| Path | Purpose |
| --- | --- |
| `src/SapLens.Domain` | Ported v1 business rules: CSV import, normalization, catalogue, users, lookups, comparison, SoD, import checks |
| `src/SapLens.Persistence` | EF Core SQLite: schema, migration, immutability triggers, write coordinator, integrity, online backup, retention |
| `src/SapLens.Application` | Import pipeline, persistent job queue and worker, snapshot service, review service |
| `src/SapLens.Api` | ASP.NET Core host and Server entry point: `/api/v1`, OpenAPI, problem details, health, security boundary, embedded production React UI (`frontend/dist`) and sign-in page, v1 compatibility API (`V1Compatibility.cs`), startup probe |
| `src/SapLens.Desktop` | Windows shell: WinForms + WebView2, in-process core, loopback, per-run token (built on Linux, never run) |
| `src/SapLens.Cli` | Equivalence writer, benchmark, cross-process database probes |
| `tests/SapLens.Tests` | 196 xUnit tests: domain, SQLite, imports, jobs, reviews, multi-process concurrency, HTTP integration, UI serving, sign-in, startup, network policy, certificates, LAN HTTPS, v1 compatibility contracts (Data Sources, Access, Data Health, Dashboard, Saved Filters, Access Packages, accounts and sessions, Employee Directory, Account Review, SoD source metadata and catalogue), publish acceptance (`Category=Publish`, slow) |
| `tools/` | Synthetic data generators, Python v1 reference runner, comparers, benchmark harnesses, v1 reference-data export |
| `scripts/` | `build-release.ps1` (Windows) and `build-release.sh` (Linux): UI build, .NET build and tests, self-contained packages, build identity check, `SHA256SUMS`, `manifest.json` |

## Reproduce

Prerequisites: .NET SDK 10 (LTS), the repository's Python 3.12 venv with `backend/requirements-dev.txt`.

```bash
cd experiments/dotnet-backend
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
