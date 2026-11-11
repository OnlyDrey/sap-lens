# SAP Lens build system

The public interfaces are `scripts/build.ps1` (Windows bootstrap) and `scripts/build.py`
(Python CLI on Windows/Linux). Both use the same Python engine. No command publishes
an image, changes `main`, bumps the product version, creates a tag or publishes a
release by default. **Release mode prepares and verifies artifacts only.** Actual
publication stays in the existing explicitly dispatched, branch-guarded workflow.

## Architecture

```mermaid
flowchart TD
  PS[scripts/build.ps1: Python detection and consent] --> CLI[scripts/build.py]
  CLI --> Engine[build_system: CLI, prerequisites, runner, targets]
  CI[GitHub Actions: explicit non-interactive commands] --> Engine
  Engine --> Win[Internal Windows desktop stages and local receipt]
  Engine --> Deploy[Internal deployment builder]
  Deploy --> Native[Native Linux / Docker / Windows installer and service]
  Engine --> Tests[Existing isolated validation runner]
  Engine --> Release[Existing release policy and artifact verifiers]
```

The engine owns modes, input, prerequisites, consent, routing, logging and exit
codes. Specialized scripts remain internal owners of compilation, installers,
service management, platform-specific receipts, immutable identity and verification.
It does not duplicate PyInstaller or implement a second installer/release system.

| Internal consumer | Existing implementation reused |
| --- | --- |
| Windows portable adapter | `build-local.ps1` → `build-windows.ps1` → PyInstaller, PE verifier, EXE smoke and local ZIP verifier |
| Deployment adapter | `deployment/build-deployments.py` → shared receipts → Windows package, native and Docker utilities |
| Windows installer/service | `package-windows-deployment.ps1`, `build-desktop-installer.ps1`, `build-server-windows.ps1`, `build-service-manager.ps1` |
| Tests and CI timing | `validate.py`, `run-tests.py`, `testing/ci.py`, workflow contracts |
| Release preparation/publication guards | `deployment/deployment-release.py`, `packaging/release-windows.py` and artifact verifiers |

These have actual engine/CI consumers and remain internal; they are not obsolete
copies of the public interface.

## Prerequisites

