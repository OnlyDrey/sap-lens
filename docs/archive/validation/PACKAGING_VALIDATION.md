# Cross-platform packaging validation — 24 October 2026

> Historical evidence: applies to the source/phase recorded below, not later
> commits. Use the [current documentation index](../../README.md) for instructions.

Historical execution record. The subsequent optional channel/publication changes
and their local-only tests are documented in [Phase 2 validation](DEPLOYMENT_RELEASE_VALIDATION.md).

Status: **local implementation and Linux packages validated; GitHub/Windows native
execution pending**. No push, workflow dispatch, release, registry publication or
merge was performed. Runtime commits `27e0622` and `a857539` remain ancestors.

Implementation: `16cbd132eb19862ea7e3ab60be80c3de6203dedc`.
Final packaging/test safety corrections and local artifact source:
`15e588639e16` (full SHA is recorded in each package manifest).
Both final Linux archives embed `0.1.0+local.15e588639e16` and that same source SHA.
The final report-only commit does not change executable/package implementation.

## Delivered architecture

One additional workflow: **Build Deployment Packages**, manual-only. Inputs:
`platform` = Windows Desktop, Windows Server Service, Linux Docker,
Linux Native/systemd or All; `version` = base MAJOR.MINOR.PATCH.

Shared validation runs once and seals frontend bytes, public production licenses,
version/source identity, run/attempt, checks and timestamp. Platform jobs depend
only on that validation, not siblings. Each consumes and verifies the same-run
attestation, performs platform checks, uploads independently, downloads its own
upload and verifies inner archive checksum/exact content. No broad write permission,
release reservation, publication, registry login or image push is introduced.

The existing desktop release workflow, canonical desktop packager, desktop PE/ZIP
verifiers and EXE smoke script are unchanged. The new desktop job calls those
canonical stages; it does not implement another PyInstaller desktop build. Shared
backend/browser validation replaces duplicate full suites in the new platform
jobs, while Windows-specific regressions, audits and native smoke remain mandatory.

## Actual local results

| Platform | Build/archive | Executed validation | Pending |
| --- | --- | --- | --- |
| Windows Desktop | Implemented orchestration, not built here | PowerShell/workflow/static contract checks | Native EXE/PE/icon/privacy and WebView2 smoke on Windows |
| Windows Service | Implemented ZIP builder, pinned WinSW/license/config generator, not built here | PowerShell parser and packaging contracts | Windows build/verifier; SCM install/start/health/stop/uninstall; reboot/recovery/UNC |
| Linux Docker amd64 | **Built and exported successfully** | Non-root/read-only runtime, frontend, auth rejection/admission, import, health/version, restart/recreation persistence, actual image dependency audit, inner archive roundtrip/privacy | GitHub upload/download execution, real Compose host-secret setup, production HTTPS gateway |
| Linux native x86-64 | **Built and exported successfully** | Hash-locked wheelhouse, offline target venv, spaces/Unicode paths, installed startup/version/import, synthetic upgrade retaining records/config, uninstall preserving data, runtime audit, archive roundtrip | Ubuntu baseline host/systemd enablement/boot/journald/hardening acceptance |
| Linux browser client | Same native archive | Non-root user-mode installation/process and API exercised | Real desktop/mobile browser acceptance; no standalone GUI/AppImage is supplied |

Linux local host: x86-64, Python 3.12.14, glibc 2.41. CI definition targets Ubuntu
22.04, and native wheel tags are checked for glibc <=2.35 compatibility. This is not
a claim that Ubuntu 22.04/24.04 or a running systemd host was tested locally.
No Windows runner was available; no Windows native or package result is marked passed.

### Checks executed

- Complete backend: **342 passed**, 19.247 seconds, command
  `python -W error::DeprecationWarning -m unittest discover -s backend/tests -v`.
- After final delivery corrections: **7 packaging tests** and **8 server tests**
  passed. The server cases also passed with the checkout's `frontend/dist`
  temporarily absent; synthetic fixtures now make clean-checkout Fast/shared CI
  independent of ignored build outputs. Original compiled assets were restored.
- TypeScript and production frontend build passed. No frontend/UI application
  source changed; the existing 224-browser-test result remains the prior runtime
  baseline. No comprehensive browser rerun was performed in this packaging task.
