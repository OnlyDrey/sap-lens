# Scripts

Build, validation, packaging and maintenance tooling. Run everything from the repository root. The detailed build reference is
[docs/BUILD.md](../docs/BUILD.md); testing is described in [docs/development/TESTING.md](../docs/development/TESTING.md).

## Use these directly

| Command | Platform | Purpose |
| --- | --- | --- |
| `.\scripts\build.ps1 -Mode build -Platform windows -Target all` | Windows x64, PowerShell 5.1 or 7 | Windows bootstrapper: finds Python 3.12 x64 (installs it only with consent) and forwards to `build.py`. Modes `quick`, `test`, `build`, `package`, `release`, `clean`. Works from any working directory. |
| `python3.12 scripts/build.py <mode> [--platform windows\|linux\|docker] [--target ...]` | Windows and Linux | The build engine (CLI, prerequisites, targets). Linux packages and Docker images are built here. |
| `python scripts/run-tests.py smoke\|targeted <feature>\|regression\|release\|list\|check` | Windows and Linux | Test profiles; feature ownership is in `test-map.json`. |
| `python scripts/validate.py --level fast\|feature\|full` | Windows and Linux | Local validation by risk level. |
| `python scripts/check-docs.py`, `check-workflows.py`, `sync-lucide-catalog.mjs --check` | Windows and Linux | Static repository checks. |
| `python scripts/benchmarks/data_benchmark.py`, `benchmarks/profile-sod.py` | Windows and Linux | Import, refresh, startup and API timings; SoD write profiling. |
| `python scripts/maintenance/validation_tracker.py`, `generate-examples.py`, `reference-template.py` | Windows and Linux | Validation tracker CSV and workbook, synthetic examples, SoD reference template. |

## Internal helpers

Called by the entrypoints above, by workflows or by each other; not supported as entrypoints. Windows-only scripts cannot be executed in the Linux
development environment; they are parse-checked and covered by static tests only (see the
[validation status](../docs/deployment/README.md#validation-status)).

| Group | Files | Platform |
| --- | --- | --- |
| Build engine | `build_system/*` | both |
| Deployment builders | `build-deployments.py`, `deployment-package.py`, `package-docker.py`, `deployment-release.py`, `check-deployment-download.py` | both |
| Linux bundle runtime (shipped inside the native archive) | `install-linux-server.py`, `run-installed-server.py` | Linux |
| Windows desktop and service packaging | `build-windows.ps1`, `build-local.ps1`, `local-build.py`, `package-windows-deployment.ps1`, `build-desktop-installer.ps1`, `build-server-windows.ps1`, `build-service-manager.ps1`, `release-windows.py`, `write-build-report.py`, `write-windows-metadata.py` | Windows |
| Service management (shipped in the service bundle) | `manage-server-service.ps1` | Windows |
| Verification | `verify-windows-package.py`, `verify-server-bundle.py`, `verify-desktop-installer.py`, `verify-desktop-distribution.py`, `verify-artifact-zip.py` | both |
| Smoke and lifecycle tests | `test-windows-exe.ps1`, `test-desktop-installer.ps1`, `test-server-service.ps1`, `test-service-management.ps1` (Windows); `test-native-deployment.py`, `test-docker-deployment.py`, `test-docker-lifecycle.py` (Linux, Docker) | as listed |
| Validation and CI support | `ci.py`, `check-powershell.ps1`, `serve-browser-tests.py`, `test-map.json`, `requirements-audit.txt` | both |
| Generators used by `npm` and packaging | `product-version.mjs`, `frontend-licenses.mjs` | both |

## Layout rules

* Public entrypoints and shared pipeline pieces stay at the top level; workflows, release tooling and documentation address them by these paths.
* `benchmarks/` and `maintenance/` hold tools that no workflow calls. Add a subdirectory only when it removes clutter without moving a documented entrypoint.
* Python scripts find the repository through `Path(__file__).resolve().parents[N]`; keep `N` correct when moving a file. PowerShell scripts use
  `Split-Path $PSScriptRoot -Parent`.
* Every new script is listed in the inventory table of [docs/BUILD.md](../docs/BUILD.md); a test enforces this.
