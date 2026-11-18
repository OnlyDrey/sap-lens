# Repository scripts

SAP Lens runtime and deployment tooling lives in `backend/scripts`; these are
repository-wide development helpers. Canonical commands: [development](../docs/development/README.md),
[CI](../docs/development/CI.md), [deployment](../docs/deployment/README.md).

| Script | Purpose |
| --- | --- |
| `browser-server.mjs` | Owned disposable .NET browser/dev host; bounded shutdown and no inherited operator configuration |
| `product-version.mjs` | Check frontend mirrors against `backend/product-version.json`; explicit `--write` synchronizes mirrors |
| `check-structure.py` | Active .NET layout, frontend version mirrors, and no dependency on the archived SAP Lens 1 |
| `check-workflows.py` | Parsed YAML, exact main-only trigger, pinned actions and read-only/no-publish contracts |
| `check-dependencies.py` | NuGet advisory audit with fail-closed JSON parsing and nonzero findings exit code |
| `check-docs.py` | Offline relative Markdown link and anchor checks |
| `check-secrets.py` | Tracked/release file scan; diagnostics never print matched values |
| `sync-lucide-catalog.mjs` | Check/update the locked icon list in the .NET embedded registry |
| `tests/` | Focused version, CI, structure and container-boundary regression tests |
| `requirements-checks.txt` | Pinned development-only YAML parser for workflow contracts |

SAP Lens 1 (Python) is archived outside the repository; no active script, test or build depends on it. Historical deployments can still resolve a pre-promotion
commit through the existing deployment compatibility resolver. That resolver's
`experiments/dotnet-backend` references are deliberate compatibility paths, not
current build paths; removing them would break rollback/older-commit inspection.