- Workflow contract tests (14), actionlint schema/expression/shell checks, YAML
  contracts, and all eight PowerShell parsing/static guards passed.
- Archive regression tests reject checksum mismatch, extra/duplicate/unsafe paths,
  symlinks, private files, mismatched commit/run/attempt, stale inputs, failed shared
  checks and changed validated frontend. Installer guard rejects OS directories
  before mutations; existing data/prefix must be dedicated/recognized.
- Both Linux archives were extracted again with `check-deployment-download.py`:
  exact member hashes, identity, sidecars and privacy passed. Docker archive has
  four payload files plus its manifest; native archive contains backend, compiled
  frontend, runtime wheels/requirements, deployment files, scripts and manifests.
- Final image inspection found no application settings, CSV records, access secret,
  test tree, node_modules or Git history. Synthetic test volumes/containers were removed.
- Documentation links, protected README branding comparison and `git diff --check`
  passed. Packaging outputs/logs remain ignored/outside Git.

### Security finding resolved

Auditing the actual Docker image found vulnerable base-image **pip 25.0.1**.
Docker and the native wheelhouse now consume the existing project **pip 26.2.2**
pin from `backend/requirements-build.txt`; no application dependency was upgraded.
Both final runtime audits report **no known vulnerabilities**. Docker's audit of
exact installed versions emits pip-audit's ordinary recommendation about hashed
requirements; it is visible, not suppressed. This is a Python dependency audit,
not a claim of a complete operating-system image vulnerability assessment.

The managed environment required its existing proxy routing and temporary CA
secret for Docker downloads. A changing proxy address caused an initial build
failure; the final run used current routing without TLS bypass. No session CA or
access secret is baked into the runtime image.

## Final local artifacts

Located in Git-ignored `dist/deployment/`; these are unofficial local builds,
**not yet GitHub-downloadable artifacts**.

- `SAP-Lens-Linux-Native-x64-0.1.0+local.15e588639e16.tar.gz`
  — 13,996,964 bytes.
  SHA-256 `2d551f3e6a4c535ac7edfd4566d8d93d74383aec412b55c26c98a5f452c7a229`.
- `SAP-Lens-Linux-Docker-amd64-0.1.0+local.15e588639e16.tar.gz`
  — 64,464,343 bytes.
  SHA-256 `09154c4f2d7a89ece61bb9c3339d5daa40f5d9d6e53dcfb0ffbf4376506f5e65`.

Each has an adjacent `.sha256`. Prototype outputs were retained separately outside
Git. The Docker archive includes image.tar and Compose referencing its locally
loaded versioned image; no target source compilation or registry access is needed.

## Remaining acceptance and delivery

An approved Actions run must exercise all four jobs and actual artifact roundtrips.
GitHub requires the new manual definition on the default branch for normal dispatch
registration; no merge/default-branch change is performed here. Reboot, recovery,
UNC/domain service identities, Windows native dialogs, physical mobile/non-Chromium
browsers and a real authenticated HTTPS gateway remain manual acceptance work.
Current `[skip ci]` markers preserve the user's standing instruction; a manual
packaging dispatch still requires separate explicit approval.

## Packaging files

- `.github/workflows/build-deployments.yml`, workflow contract/tests and PowerShell
  guard integration; existing desktop release workflow unchanged.
- `scripts/deployment-package.py`: identity, attestation, native archive/wheelhouse,
  exact archive checks; `check-deployment-download.py`: distribution roundtrip/summary.
- `scripts/package-windows-deployment.ps1`: canonical desktop/service orchestration;
  `build-server-windows.ps1`, `verify-server-bundle.py`, `manage-server-service.ps1`,
  `test-server-service.ps1`: service packaging, safe configuration and SCM acceptance.
- `scripts/package-docker.py`, `test-docker-deployment.py`, Dockerfile/.dockerignore:
  versioned image, audited inventory, persistent smoke and offline image export.
- `scripts/install-linux-server.py`, `run-installed-server.py`,
  `test-native-deployment.py`: safe staged target install, configuration handling,
  synthetic upgrade/uninstall validation. No relocated venv.
- `scripts/frontend-licenses.mjs`, pinned WinSW license, deployment guides and
  README package navigation outside the protected branding block.