One command prepares and verifies everything below: `.\scripts\build.ps1 -Mode prerequisites` (`-CheckOnly`, `-Repair`, `-Json`; Linux: `python3.12 scripts/build.py prerequisites ...`). Details: [Development setup](development/DEVELOPMENT.md#1-one-time-setup). If the engine is started by another Python (for example 3.15) it re-runs itself under the resolved 3.12 x64.

- CLI: Python 3.12+ and standard library only for initial parsing/detection.
- Actual project setup/build/test environments: **Python 3.12 x64**, matching the
  locked and validated toolchain. Newer Python can show help/plan/Quick but is not
  certified for packaging or dependency setup.
- Git; Node/npm when required. Node uses `frontend/package.json`'s compatible engine
  range (currently 24/25); npm 10/11. Package installs use existing Python requirement
  pins and `npm ci`, never arbitrary dependency upgrades.
- Windows x64: PowerShell 5.1 or 7; WebView2 for desktop runtime smoke checks.
  Service-manager compilation requires .NET Framework 4.8.
- Native Linux packaging: Linux x86-64 and Python 3.12/system libraries from the
  [native guide](deployment/LINUX_NATIVE.md). Linux native and Docker packaging are
  Python-only and do not require PowerShell. If `pwsh` happens to be installed, the
  shared validation also parses the Windows scripts; without it that one check is
  recorded as *not verified* in the local receipt (never as passed). Windows hosts and
  CI always run it. No Windows binary is built on Linux.
- Docker: a running Linux amd64 Docker engine and `docker compose`.

Detailed Windows installation, PATH, proxy/CA and tool checks live in
[Windows build toolchain](development/DEVELOPMENT.md#windows-build-toolchain).
Destination installations do not need Node or React compilation. Existing package
contents, service names, installation paths, binding/security and data storage stay
unchanged; see the [deployment guides](deployment/README.md).

### Prerequisite matrix

| Prerequisite | Needed for | What the build entry points do | Manual or administrator action |
| --- | --- | --- | --- |
| Python 3.12 x64 | build, test, package | Checked (version and 64-bit); `scripts/build.ps1` offers a per-user winget install only with consent | Install it yourself on other platforms |
| Project `.venv` / packaging env | test, build, package | Created if missing; reused if valid; a wrong-version, 32-bit or broken one is reported and **never deleted** | Remove or repair it yourself when told |
| pip | all Python setup | Seeded if missing; upgraded to the pinned release when older than 24.2 (see below) | None normally |
| Locked Python dependencies | test, build, package | Installed from the pinned requirement files only when something is missing or different; otherwise skipped | None |
| Node.js 24/25 and npm 10/11 | frontend, build, package | Checked only; per-user winget install on Windows with consent; **never replaces your global Node** | Install a supported version when missing |
| Locked frontend dependencies | frontend, build, package | `npm ci` only when `node_modules` is older than `package.json` or the lockfile | None |
| Git | release, packaging identity | Checked; per-user winget install with consent | Elsewhere install it yourself |
| Docker engine and Compose | Docker target | Checked only | Install and start it yourself |
| PowerShell 5.1 or 7 | Windows targets | Checked on Windows; not needed for Linux or Docker packaging | None on Windows |
| Inno Setup, .NET Framework 4.8, WebView2 | Windows installer, service manager, desktop smoke | Handled by the Windows packaging scripts; see the Windows guides | Administrator approval where policy requires |

Windows packaging accepts Windows PowerShell **5.1 or 7**. PowerShell 7 is optional:
checks that specifically require `pwsh` are reported as skipped when it is absent;
those skips do not prove PowerShell 7 compatibility. PowerShell 5.1 static contracts
remain enforced. A skipped symlink test on a host without link privileges likewise
does not relax the package's link protections.

Quick checks (`quick`) install nothing. `test` prepares only the project `.venv`; `build`/`package` prepare the packaging environment; `release` needs Git only. System-level installs (Python, Git, Node) always need explicit consent (`--install-system` or an interactive yes).

**pip and certificates.** Python 3.12 seeds new environments with pip 24.0, which trusts only its bundled certificates and fails with `CERTIFICATE_VERIFY_FAILED` where a corporate proxy's CA lives in the Windows certificate store. The engine therefore moves an old pip to the project's pinned release (`pip==` in `backend/requirements-build.txt`) before installing anything; if that first step fails certificate verification it retries **once** with pip's system-trust-store option (`--use-feature=truststore`), only for this bootstrap, because pip 24.2 and later use the system store by default. Verification is never disabled, `--trusted-host` is never used, and no certificate is added to the machine. If the system store does not contain the CA, ask IT to trust it there (or `pip config set global.cert <file>`) and rerun; repeated runs resume safely.

## Frontend dependencies, shared prerequisites and diagnostics

- **Node.js:** `frontend/package.json` `engines` (Node 24 or 25, npm 10 or 11) is enforced before any build starts, with an actionable message and no automatic
  Node installation. Node 24 LTS is the CI baseline and the recommended version; Node 25 is accepted, with a one-time note that it is not an LTS release.
- **How prerequisite detection works:** each tool (`git`, `node`, `npm`, `docker`) is resolved through `PATH`/`PATHEXT` (so Windows `npm.cmd` is found) and asked for its
  version with a 15 s timeout, no shell and no console input. Only a tool that is not on `PATH` is "missing". A tool that is found but cannot be started, exits with an
  error, times out or prints something that is not a version stops the build with a report naming the Python interpreter, the resolved executable, the exact command,
  the result (exit code, exception or stderr, secrets redacted) and a suggested action; SAP Lens never reinstalls a tool that exists. Set
  `SAP_LENS_BUILD_DIAGNOSTICS=1` to also print, for every probe, the status, resolved path, version, Python, working directory and `PATHEXT`. To troubleshoot, run the
  printed command in the same terminal.
- **Isolated frontend workspace:** the deployment builder (`-Mode build|package` for Windows, Linux native and Docker) never runs `npm ci` in your
  `frontend/node_modules`. It mirrors the needed sources into `backend/build/frontend-workspace` (a generated, ignored, cleanable path), installs from the
  committed `package-lock.json` there, runs type check, catalogue check, production build, audit and the browser smoke tests in the workspace, and publishes only
  the verified `dist` to `frontend/dist`. A running dev server, editor or scanner holding files in `frontend/node_modules` can no longer break a build. The
  installation is reused while `package.json`, `package-lock.json` and the Node major version are unchanged, so a repeated or second-target build does not reinstall.
- **Shared prerequisites run once per invocation:** `-Target all` validates and builds the shared frontend assets once; Desktop and Service reuse them. If shared
  validation fails, the remaining targets are recorded as `blocked` (not attempted) instead of repeating the suite or being reported as packaging failures.
- **Live build stages:** named `[build-stage] START`, `RUNNING`, `PASS` and `FAILED` messages show elapsed seconds and log locations. Long commands emit a heartbeat every 15 seconds. The public runner relays only authored stage markers from child logs; detailed command output remains in the log. Windows packaging names its desktop, package and server validation modules individually. Deployment manifests retain per-stage status, duration and exit code in `stages`; existing artifact identity and failure records are unchanged.
- **Failure reports:** every failed stage prints the stage, command, working directory, exit code, the real error and the last output lines, and names the detailed
  log (`dist/<version>-<commit12>/build.log`). Secrets (token variables, URL credentials, `_authToken`) are redacted. `build-manifest.json` carries the same facts per
  target (`failed_stage`, `failure_class`, `command`, `exit_code`, `error`, `hint`, `output_tail`, `log`), a top-level `shared_validation` record when shared validation
  failed, and `status: blocked` with `blocked_by: shared_validation` for targets that were not attempted. Failure classes: `dependency_install`, `python_environment`,
  `frontend_validation`, `frontend_build`, `browser_smoke`, `desktop_packaging`, `service_packaging`, `runtime_smoke`, `validation`.
- **Windows file locks** (`EPERM`, `EBUSY`, `EACCES`, WinError 5 or 32): the report names the affected file. Transient locks inside the isolated workspace are retried at
  most twice (3 s, then 8 s); permission errors are never retried. SAP Lens never stops other processes, disables antivirus or asks for administrator rights. To fix a
  persistent lock, close programs that use the repository (editors, dev servers, terminals in the folder) or exclude `backend/build` from real-time scanning where policy
  allows, then run the same command again; the build is safe to repeat.
- **Retry and targeted validation:** rerun the same command (`--skip-setup` reuses a still-valid validation receipt). Run only the build contract checks with
  `python -m unittest discover -s backend/tests -p test_build_diagnostics.py` and `-p test_local_deployments.py`. Build Desktop and Service together with
  `.\scripts\build.ps1 -Mode build -Platform windows -Target all`.
- **Windows paths:** the repository path may contain spaces. Very long checkout paths are rejected early with advice to use a shorter path or enable Windows long paths.

## First-time Windows setup

From an approved checkout, in x64 PowerShell:

```powershell
.\scripts\build.ps1
.\scripts\build.ps1 -Mode quick
.\scripts\build.ps1 -Mode package -Platform windows -Target installer
```

The bootstrapper can start **without Python installed**. It runs every candidate and
accepts only Python 3.12.x that is 64-bit, in this order: an existing project `.venv`,
the Python launcher (`py -3.12`), `python3.12`/`python` on PATH, then other registered
installations (`py -0p`, the Windows registry). Microsoft Store app execution aliases are
skipped. Nothing is printed on success (use `-Verbose` to see the selected interpreter);
when no candidate is accepted it lists each one with the reason (version, architecture or
failed probe). Only then, interactive execution offers the official `Python.Python.3.12` winget package with
an explicit confirmation. It requests per-user/x64 installation, verifies the
result, and never silently falls back to a machine-wide/elevated installer.

For explicit unattended consent use `-InstallSystem -NonInteractive`. Ordinary
non-interactive/CI runs do not install system software and never prompt. Missing
winget, policy restrictions, unsupported per-user packages or stale PATH produce
manual remediation guidance. Git/Node setup similarly requires consent; Node's
winget version is selected from the supported 24 line rather than an unrelated
latest major. Docker/system services need approved manual setup.

### Corporate policy restrictions

No entry point changes execution policy or downloads/runs unchecked installers.
AllSigned/Restricted/AppLocker/WDAC environments may block the bootstrapper **before
it starts**. Obtain IT approval/signing for the reviewed root and internal scripts,
or use an approved Python interpreter for the CLI; Python does not bypass policy
on internal PowerShell packaging scripts. Do not weaken organization controls.
No system software is installed by the automated tests.

## Commands

Windows:

```powershell
.\scripts\build.ps1 -Mode quick
.\scripts\build.ps1 -Mode build -Platform windows -Target desktop
.\scripts\build.ps1 -Mode package -Platform windows -Target installer
.\scripts\build.ps1 -Mode package -Platform windows -Target service
.\scripts\build.ps1 -Mode test -Scope targeted -Area deployment
.\scripts\build.ps1 -Mode test -Scope full -NonInteractive
```

Linux / direct Python:

```sh
python3.12 scripts/build.py
python3.12 scripts/build.py quick
python3.12 scripts/build.py package --platform linux --target server
python3.12 scripts/build.py package --platform docker --target server
python3.12 scripts/build.py test --scope targeted --area deployment --skip-setup --non-interactive
python3.12 scripts/build.py test --scope full --non-interactive
```

Interactive terminals prompt only for missing required values. With no mode, the
menu defaults to Quick; an empty answer accepts the displayed default. Mode,
platform, target and scope input are case-insensitive. Complete arguments execute
directly. Non-interactive execution defaults to Quick/current host and never reads
stdin. GitHub Actions is always treated as non-interactive.

## Modes

| Mode | Behavior |
| --- | --- |
| `quick` | Offline/read-only source/version/manifests, docs, ownership and whitespace checks; no installs, builds or regression by default |
| `test` | Existing isolated validation runner; targeted deployment area by default; `--area` selects another existing area |
| `build` | Compile/package the selected application through canonical platform adapters |
| `package` | Produce verified distributable archives through the same adapters; `--skip-setup` requires fresh validated inputs, never an unchecked skip |
| `release` | Verify validated deployment artifacts from `--output`, branch/source/version and workflow contracts; no tag or publication |
| `clean` | Only allowlisted generated directories, with `--confirm-clean`; refuses active locks, links, arbitrary output paths and the running interpreter |

Full regression is opt-in **test mode only**, not a build/publication prerequisite.
`--dry-run` prints the commands without setup, installs, logs, deletion or build
execution. Platform restrictions still apply; there is no cross-compiler.
`--verbose` displays captured tool output. Local runs store structured events and
per-operation logs under ignored `backend/build/unified/<run-id>/`. CI preserves
native step output and existing timing/summary artifacts.

## Targets

| Platform | Targets | Canonical result |
| --- | --- | --- |
| `windows` | `desktop` | Existing portable EXE/ZIP, PE/privacy/checksum and native EXE smoke verification |
| `windows` | `installer` | Existing current-user Inno Setup deployment archive; no service requirement |
| `windows` | `server` / `service` | Same headless runtime + verified WinSW + service manager package |
| `windows` | `all` | Installer/desktop payload plus service, sharing validated inputs |
| `linux` | `server` / `service` / `all` | Native x86-64 server package with systemd installer and pinned wheelhouse |
| `docker` | `server` / `all` | Existing amd64 image archive + Compose deployment; never a registry push |
| `all` | `all` | Existing four deployment archives using explicit trusted remote builders where required |

There is no Linux desktop GUI or Linux installer executable. Unsupported
combinations fail before packaging. Windows Portable Desktop needs Windows;
remote Windows builds use the installer target. Desktop stays `--windowed`;
the separate headless service host retains console shutdown semantics.

## Setup and repair

```sh
python3.12 scripts/build.py --setup-only --non-interactive
python3.12 scripts/build.py test --setup --area deployment
python3.12 scripts/build.py quick --skip-setup --non-interactive
```

Setup creates/reuses project `.venv`, ensures pip, installs pinned development
requirements and uses `npm ci`. Packaging environment preparation remains owned
by the canonical platform adapter under `backend/build/python-env`; explicit
setup-only in build/package mode prepares that environment. No global pip
installation is used. Incompatible/incomplete environments fail with repair
instructions rather than deleting user files. `--setup` explicitly repairs local
dependencies; `--skip-setup` forbids bootstrap and fails if required inputs are
missing. Reusing compiled inputs additionally requires their existing fresh,
source/tool/version-bound receipt. System tools still need separate explicit
consent (`--install-system` or an interactive Yes).

## Output layout

All distributable output is written under the repository-root `dist/`, which Git ignores completely (`/dist/`) and the Docker allowlist context never includes; temporary work and logs stay in `backend/build`, `frontend/dist` and `build/`. `scripts/build_system/layout.py` is the single description used by the clean command and the layout tests:

| Directory | Holds |
| --- | --- |
| `dist/local/` | Portable Windows desktop builds, run records and receipts |
| `dist/deployment/` | Verified deployment archives and checksums: Windows desktop and service, Linux native, Docker image archive |
| `dist/server/` | Windows service distributions |
| `dist/<version>-<commit12>/` | Per-version output of the cross-platform builder, with its manifest and `SHA256SUMS.txt` |
| `dist/publication/` | Same-run artifacts collected by the guarded release job (never written locally) |

Docker images stay in Docker; only exported archives and metadata land in `dist/`. The package folders were not split further by platform because the GitHub upload contracts, release collection and verification read these exact paths; the platform is part of each package name. `clean` removes only the generated locations above plus `backend/build`, `backend/dist` and `frontend/dist`, refuses symbolic links and Windows junctions anywhere on the path, requires `--confirm-clean`, and never touches sources, user data or databases.

## Outputs and versioning

`backend/resources/product-version.json` remains authoritative through
`backend/version.py`. `--version` is an intentional test override, never a version
bump. Existing dotted prereleases and legacy portable beta-hyphen overrides remain
supported; deployment archives retain their established SemVer requirements.

Deployment archives default to `dist/<version>-<commit12>/`; `--output` can select another
verified managed/ignored or external output directory. Portable Windows exports
retain `dist/local/packages/<local-version>/<run-id>/`; a portable output override
must remain under `dist/local/`. No output is silently overwritten. Each successful
command prints its canonical manifest/artifact location and log directory.

| Target | Existing archive name |
| --- | --- |
| Windows installer | `sap-lens-win-desktop-x64-v<version>.zip` |
| Windows service | `sap-lens-win-service-x64-v<version>.zip` |
| Linux native | `sap-lens-linux-native-x64-v<version>.tar.gz` |
| Docker | `sap-lens-linux-docker-amd64-v<version>.tar.gz` |
| Portable Windows | `SAP-Lens-Windows-x64-<version>+local.<sha>.zip` |

Installer payload: `SAP-Lens-Windows-Desktop-x64-<version>-Setup.exe`. Existing
checksums, exact contents, same-source identity and extraction/native verification
are retained. Release attachment policy is unchanged: no duplicate loose SHA256
release assets. Partial/failed output is not success; consult the operation exit
code and manifest rather than selecting an old executable.

## Remote builders

Use `--windows-host/--windows-repository` or `--linux-host/--linux-repository`
for an explicitly configured trusted SSH builder with a clean checkout of the
exact same commit. Existing strict host-key checking, source matching, nonce and
artifact/hash verification are retained. Hosts/keys are administrator setup, not
auto-installed or inferred by SAP Lens.

## Release preparation and CI

```sh
python3.12 scripts/build.py release --platform linux --target server --output dist/<version>-<commit12> --non-interactive
```

Prereleases prepare from `work`; stable preparation is rejected unless on `main`.
Artifacts must match the selected version, source and targets. No tags/releases
are created locally. Actual publishing still requires the existing manual workflow
and all selected packages to pass, with source/branch/tag/collision protections.
See [release policy](deployment/RELEASES.md).

Existing Actions now invoke this engine explicitly without prompting, for example:

```yaml
- name: Package Windows service
  run: python scripts/build.py package --ci-tool windows-package --non-interactive -- -Target Service
```

`--ci-tool` is a CI-only adapter boundary, not a local bypass. Setup actions and
same-run attestations remain authoritative; ordinary local setup cannot mint CI
receipts. Fast/Full timing runners and platform/release adapters reuse the existing
helpers through this entry point. Permissions, job independence, setup actions,
version allocation and artifact names are unchanged. No workflow is dispatched by
this guide. Full remains manual and is not a release prerequisite.

## Cleanup and internal scripts

```sh
python3.12 scripts/build.py clean --dry-run --non-interactive
python3.12 scripts/build.py clean --confirm-clean --non-interactive
```

Only `backend/build`, `backend/dist`, `frontend/dist`, `dist/local` and
`dist/deployment` are allowlisted. `.venv`, installations, configuration, snapshots
and user data are preserved. Active build/cleanup locks block deletion. Stale
locks require ownership review; clean never breaks an active owner's lock.

The duplicate root Bash wrapper was removed after migrating its active caller.
Use Python directly on Linux. Specialized internal Windows/local/deployment,
installer, validation, runtime and release helpers remain because the engine or
CI adapters actually call them. They are not alternative documented build front
doors. The old deployment build-guide URL is a navigation stub for existing links,
not a competing set of instructions.

## Exit codes and troubleshooting

- `0`: completed operation (or dry-run/help); `2`: arguments/configuration/unsupported
  combination; `3`: missing/incompatible prerequisite, denied setup or lock ownership.
- Child tool failures retain their exit code; timeout is `124`. Nonzero always means
  failure. Logs identify the operation and captured diagnostics.
- Missing Python: read the `Python discovery:` list the bootstrapper prints for every rejected candidate. If none is
  listed, use approved Python 3.12 x64/winget and reopen PowerShell. An existing `.venv` that is not 3.12 x64 is reported
  and left untouched; remove or repair it yourself.
- Missing/incompatible Node: install the project-supported version; do not install
  an unrelated latest major. A failed per-user winget install has no admin fallback.
- Missing Docker/Compose: use approved manual platform setup. PowerShell is needed only for Windows targets.
- Stale receipt: rebuild without `--skip-setup`, on the exact clean commit.
- TLS/proxy or audit failure: use approved trust settings and resolve the advisory;
  never disable verification or ignore audits to finish packaging.
- Corporate policy blocks a script: obtain signing/IT approval, not a policy bypass.

## Packaging versus native service (SCM) acceptance

`-Mode package` builds and verifies the Desktop and Service artifacts **without installing or changing any Windows service** and needs no administrator rights. The privileged acceptance, `scripts\test-server-service.ps1`, installs, starts, stops, backs up, restores and uninstalls a real `SAPLens` service and is a separate step:

| Step | Command (Windows PowerShell 5.1) | Rights |
|---|---|---|
| Package and verify | `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build.ps1 -Mode package -Platform windows -Target all -Output ".\backend\build\windows-$(Get-Date -Format 'yyyyMMdd-HHmmss')" -NonInteractive` | normal user |
| Package with acceptance in one run | the same command plus `-NativeAcceptance` | elevated (checked before the build starts, exit 3) |
| Acceptance only, on a built bundle | `powershell -NoProfile -File .\scripts\test-server-service.ps1 -Bundle .\backend\build\deployment-service-<id>` | elevated |

The build manifest keeps three facts apart per target: `built`, `package_verified` and `native_acceptance` (`kind: windows-scm`, `status: passed | not_run | blocked | not_applicable`). A service package without acceptance is a valid package with `native_acceptance.status = not_run` and `runtime_smoke_tested = false`; release verification (`--verify-output`) requires the acceptance to have passed. Missing elevation is reported as `ACCEPTANCE PREREQUISITE` (failure class `acceptance_prerequisite`, target status `blocked`), never as a packaging failure. The CI runner (`GITHUB_ACTIONS=true`, elevated) still runs the acceptance. The existing safeguards (an existing `SAPLens` service is never touched, uninstall in `finally`) are unchanged.

## Windows build stabilization notes

- **Public parameter mapping:** `-Output <dir>` (alias `-OutputDir`) maps to `--output` of `build.py` and `--output-dir` of the deployment builder. An explicit directory is honored by filesystem identity; Windows long-name and 8.3 aliases resolve to the same directory. Symlinks and reparse points are rejected before canonicalization. If it holds a build of another version or commit, the build stops and prints the path, the existing manifest version/commit, the requested ones and a suggested new directory; nothing is overwritten or deleted. Use a timestamped directory for routine runs: `-Output ".\backend\build\windows-$(Get-Date -Format 'yyyyMMdd-HHmmss')"`.
- **Python discovery:** `build.ps1` resolves the repository root from its own location (`Get-RepositoryRoot`, validated by the presence of `scripts\build.py`); functions never depend on an implicit `$PSScriptRoot`. Python 3.12 x64 is required; others are listed with the reason for rejection.
- **Clean order:** confirmation, allowlisted target, no linked directory, then protection of the running interpreter. Each is tested separately.
- **Managed tools:** actionlint and the Inno Setup bootstrap use the shared verified acquisition engine. Repository lint tooling is resolved before expensive build validation; see [centralized prerequisites](#centralized-prerequisites-and-restricted-networks). A corporate 403 is still a prerequisite failure, never a lint pass.
- **Prerequisites:** Windows PowerShell 5.1 (PowerShell 7 optional), Python 3.12 x64, Node.js 24 LTS recommended (25 accepted with a note), npm 10/11. Python and frontend dependencies are installed into isolated project environments automatically; Git, Node.js and Python are never installed without consent. Certificate problems must be fixed in the operating system trust store.
- **Failure classes:** `prerequisite` (tool missing/unobtainable), `validation`, `dependency_install`, `*_packaging`. A target not attempted because shared validation failed is `blocked`, with the underlying error, log path and recovery hint, and is not a packaging failure.
- **Test skips:** PowerShell-dependent tests run on Windows PowerShell 5.1 or PowerShell 7; they skip only when no PowerShell exists. Other skips are POSIX-only behavior (permission bits, signals, process groups, `/proc`) or optional build dependencies (PyInstaller, pefile, openssl).

## Validation status

CLI/routing/consent/error/cleanup behavior and package/workflow contracts are tested
with isolated synthetic fixtures and mocked system installers. Python Quick is
executed locally. Real Windows bootstrap, winget, PowerShell 5.1/7 execution,
PyInstaller/Inno/.NET compilation, WebView2/SCM and current-source platform packages
remain unexecuted on this Linux host. No full application regression is claimed.
See the [workflow validation matrix](validation/WORKFLOW_MATRIX.md) and the
[platform acceptance matrix](deployment/README.md#validation-status).

## Script inventory

Every tracked file under `scripts/` is classified here and in [scripts/README.md](../scripts/README.md) by purpose, callers (workflows, tests, documentation) and overlap with the Python engine.
Result of the audit: no script is redundant. Every file has a live caller or a documented role, and the apparent overlaps are layered
(a public wrapper over an internal worker) rather than duplicated. Public entrypoints are `scripts/build.ps1` and `scripts/build.py`; everything
else is an internal helper and is not a supported entrypoint.

| Group | Files | Disposition | Purpose |
| --- | --- | --- | --- |
| Public entrypoints | build.ps1, build.py, build_system/* | KEEP | Windows bootstrapper and the shared Python engine (CLI, prerequisites, runner, targets) |
| Orchestrators | deployment/build-deployments.py | KEEP | Deployment builder: shared validation, Windows/Linux/Docker packages, remote builders; called by the engine and workflows |
| Orchestrators | packaging/local-build.py, build-local.ps1 | KEEP | Portable Windows desktop local build (receipt, ZIP verification); called by the engine |
| Orchestrators | build-windows.ps1, packaging/release-windows.py, packaging/write-build-report.py | KEEP | Legacy Windows desktop workflow stages, version reservation/release gate and run report (build-windows.yml) |
| Orchestrators | package-windows-deployment.ps1 | KEEP | Windows desktop/service packaging steps shared by local and CI builds |
| Windows helpers | build-desktop-installer.ps1, build-server-windows.ps1, build-service-manager.ps1, manage-server-service.ps1 | KEEP | Inno installer, service bundle, service-manager compile and the shipped service management script (need Windows/.NET) |
| Windows tests | test-windows-exe.ps1, test-desktop-installer.ps1, test-server-service.ps1 | KEEP | Native EXE, installer and service smoke tests run by the packaging scripts |
| Windows tests | testing/windows-scm-test-helpers.ps1 | KEEP | Internal SCM acceptance helpers: isolated marked workspaces, secure ZIP inspection and ownership-scoped protected cleanup; no production service behavior |
| Windows tests | test-service-management.ps1 | KEEP | Portable service-helper regression test (state transitions, configuration reading, secret-repair guards); executed by check-powershell.ps1, so it runs wherever that check runs, including PowerShell 7 on Linux (`backend/tests/test_powershell.py`). No SCM operation is executed |
| Linux/Docker | deployment-package.py, install-linux-server.py, run-installed-server.py, testing/test-native-deployment.py | KEEP | Native Linux archive, installer, runtime launcher and offline install smoke test (Python only) |
| Linux/Docker | deployment/package-docker.py, testing/test-docker-deployment.py, testing/test-docker-lifecycle.py | KEEP | Docker image archive and its runtime/persistence smoke tests |
| Release | deployment/deployment-release.py, deployment/check-deployment-download.py | KEEP | Plan/preflight/publish gates and downloaded-artifact check for the deployment workflow |
| Verification | packaging/verify-windows-package.py, packaging/verify-server-bundle.py, packaging/verify-desktop-installer.py, packaging/verify-desktop-distribution.py, packaging/verify-artifact-zip.py, packaging/write-windows-metadata.py | KEEP | Package, bundle, installer and ZIP verifiers; version/PE metadata generation |
| Validation | validate.py, run-tests.py, test-map.json, testing/ci.py, check-workflows.py, check-docs.py, check-powershell.ps1, check-powershell-compat.ps1 | KEEP | Validation levels (documented in AGENTS.md), test profiles and ownership, CI step runner/summary, workflow contracts, documentation links, PowerShell parse check |
| Validation | testing/serve-browser-tests.py, sync-lucide-catalog.mjs, frontend-licenses.mjs, product-version.mjs, requirements-audit.txt | KEEP | Browser test server, icon catalogue check, license and version generators, audit tooling pins |
| Test fixtures | testing/desktop_test_mutex.py | KEEP | Test-only Windows desktop mutex isolation shared by backend fixtures and browser-test subprocesses; production locks remain unchanged |
| Test fixtures | testing/synthetic-backup.py | KEEP | Generates disposable synthetic backup archives for browser tests using isolated temporary storage and a unique test mutex |
| Development | maintenance/validation_tracker.py, maintenance/generate-examples.py, maintenance/reference-template.py, benchmarks/profile-sod.py, benchmarks/data_benchmark.py | KEEP | Tracker tooling, deterministic example generator, SoD profiling and reference template; separate from the build engine by design |

Remaining debt: the legacy `build-windows.ps1` stage engine and the deployment
builder still own sequencing that could later move into Python, which needs real Windows parity testing first.

## Python ports of the Windows build scripts and their validation checklist

The six PowerShell build scripts are being moved into `scripts/build_system/windows/`. Each port keeps the PowerShell original as the default until the checklist below
has been run on a Windows host; a port is selected only by an explicit opt-in. **None of the ports has been executed on Windows.** Linux tests (`backend/tests/test_windows_stages.py`)
check the generated commands, their order, option names, log markers, timing records and exit codes against the PowerShell source; they cannot show that PyInstaller, npm or the Windows tools accept them.

| PowerShell original | Python port | Opt-in |
| --- | --- | --- |
| `build-windows.ps1` | `scripts/build_system/windows/stages.py` | `SAP_LENS_WINDOWS_STAGES=python` (the `windows-stage` adapter) or run the file directly with the same `-Stage`, `-ArtifactDirectory`, ... options |
| `build-service-manager.ps1` | `scripts/build_system/windows/service_manager.py` | called by `server.py`; direct: `python scripts/build_system/windows/service_manager.py -OutputDirectory DIR` |
| `build-server-windows.ps1` | `scripts/build_system/windows/server.py` | direct: `-WinSW`, `-Version`, `-ValidatedDeployment`, `-OutputDirectory` |
| `build-desktop-installer.ps1` | `scripts/build_system/windows/installer.py` | `SAP_LENS_WINDOWS_PACKAGING=python` (the `installer-check` adapter) or direct: `-OutputDirectory`, `-CompileCheck` |
| `package-windows-deployment.ps1` | `scripts/build_system/windows/packaging.py` | `SAP_LENS_WINDOWS_PACKAGING=python` (the `windows-package` adapter) or direct: `-Target Desktop\|Service`, `-OutputDirectory` |
| `build-local.ps1` | `scripts/build_system/windows/local.py` | `SAP_LENS_WINDOWS_PACKAGING=python` (the local `build --platform windows --target desktop` route) or direct: `-Mode Build\|Quick\|Validate\|Package`, `-Version`, `-IncludeService`, `-OutputDirectory` |

The packaging ports call the Python stage port and the same native PowerShell tests (`test-desktop-installer.ps1`, `test-server-service.ps1`, `test-windows-exe.ps1`), which stay PowerShell.

### Windows validation checklist: `build-windows.ps1` against `stages.py`

Requirements: Windows x64, 64-bit Python 3.12 (`python --version`), Node 24 or 25, Git. Run in a clean checkout of `work` from the repository root, in PowerShell. The first block records the PowerShell
reference, the second the port; compare the listed evidence.

```powershell
# 0. Reference run with the PowerShell stages (expected to pass)
$py = (Get-Command python).Source
foreach ($s in 'Environment','Frontend','Python') { pwsh -NoProfile -File scripts\build-windows.ps1 -Stage $s -PythonExecutable $py; if ($LASTEXITCODE) { throw "PS $s" } }
pwsh -NoProfile -File scripts\build-windows.ps1 -Stage Backend -TargetedValidation -PythonExecutable $py
pwsh -NoProfile -File scripts\build-windows.ps1 -Stage Package -PythonExecutable $py
pwsh -NoProfile -File scripts\build-windows.ps1 -Stage Verify -PythonExecutable $py
Copy-Item backend\build\timings.jsonl "$env:TEMP\ps-timings.jsonl"; Copy-Item backend\dist\SAP-Lens.exe.sha256 "$env:TEMP\ps.sha256"
Copy-Item backend\build\package-verification.json "$env:TEMP\ps-verification.json"

# 1. The same stages with the Python port (clean the outputs first: python scripts\build.py clean --confirm-clean)
foreach ($s in 'Environment','Frontend','Python') { python scripts\build_system\windows\stages.py -Stage $s -PythonExecutable $py; if ($LASTEXITCODE) { throw "PY $s" } }
python scripts\build_system\windows\stages.py -Stage Backend -TargetedValidation -PythonExecutable $py
python scripts\build_system\windows\stages.py -Stage Package -PythonExecutable $py
python scripts\build_system\windows\stages.py -Stage Verify -PythonExecutable $py
python scripts\build_system\windows\stages.py -Stage Smoke        # starts the packaged EXE through scripts\test-windows-exe.ps1

# 2. Failure propagation: a missing stage input must fail with exit code 1
python scripts\build_system\windows\stages.py -Stage Artifact; "exit code: $LASTEXITCODE"      # expected: 1 and the message "needs a downloaded artifact directory"
```

Evidence to compare:

1. Every command above exits 0; step 2 exits 1.
2. `backend\build\timings.jsonl`: same `stage` names in the same order for both runs (seconds differ).
3. `backend\build\package-verification.json`: same fields; `exe_sha256` need not be equal (PyInstaller output is not reproducible byte for byte) but `verify-windows-package.py` must pass in both runs.
4. `backend\dist\SAP-Lens.exe.sha256`: same format, `<64 hex>  SAP-Lens.exe` followed by CRLF (compare with `Format-Hex`).
5. The EXE built by the port starts: `Smoke` passes.
6. Remaining stages (`Audit`, `JavaScriptAudit`, `Browser`, `Artifact` with a downloaded workflow artifact) are checked the same way before the original is removed.

Report any difference; the original `build-windows.ps1` is removed only after every item matches.

### Windows validation checklist: packaging ports

Run after the stage checklist passes, on the same host (needs .NET Framework 4.8 for the service manager, network access to download the pinned Inno Setup and WinSW, and an
unregistered machine for the native installer and service tests: they refuse to touch an existing SAP Lens installation or `SAPLens` service).

```powershell
# Reference (PowerShell) first, then the port; compare the bundle contents and exit codes.
pwsh -NoProfile -File scripts\build-desktop-installer.ps1 -CompileCheck -OutputDirectory $env:TEMP\ps-iscc
python scripts\build_system\windows\installer.py -CompileCheck -OutputDirectory $env:TEMP\py-iscc        # both: four channels compile and verify

pwsh -NoProfile -File scripts\build-service-manager.ps1 -OutputDirectory $env:TEMP\ps-mgr                   # needs backend\build\build-version.json (after a Package stage)
python scripts\build_system\windows\service_manager.py -OutputDirectory $env:TEMP\py-mgr                  # both: exe produced, self-test passes

pwsh -NoProfile -File scripts\package-windows-deployment.ps1 -Target Service -OutputDirectory $env:TEMP\ps-dist
python scripts\build_system\windows\packaging.py -Target Service -OutputDirectory $env:TEMP\py-dist
pwsh -NoProfile -File scripts\package-windows-deployment.ps1 -Target Desktop -OutputDirectory $env:TEMP\ps-dist-desktop
python scripts\build_system\windows\packaging.py -Target Desktop -OutputDirectory $env:TEMP\py-dist-desktop
```

Local pipeline port (`local.py`): run `pwsh -NoProfile -File scripts\\build-local.ps1 -Mode Quick` and `python scripts\\build_system\\windows\\local.py -Mode Quick`, then `-Mode Build -Version <x>` for both
(on separate clean checkouts). Compare: exit codes, `dist\\local\\runs\\<run>\\summary.json` (same stage names and order, same fields), `build.log` contents, the verified artifact directory, and that
a second concurrent run of the port fails with "Another local build is running" while the first holds `backend\\build\\local-build.lock` and that `python scripts\\build.py clean --confirm-clean` refuses during a
build (the port holds the lock through `CreateFileW` with share mode 0, the original used `FileShare.None`: confirm the clean probe sees it).

Compare per target: exit code 0; the same file names, sizes (except compiled binaries) and `manifest` entries in the two `dist` folders; `README.md` byte-for-byte (the port writes UTF-8 without BOM and no trailing newline);
the Desktop installer's `SAP-Lens-Windows-Desktop-x64-<version>-Setup.exe.sha256` removal (compiler checksums are internal); `verification-report.json` of the service bundle with `native_service_smoke` set; and
that the native tests (`test-desktop-installer.ps1`, `test-server-service.ps1`) pass against the port's output. Clean up with `python scripts\build.py clean --confirm-clean` between runs. Note
`build-server-windows.ps1` and its port create `dist\server\<version>` and refuse an existing directory, so pass `-OutputDirectory`.

## Manual build

Open Actions → **Build Deployment Packages** → Run workflow, select the intended
branch (normally `work`), then choose one **`build_target`** (a single dropdown; every
choice is valid):

| `build_target` | Builds |
| --- | --- |
| `all` (default) | All platforms, all four packages |
| `windows-all` | Both Windows packages: Windows Desktop and Windows Server Service |
| `windows-desktop` | Windows Desktop only |
| `windows-service` | Windows Server Service only |
| `linux-all` | Both Linux packages: Linux Docker and Linux Native/systemd |
| `linux-docker` | Linux Docker only |
| `linux-native` | Linux Native/systemd only |

The first job, **Resolve Build Selection** (about a minute, no dependencies installed),
resolves the choice once and exposes the selected packages. An unknown value (possible
only through a manual API dispatch) fails there with a message listing the valid values,
before shared validation or any packaging runner starts. Unselected packages are skipped
jobs: no Windows runner starts for a Linux target and no Linux packaging runner for a
Windows target. The job summary shows the selected target, the resolved packages, every
package as selected or skipped, the version and channel, and whether publication is
enabled. Artifact names and the per-package jobs are unchanged.

Leave base `version` empty to use the source product version, choose a `release_channel`, and use
`prerelease_number=auto` to derive the next sequence from tags and release metadata. Publication is controlled separately by
`publish_release`, **false by default**. All selected artifacts embed the same
resolved version, source commit and workflow run/attempt.

| Channel | Example |
| --- | --- |
| Alpha | `1.0.0-alpha.1` |
| Beta | `1.0.0-beta.1` |
| Release Candidate (RC) | `1.0.0-rc.1` |
| Stable / Production | `1.0.0` |

Base components and prerelease numbers are limited to 65535 for Windows PE
compatibility. Leading zeros, suffixes in the base, invalid channels and malformed
numbers are rejected. Stable ignores a valid supplied sequence; leaving it blank
is supported. Automatic numbering counts both legacy `beta-N` and SemVer `beta.N` tags (including drafts). Published identities are never renamed or reused. Explicit publication numbers must equal the next available sequence.

With `publish_release=false`, only Actions artifacts are created: **no tag or
GitHub Release**, even for a Stable version. An embedded version/tag name is
candidate metadata, not proof of publication. No binary signing or registry push
is enabled. Existing **Build Windows Application** retains its independent,
legacy desktop build/beta/stable release behavior unchanged.

With `publish_release=true`, every selected package must finish its native
packaging and artifact roundtrip successfully. Only then can the isolated,
write-scoped publisher collect those exact same-run artifact IDs, verify their
names/checksums against successful job outputs, stage a draft, verify every
uploaded release asset's server-side SHA-256, create an owned annotated version
tag and publish. Alpha/Beta/RC are prereleases; Stable is a normal/latest release.
All selected packages, checksum sidecars and a source/digest manifest are attached.
A failed, skipped or cancelled selected package prevents publication. Packages that
were not selected are skipped by design: they never block publication, and they are
never collected. The publisher takes the package list from the planning job, checks it
against a fresh resolution of the same build target, and refuses to publish if an unselected
package ran. Only same-run artifact IDs of selected, verified packages are downloaded;
nothing is reused from earlier runs. Build-only runs still upload successful
independent packages when a sibling fails.

Publication asks GitHub to generate release notes from repository history, keeping
the validated-package/source explanation as the prefix. Authorized maintainers can
review/edit the published notes using GitHub's Release editor. The workflow does
not pause its private draft for manual editing; use existing environment approval
before publication. Build-only mode creates neither a draft nor release notes.
GitHub Releases remains the release-history record; no CHANGELOG.md is used.

### Examples after workflow registration

For test packages: select build target `all`, source base (empty input), `Beta`, sequence `auto`, and leave
**Publish release unchecked**. Download each successful job's Actions artifact.

For a Beta release: select the desired build target, source base (empty input), `Beta`, sequence `auto`, and explicitly check **Publish release**.

For Stable: first promote reviewed changes and stable product metadata to `main` through a PR; select that main commit, the desired target (normally `all`), source base (empty input),
`Stable / Production`, and explicitly check **Publish release**. Existing
`sap-lens-stable` environment protection applies; prereleases use `sap-lens-beta`.
No repository/environment settings are modified by these source changes.

The CLI equivalent for a build-only run, **after the workflow is registered**:

```bash
gh workflow run build-deployments.yml --repo OnlyDrey/sap-lens --ref work \
  -f build_target=all -f version=1.0.0 -f release_channel=Beta \
  -f prerelease_number=1 -f publish_release=false
```

Do not run publication commands without approval. Actions artifacts have the
configured retention period and an outer GitHub ZIP wrapper; release assets are
the actual deployment archives/sidecars and remain attached until explicitly
removed. This implementation does not publish anything during local development.

### Failure and concurrency safety

A read-only preflight rejects existing tags/releases before shared validation;
the publisher checks again after all packages pass. Existing refs/releases are
never overwritten, adopted or force-updated. Draft assets are uploaded before
tag creation. Publication is serialized independently across branches. A normal
failure removes only this invocation's draft and its provably owned annotated
tag; foreign tags and published releases are never removed. A lost successful
publish response is reconciled once without retrying publication.

GitHub does not offer a transaction spanning all release/tag calls. If remote
state cannot be read during recovery, cleanup stops and reports manual
reconciliation rather than guessing or deleting uncertain state. Inspect the
release, owned tag and run summary before a new dispatch. Do not blindly retry a
failed version or delete a pre-existing reservation. Mocks validate this policy;
live GitHub publication/rollback has not been exercised in this task.

This workflow is registered on the default branch as well as `work` (registration
was verified on 25 October 2026). No merge or default-branch change is needed merely
to select `work`. The GitHub form may reflect the default branch's older inputs;
CLI/API dispatch with an explicit `ref` selects the intended branch definition.
Always inspect its inputs and use the matching source version. No dispatch is
performed automatically by these instructions.

Shared validation runs once per dispatch: backend/browser regressions, types,
production frontend, audits, workflow/PowerShell checks. Its frontend and identity
are sealed with hashes, source SHA, run/attempt and successful stage records.
Platform jobs accept only this same-run/attempt attestation. If GitHub reruns only
failed platform jobs under a new attempt, the prior attestation is deliberately
not accepted; an approved full rerun must regenerate shared validation. Each needs only shared
validation, so one platform failure cannot cancel or block another platform's
upload. A shared validation failure appropriately prevents all packaging.

## Outputs

Actions artifact names use the same stem as their inner archive:

| Platform | Inner deployment file |
| --- | --- |
| Windows Desktop | `sap-lens-win-desktop-x64-v<version>.zip` |
| Windows Service | `sap-lens-win-service-x64-v<version>.zip` |
| Linux Docker | `sap-lens-linux-docker-amd64-v<version>.tar.gz` |
| Linux native/client | `sap-lens-linux-native-x64-v<version>.tar.gz` |

After the selected job and roundtrip succeed, open the completed Actions run's
**Artifacts** section and download the selected platform stem. Alternatively, use
`gh run download <run-id> --repo OnlyDrey/sap-lens --name <artifact-name>` for an
authorized run. Downloading is not a build or publication action.

Every artifact contains its archive plus `<archive>.sha256`, retained for 14 days.
Published releases contain only the selected archives and `sap-lens-manifest.json`;
individual sidecars remain internal verification inputs. GitHub displays the SHA-256
digest for each uploaded asset, and the manifest records source identity and archive
sizes/digests. No separate checksum list is uploaded. Existing releases are not changed.
To verify a download, compare `sha256sum <archive>` on Linux or
`Get-FileHash <archive> -Algorithm SHA256` on Windows with the digest shown by GitHub
or recorded for that archive in `sap-lens-manifest.json`.

For Actions downloads, GitHub wraps these files in another downloadable ZIP: extract that wrapper first.
The workflow downloads each upload again, checks its digest, inner checksum,
exact expected members and hashes. Desktop additionally uses its existing EXE/ZIP
verifiers; Service includes its PE/resource report and native SCM smoke result.

The desktop deployment ZIP now wraps the unchanged portable EXE/checksum with a
per-user Setup executable/checksum, license notices, installation guide, exact
manifest and native installer receipt. Its portable verifier still enforces its
exactly-two-file ZIP contract. See [desktop installation](deployment/WINDOWS_DESKTOP.md).
This installer definition has not been compiled or accepted on Windows in the
Linux development environment. The separate legacy Windows release artifact
remains the portable pair; it is not silently changed into an installer release.

Docker packages include an offline image, Compose configuration and the
[managed lifecycle entry point](deployment/LINUX_DOCKER.md). Native packages
include their installer and offline wheelhouse. No target needs Node.js or React
compilation; native Linux explicitly requires Python 3.12 and venv support.

Server archives contain `package-manifest.json` with per-file hashes and build
identity. Windows Service includes pinned WinSW and its MIT license. Native
includes a hash-locked wheelhouse with dependency licenses; frontend production
license notices are included in compiled assets for all platforms. SAP Lens is proprietary under [LICENSE.md](../LICENSE.md); third-party
notices do not grant rights to redistribute the application.

Only production application inputs and explicit deployment files are packaged.
CSV exports, snapshots, settings, secrets, test results, virtualenvs and Git history
are excluded. Target configuration is generated at install time; it must not be
prepopulated with an organization's data or access secrets.




## Centralized prerequisites and restricted networks

The public interfaces remain `scripts/build.ps1` and `scripts/build.py`.
`build_system/prerequisites.py`, `python_env.py` and `doctor.py` detect compatible
host tools and prepare pinned local environments. `build_system/managed_tools.py`
is the common acquisition engine used by Repository lint, deployment validation
and both Windows installer helpers. No host Python or Node installation is
silently installed, upgraded or replaced.

| Tool | Approved version/source | Acquisition / scope |
| --- | --- | --- |
| Python | 3.12 x64 for builds | Existing discovery; approved manual/explicit opt-in system setup; local venvs |
| Node.js / npm | Node 24 LTS recommended (25 accepted), npm 10–11 | Existing detection; no automatic replacement; frontend lockfile via `npm ci` |
| PyInstaller | 6.22.3 in `backend/requirements-build.txt` | Pinned packaging venv; version checks before frontend build in local Windows pipeline |
| Audit/build Python packages | Existing requirement files | Existing isolated environments and pinned installers |
| actionlint | 1.7.12; platform archive SHA-256 pinned in `managed_tools.py` | Windows/Linux x64; required only when Repository/shared workflow lint runs |
| Inno Setup bootstrap | 7.1.0; pinned Windows installer SHA-256 | Installer-bearing Windows targets; existing per-user compiler provisioning/receipt checks retained |
| Git, Docker/Compose, PowerShell, service compiler | Existing compatible host checks | Target-specific; no implicit system installation |
| WebView2 | Existing native acceptance prerequisite | Runtime prerequisite, never silently downloaded by this resolver |

Fresh local Windows validation resolves managed tools **before Environment,
Python installs, frontend, backend tests and Repository lint**. Deployment shared
validation resolves them before its environments/frontend/tests. A verified
receipt-reuse path does not acquire tools for checks it does not run. Quick,
dry-run and read-only prerequisite inspection do not download managed tools.

Check/setup independently before another expensive build:

```powershell
.\scripts\build.ps1 -Mode prerequisites -Platform windows -Target desktop -CheckOnly -NonInteractive
.\scripts\build.ps1 -Mode prerequisites -Platform windows -Target desktop -NonInteractive
```

```bash
python scripts/build.py prerequisites --platform linux --target server --check-only --non-interactive
python scripts/build.py prerequisites --platform linux --target server --non-interactive
```

Check-only reports cached archive availability without network access or cache
writes; actual executable/version verification occurs in preflight. Setup may
create project venvs and install locked project packages. It does not imply native
packaging or runtime acceptance. `--setup-only` also resolves the selected managed
tools. Select `installer` explicitly when preparing the Inno bootstrap.

### Managed tool policy

Resolution prefers an explicit local artifact, then checksum-verified configured
and project/run caches, then a configured approved HTTPS mirror, then the official
upstream release. Default local storage is ignored `.build-tools/`, separate from
runtime/user data and disposable packaging output. `RUNNER_TEMP`, when set by CI,
is used by its lint adapter; `SAP_LENS_TOOL_CACHE` supplies a persistent cache.
Verified legacy `backend/build` archives are promoted into the selected cache.
Normal build cleanup does not purge `.build-tools/`.

Archive SHA-256 is checked before extraction. Only the expected executable member
is read; link/invalid members are rejected. Cached executable bytes must match the
verified archive and actionlint must report exactly the pinned version. A PATH
binary is reused only if its bytes match that trusted archive, not merely because
it claims the right version. Keep archives with binaries for offline verification.
Missing/corrupt artifacts never count as successful validation.

Downloads are capped at 32 MiB, have socket timeouts and at most three attempts per
source with 0.25/0.5-second backoff for transient failures. 403/404 and TLS failures
are not retried repeatedly. A configured mirror denial may fall back to the
official source; a checksum mismatch is rejected immediately. HTTPS redirects
are supported; downgrade to HTTP is refused. Proxy/CA behavior uses Python's
standard trusted configuration, never disabled verification. Temp files are
fsynced and atomically published; kernel-owned acquisition locks serialize
concurrent callers and release on process exit. No partial download is executed.

| Variable | Meaning |
| --- | --- |
| `SAP_LENS_TOOL_CACHE` | Persistent cache directory; use an absolute path |
| `SAP_LENS_ACTIONLINT_ARCHIVE` | Explicit official Windows ZIP or Linux tar.gz; exact pinned checksum required |
| `SAP_LENS_ACTIONLINT_MIRROR` | Approved HTTPS directory containing `actionlint_1.7.12_windows_amd64.zip` and/or `actionlint_1.7.12_linux_amd64.tar.gz` |
| `SAP_LENS_INNO_ARCHIVE` | Explicit pinned `innosetup-7.1.0-x64.exe` bootstrap artifact |
| `SAP_LENS_INNO_MIRROR` | Approved HTTPS directory containing that exact Inno installer filename |
| `SAP_LENS_TOOLS_OFFLINE=1` | Managed tools use verified local artifacts/caches only; does not put pip/npm/other build operations offline |
| `HTTPS_PROXY`, `NO_PROXY`, trusted CA configuration | Standard urllib proxy/trust handling; never print proxy credentials or disable certificate verification |

Example restricted-network configuration (replace reserved example hostname with
your organization-approved artifact service):

```powershell
$env:SAP_LENS_TOOL_CACHE = 'C:\BuildTools\SAP-Lens'
$env:SAP_LENS_ACTIONLINT_MIRROR = 'https://artifacts.example.invalid/sap-lens'
.\scripts\build.ps1 -Mode prerequisites -Platform windows -Target desktop -NonInteractive
```

Mirrors must provide the **same upstream bytes**; they cannot override versions or
hashes. Initial source URLs cannot embed credentials, query tokens or fragments.
Use an approved proxy or explicit local artifact if the artifact service needs an
authentication scheme this downloader does not implement. Diagnostics omit URL
authentication/query data, internal repository paths and raw network exception
messages; they report attempted sources, failure category, cache status, required
checksum, mirror availability and remediation. A User-Agent change is not a fix
for an authorization policy.

Persistent 403: ask the network/artifact administrator for approved access or a
mirror, then run prerequisite setup again. Offline cache miss: provision a
verified artifact through approved channels. Checksum/version mismatch: do not
execute or allowlist the artifact; investigate the source. Cache permission/disk
failures: repair only the chosen tool cache. No WDAC, TLS, proxy or endpoint
controls are bypassed. Native Windows/corporate acquisition must be verified
separately; mocked network success does not prove access through that network.

### Machine-readable prerequisite reports

`prerequisites --json` (PowerShell `-Json`) writes exactly one JSON report to
stdout for checks, setup and expected failures. `ok` and `exit_code` match the
process outcome; warnings remain in report items and human diagnostics go to
stderr. A supported non-LTS Node version remains a warning, not a failure.
Interpreter handoff, dependency progress and verbose diagnostics must not prefix
the document. Machine-readable mode does not prompt; JSON-mode children have
closed stdin. Dry-run also reserves stdout for its JSON plan.

Consume stdout directly; do **not** merge stderr with `2>&1` before parsing:

```powershell
New-Item -ItemType Directory -Force build | Out-Null
$report = .\scripts\build.ps1 -Mode prerequisites -Platform windows -Target server -CheckOnly -NonInteractive -Json 2> build/prerequisites-json.stderr.log | ConvertFrom-Json
if ($report.exit_code -ne $LASTEXITCODE) { throw 'Report/process exit codes disagree.' }
$report.items | Where-Object status -eq 'Warning'
```

Windows PowerShell 5.1 and PowerShell 7 use the same interface. Native stderr
warnings do not override the child's exit code; bootstrap failures before Python
starts produce an error report instead. Invalid CLI syntax/help remains ordinary
CLI usage output, not a successful prerequisite report. Linux/Python consumers
can use `subprocess.run(..., capture_output=True)` and `json.loads(done.stdout)`
without filtering lines; preserve `done.stderr` and the exit code for diagnostics.

### Source-isolated outputs and PowerShell status

Cross-platform local deployment defaults are now
`dist/<product-version>-<first-12-source-SHA>/`. Local and trusted remote builders
use the same naming rule. Different commits normally get separate directories;
the manifest still records the **full** source SHA and refuses a different
identity even in a short-prefix collision. Product versions and artifact names
are unchanged. Explicit `-Output`/`--output` paths are honored exactly, including
older layouts, with the same no-overwrite checks. Existing directories are never
deleted automatically. Legacy portable Desktop output already includes its
local identity/run ID and keeps that established layout.

The bootstrap uses the global native LASTEXITCODE value consistently. A
script-local sentinel must not shadow the native value and turn a successful
build into apparent exit 2. Wrapper exceptions after a successful child become
nonzero failures; help/invalid arguments retain CLI semantics. Native tests cover
help, dry-run success, invalid arguments and a caller with a stale exit code.
The reported separate help exit 1 has not been reproduced on Linux; inspect
stdout/stderr if it persists on Windows rather than assuming it was success.

Commands for the next native checks (no release is published):

```powershell
# Service package; ordinary packaging does not require installing a service.
.\scripts\build.ps1 -Mode build -Platform windows -Target server -NonInteractive
# Elevated: use the exact service ZIP path printed by the build, or an extracted directory.
.\scripts\test-server-service.ps1 -Bundle 'C:\Builds\verified-service-package.zip'
# Desktop installer target and native installer behavior against its verified artifacts.
.\scripts\build.ps1 -Mode build -Platform windows -Target installer -NonInteractive
# Use the actual setup EXE path reported/extracted from the verified Desktop artifact.
.\scripts\test-desktop-installer.ps1 -Installer 'C:\Builds\SAP-Lens-Setup.exe' -Report 'C:\Builds\installer-acceptance.json'
```

For the installer lifecycle command and prerequisites, see
[Desktop installation/lifecycle](deployment/WINDOWS_DESKTOP.md) and the native
installer test's `-Installer` / `-Report` interface. SCM cleanup/security details and test commands
are in [Windows Service acceptance](deployment/WINDOWS_SERVICE.md#isolated-native-scm-acceptance).
