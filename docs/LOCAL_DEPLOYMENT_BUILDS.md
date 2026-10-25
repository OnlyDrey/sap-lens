# Local deployment builds

The root `build.ps1` and `build.sh` are equivalent front doors to
`scripts/build-deployments.py`. They invoke the **same** native/Docker/Windows
packagers and verifiers used by Build Deployment Packages. There is no Linux
Windows cross-compiler and no second desktop PyInstaller implementation.
Nothing here creates a tag, pushes a commit, publishes a release or registry image.

## Build-time prerequisites

Use a clean committed checkout on Windows x64 or Linux x86-64. Install:

- Python **3.12 x64**, including venv support; Windows Python launcher recommended.
- Node **24 LTS** (recommended) or **25**, with npm **10 or 11**.
- Git and PowerShell **7** (`pwsh`; Windows PowerShell 5.1 also supported).
- For Docker: Docker CLI and an **amd64 Linux engine**, with sufficient disk space
  for an image export. Windows Docker Desktop must use Linux containers; an
  explicitly configured Docker SSH context is another option.
- For native Linux: a glibc Linux x86-64 builder. Target baseline is glibc 2.35+
  (Ubuntu 22.04/24.04 family) with Python 3.12 and venv support. Wheels are checked
  against the existing <=2.35 manylinux baseline; this is not universal Linux support.
- For Windows desktop/service: a genuine Windows x64 build environment. Service
  smoke tests register a disposable SCM service and therefore require elevation.
  WebView2 requirements remain those of the existing desktop package.

The scripts create/reuse dedicated `backend/build/python-env` and `audit-env`
virtual environments, install project-pinned requirements and `npm ci` lockfile
inputs, install the pinned Playwright Chromium headless shell, and run shared
validation once per build host. Linux may need Playwright OS libraries installed
by an administrator (`node frontend/node_modules/playwright/cli.js install-deps chromium`).
Do not run the entire build as root merely to install browser libraries.
An explicit `PLAYWRIGHT_EXECUTABLE_PATH` override is supported for prepared QA
hosts; the build logs disclose that override. It is not native WebView2 validation.

For ZIP-downloaded source on Windows, review/trust the checkout first. A process-only
execution-policy bypass does not change machine policy:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1 -Platform desktop -Version 0.1.0-beta.1
```

## Commands

```powershell
.\build.ps1 -Platform desktop -Version 0.1.0-beta.1
.\build.ps1 -Platform service -Version 0.1.0-beta.1
.\build.ps1 -Platform docker -Version 0.1.0-beta.1
.\build.ps1 -Platform linux-native -Version 0.1.0-beta.1
.\build.ps1 -Platform all -Version 0.1.0-beta.1
```

```bash
./build.sh --platform desktop --version 0.1.0-beta.1
./build.sh --platform service --version 0.1.0-beta.1
./build.sh --platform docker --version 0.1.0-beta.1
./build.sh --platform linux-native --version 0.1.0-beta.1
./build.sh --platform all --version 0.1.0-beta.1
```

Alpha, Beta and RC use dotted SemVer sequences; Stable uses `0.1.0`. Local package
metadata has no GitHub run number or reserved tag; the manifest identifies the
source commit and actual build environment. Legacy development commands under
[scripts/build-local.ps1](LOCAL_WINDOWS_BUILD.md) remain available for Quick,
Validate and the previous Windows-only developer workflow. They share the same
canonical EXE packager; root commands are the supported cross-platform interface.

Options have equivalent spellings:

| PowerShell | Shell | Behavior |
| --- | --- | --- |
| `-Clean` | `--clean` | Recreate dedicated Python build/audit environments and validation receipt; preserve packages/data and download caches |
| `-NoCache` | `--no-cache` | Cold pip/npm/browser caches and Docker layers; never deletes user data, Docker volumes or base images |
| `-ReuseValidation` | `--reuse-validation` | Require a <=24-hour clean-source/tool/environment/frontend receipt; stale/missing/changed inputs fail |
| `-OutputDir <path>` | `--output-dir <path>` | Separate empty output, or managed output with identical source/version |

Clean and ReuseValidation are mutually exclusive. NoCache respects an explicitly
supplied external Playwright executable rather than deleting it. Existing archive
files are never overwritten: choose another output directory for another build.
A build lock prevents simultaneous writers. After a crashed process, verify no
build is running before manually removing `backend/build/deployment-builder.lock`.
No script resets, rebases or cleans Git work.

## Cross-host builds

| Target | Windows host | Linux host |
| --- | --- | --- |
| Desktop | Native Windows packager | Explicit Windows SSH builder |
| Service | Native Windows packager + SCM smoke | Explicit Windows SSH builder + SCM smoke |
| Docker | Linux Docker engine/Desktop/context | Linux Docker engine |
| Linux native | Explicit Linux SSH builder (VM/WSL2/physical host) | Native Python 3.12 Linux builder |

Configure an SSH host alias/key in your normal SSH configuration, and pin its host
key. OpenSSH **9+** with SFTP-mode `scp` is required for paths with spaces/Unicode.
No passwords, tokens or private keys are stored in repository build configuration.
Prepare the trusted builder's prerequisites and a dedicated clean checkout at
**exactly the same commit** first. The scripts do not fetch/push/reset that checkout.
A Windows builder must allow PowerShell and `py -3.12` over SSH; Linux needs
`python3.12`. A WSL2/VM builder is supported through its explicitly configured SSH
endpoint, not through an invented Windows cross-compiler.

```bash
./build.sh --platform all --version 0.1.0-beta.1 \
  --windows-host sap-lens-windows \
  --windows-repository 'C:/Build/SAP Lens'
