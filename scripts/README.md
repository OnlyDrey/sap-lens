# Scripts

Build, validation, packaging and maintenance tooling. Run everything from the repository root (the scripts also work from any other working directory). The detailed build reference
is [docs/BUILD.md](../docs/BUILD.md); testing is described in [docs/development/TESTING.md](../docs/development/TESTING.md).

## Layout

```
scripts/
  build.ps1  build.py  build_system/       public build entrypoints and the engine (build_system/windows/: Python ports of the Windows build scripts, opt-in)
  run-tests.py  validate.py  check-docs.py  check-workflows.py  test-map.json     public validation entrypoints
  packaging/     Windows packaging helpers: local build receipts, release gate, build report, metadata and the package/bundle/installer verifiers
  deployment/    deployment builders and release gates: build-deployments, deployment-release, package-docker, check-deployment-download
  testing/       browser test server, CI step runner, native Linux and Docker smoke tests
  benchmarks/    data-path benchmark and SoD profiling
  maintenance/   validation tracker, synthetic examples, SoD reference template
  *.ps1          Windows PowerShell scripts (see below); *.mjs generators called by npm, the Dockerfile and packaging
  deployment-package.py  install-linux-server.py  run-installed-server.py   shipped inside the Linux bundle (see rules)
```

## Use these directly

| Command | Platform | Purpose |
| --- | --- | --- |
| `.\scripts\build.ps1 -Mode build -Platform windows -Target all` | Windows x64, PowerShell 5.1 or 7 | Windows bootstrapper: finds Python 3.12 x64 (installs it only with consent) and forwards to `build.py`. Modes `quick`, `test`, `build`, `package`, `release`, `clean`. Works from any working directory. |
| `python3.12 scripts/build.py <mode> [--platform windows\|linux\|docker] [--target ...]` | Windows and Linux | The build engine (CLI, prerequisites, targets). Linux packages and Docker images are built here. |
| `python scripts/run-tests.py smoke\|targeted <feature>\|regression\|release\|list\|check` | Windows and Linux | Test profiles; feature ownership is in `test-map.json`. |
| `python scripts/validate.py --level fast\|feature\|full` | Windows and Linux | Local validation by risk level. |
| `python scripts/check-docs.py`, `check-workflows.py`, `node scripts/sync-lucide-catalog.mjs --check` | Windows and Linux | Static repository checks. |
| `python scripts/benchmarks/data_benchmark.py`, `benchmarks/profile-sod.py` | Windows and Linux | Import, refresh, startup and API timings; SoD write profiling. |
| `python scripts/maintenance/validation_tracker.py`, `generate-examples.py`, `reference-template.py` | Windows and Linux | Validation tracker CSV and workbook, synthetic examples, SoD reference template. |

## Internal helpers

Called by the entrypoints above, by workflows or by each other; not supported as entrypoints. Windows-only scripts cannot be executed in the Linux development environment; they are parse-checked and
covered by static and contract tests only (see the [validation status](../docs/deployment/README.md#validation-status)).

| Group | Files | Platform |
| --- | --- | --- |
| Build engine | `build_system/*`; `build_system/windows/*` are the opt-in Python ports of six PowerShell build scripts (not yet validated on Windows, see [BUILD.md](../docs/BUILD.md#python-ports-of-the-windows-build-scripts-and-their-validation-checklist)) | both |
| Deployment builders | `deployment/build-deployments.py`, `deployment/package-docker.py`, `deployment/deployment-release.py`, `deployment/check-deployment-download.py` | both |
| Bundle packager and runtime (shipped inside the native archive) | `deployment-package.py`, `install-linux-server.py`, `run-installed-server.py` | Linux |
| Windows desktop and service packaging (PowerShell originals, authoritative until the ports are validated) | `build-windows.ps1`, `build-local.ps1`, `package-windows-deployment.ps1`, `build-desktop-installer.ps1`, `build-server-windows.ps1`, `build-service-manager.ps1` | Windows |
| Windows packaging helpers | `packaging/local-build.py`, `packaging/release-windows.py`, `packaging/write-build-report.py`, `packaging/write-windows-metadata.py` | Windows |
| Service management (shipped in the service bundle) | `manage-server-service.ps1` | Windows |
| Verification | `packaging/verify-windows-package.py`, `packaging/verify-server-bundle.py`, `packaging/verify-desktop-installer.py`, `packaging/verify-desktop-distribution.py`, `packaging/verify-artifact-zip.py` | both |
| Smoke and lifecycle tests | `test-windows-exe.ps1`, `test-desktop-installer.ps1`, `test-server-service.ps1`, `test-service-management.ps1` (Windows); `testing/test-native-deployment.py`, `testing/test-docker-deployment.py`, `testing/test-docker-lifecycle.py` (Linux, Docker) | as listed |
| Validation and CI support | `testing/ci.py`, `testing/serve-browser-tests.py`, `check-powershell.ps1`, `requirements-audit.txt` | both |
| Generators used by `npm` and packaging | `product-version.mjs`, `frontend-licenses.mjs` | both |

## Layout rules

* Public entrypoints (`build.*`, `run-tests.py`, `validate.py`, `check-*.py`) stay at the top level: documentation, workflows and developers address them by these paths.
* **Scripts shipped inside a bundle keep the path they have in the bundle.** `deployment-package.py`, `install-linux-server.py` and `run-installed-server.py` are copied to `scripts/<name>` in the native
  archive and find the bundle root from that layout, so repository and bundle layouts coincide. Do not move them without changing the archive contract.
* The PowerShell scripts stay at the top level until their Python ports pass native Windows validation; `Split-Path $PSScriptRoot -Parent` is their repository root. After validation they are removed, not moved.
* Python scripts find the repository through `Path(__file__).resolve().parents[N]`; keep `N` correct when moving a file. Scripts that load a sibling by name search below `scripts/` (`rglob`), so a move needs no loader table.
* Every new script is listed in the inventory table of [docs/BUILD.md](../docs/BUILD.md); a test enforces this.