```

```powershell
.\build.ps1 -Platform all -Version 0.1.0-beta.1 `
  -LinuxHost sap-lens-linux -LinuxRepository '/home/build/SAP Lens'
```

Equivalent `--linux-host`/`--linux-repository` and `-WindowsHost`/
`-WindowsRepository` options are supported. Related remote targets are grouped so
one host validates once. Retrieved manifests must match this source, version and
unique invocation; exact filenames and checksums are verified again after SFTP.
Only explicitly trusted build hosts should be used. Host keys are never bypassed.

All attempts every requested target and reports each result. Missing environments
or failed shared validation are failures, not skipped successes. Independent
successful packages remain available; the process exits nonzero if any target
fails. A failed shared suite is not rerun for every sibling target.

## Outputs and verification

Default output: Git-ignored `dist/<version>/`, containing successful platform
archives and their individual `.sha256` files, combined `checksums.sha256`,
`build-manifest.json` and `build.log`.

The manifest records version/source, invocation/timestamp, target, actual host/
build environment, archive/hash and separate built/package-verified/runtime-smoke
results. A failed target cannot be labeled verified or runtime-tested. Local
receipts guard accidental stale inputs; they are not signatures against a
malicious developer who controls the build machine.

Windows uses existing EXE/PE/icon/resource/privacy/checksum/native smoke rules.
Service adds WinSW pin verification and SCM install/start/health/stop/uninstall.
Native Linux uses a hash-locked offline wheelhouse, extraction/privacy validation
and installed-process/persistence smoke tests. Docker contains **image.tar** for
`docker load`, compiled app assets inside that image, Compose configuration,
configuration example, documentation and checksums; it does not require Node.js
or React compilation on the target. Docker packaging consumes the already
validated frontend rather than building it twice. Ordinary `docker compose build`
from source retains its normal frontend build path.

Builds need network access for tools/dependencies/base images unless they are
already cached. An offline deployment archive is not a promise of an offline
**build**. Native targets require Python 3.12/venv/system libraries; service and
desktop packages include their Python runtime. See [packages](DEPLOYMENT_PACKAGES.md)
and the platform [deployment guides](DEPLOYMENT.md) for installation/runtime
prerequisites. Automated package smoke tests do not replace native desktop,
SCM reboot/recovery/UNC, systemd boot or physical mobile-browser acceptance.
