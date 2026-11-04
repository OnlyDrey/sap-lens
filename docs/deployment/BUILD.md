# Build and obtain deployment packages

Runtime support, an automated packaging test, and native acceptance are different
claims. The scripts/workflow below implement packaging; a downloadable Actions
artifact exists **only after an approved run succeeds**. No run is started by these
documents. See [actual validation](../archive/validation/PACKAGING_VALIDATION.md).

Deployment archives and checksum sidecars are never overwritten by a repeated
packaging command. Choose a new output directory after reviewing an existing
package. Keep archive output outside the input bundle; nesting it inside the
bundle would make the archive include itself. Checksums are written only after
the new archive passes its extraction/content verification.

## Find your build path

- [Actions: one build target dropdown](#manual-build), [artifact names and download](#outputs).
- [Local cross-platform builds](#local-cross-platform-builds), [prerequisites](#build-time-prerequisites), [commands](#commands), [cross-host builders](#cross-host-builds), [outputs](#outputs-and-verification).
- [Windows Quick/Validate/Build/Package](#windows-only-development-modes), [Windows prerequisite setup](#2-install-and-check-prerequisites), [mode contracts](#5-choose-a-mode), [troubleshooting](#9-troubleshooting).
- [Install the result](README.md#choose-a-target), [release policy](RELEASES.md), [validation limits](README.md#validation-status).

Build commands belong here; platform guides own installation and operations.

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
exactly-two-file ZIP contract. See [desktop installation](WINDOWS_DESKTOP.md).
This installer definition has not been compiled or accepted on Windows in the
Linux development environment. The separate legacy Windows release artifact
remains the portable pair; it is not silently changed into an installer release.

Docker packages include an offline image, Compose configuration and the
[managed lifecycle entry point](LINUX_DOCKER.md). Native packages
include their installer and offline wheelhouse. No target needs Node.js or React
compilation; native Linux explicitly requires Python 3.12 and venv support.

Server archives contain `package-manifest.json` with per-file hashes and build
identity. Windows Service includes pinned WinSW and its MIT license. Native
includes a hash-locked wheelhouse with dependency licenses; frontend production
license notices are included in compiled assets for all platforms. SAP Lens is proprietary under [LICENSE.md](../../LICENSE.md); third-party
notices do not grant rights to redistribute the application.

Only production application inputs and explicit deployment files are packaged.
CSV exports, snapshots, settings, secrets, test results, virtualenvs and Git history
are excluded. Target configuration is generated at install time; it must not be
prepopulated with an organization's data or access secrets.


## Local cross-platform builds


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
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1 -Platform desktop -Version 1.0.0-beta.1
```

## Commands

```powershell
.\build.ps1 -Platform desktop -Version 1.0.0-beta.1
.\build.ps1 -Platform service -Version 1.0.0-beta.1
.\build.ps1 -Platform docker -Version 1.0.0-beta.1
.\build.ps1 -Platform linux-native -Version 1.0.0-beta.1
.\build.ps1 -Platform all -Version 1.0.0-beta.1
```

```bash
./build.sh --platform desktop --version 1.0.0-beta.1
./build.sh --platform service --version 1.0.0-beta.1
./build.sh --platform docker --version 1.0.0-beta.1
./build.sh --platform linux-native --version 1.0.0-beta.1
./build.sh --platform all --version 1.0.0-beta.1
```

Alpha, Beta and RC use dotted SemVer sequences; Stable uses `1.0.0`. Local package
metadata has no GitHub run number or reserved tag; the manifest identifies the
source commit and actual build environment. Legacy development commands under
[Windows-only modes](#windows-only-development-modes) remain available for Quick,
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
./build.sh --platform all --version 1.0.0-beta.1 \
  --windows-host sap-lens-windows \
  --windows-repository 'C:/Build/SAP Lens'
```

```powershell
.\build.ps1 -Platform all -Version 1.0.0-beta.1 `
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
archives and their individual `.sha256` files, combined `SHA256SUMS.txt`,
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
desktop packages include their Python runtime. See [Actions artifacts](#outputs)
and the platform [deployment guides](README.md) for installation/runtime
prerequisites. Automated package smoke tests do not replace native desktop,
SCM reboot/recovery/UNC, systemd boot or physical mobile-browser acceptance.

## Windows-only development modes

From the repository root, use the canonical local Windows entry point:

```powershell
.\scripts\build-local.ps1 -Mode Quick
.\scripts\build-local.ps1 -Mode Build
```

Neither command requires `-Version`. Both resolve
`backend/resources/product-version.json` through `backend/version.py`. Builds
never bump that resource, rename tags or create releases.

**Quick** is an offline preflight, not an application launcher or package build.
**Build** produces the verified portable desktop EXE/ZIP. For a headless service
bundle and ZIP in the same run, explicitly use:

```powershell
.\scripts\build-local.ps1 -Mode Build -IncludeService
```

The separate root `build.ps1` is retained as a compatibility front door to the
cross-platform deployment orchestrator; it is not a competing EXE compiler.
`-Platform desktop` produces the installer-first deployment archive, while
`build-local.ps1` retains its established portable output. See [cross-platform
commands](#commands) for installers, Docker and Linux. The root PowerShell wrapper
also defaults to the authoritative version when `-Version` is omitted.

## 2. Install and check prerequisites

Use Windows x64, x64 Windows PowerShell **5.1** or PowerShell **7**, Git on PATH,
Python **3.12 x64** with pip/venv, Node **24 LTS** (25 is accepted) and npm **10/11**.
WebView2 Evergreen and an interactive desktop are needed for desktop/native smoke
validation. `-IncludeService` also requires the .NET Framework 4.8 compiler.

[Windows build toolchain](../development/DEVELOPMENT.md#windows-build-toolchain)
owns installation commands, tool version checks, npm/PATH recovery, proxy/CA
requirements and process-scoped execution-policy guidance. Normal local builds
and per-user Desktop setup do not need elevation. Only actual Windows Service
installation/SCM administration requires an administrator; optional service
**packaging** does not install or register a service.

## 5. Choose a mode

| Operation | Quick | Validate | Build | Package |
| --- | --- | --- | --- | --- |
| Windows/x64/PowerShell/Git/Python/Node/npm gates; version resolution | Yes | Yes | Yes | Yes |
| Required inputs, product/package versions, Python AST, docs, PowerShell parser/management mocks and whitespace | Yes | Repository checks | Repository checks | Receipt reuse |
| Install pinned isolated Python tooling and locked frontend dependencies | No | Yes | Yes | Reuse |
| Typecheck, Lucide catalog and production frontend build | No | Yes | Yes | Reuse |
| Python/production JavaScript vulnerability audits | No | Yes | Yes | Rerun |
| Five packaging backend modules and single-worker `@smoke` browser checks | No | Yes | Yes | Reuse |
| Workflow/repository lint and fresh packaging receipt | No | Yes | Yes | Reuse |
| Clean checkout, PyInstaller, PE/privacy/integrity checks, real EXE smoke and ZIP roundtrip | No | No | Yes | Yes |
| Optional verified service bundle/ZIP | No | No | `-IncludeService` | `-IncludeService` |

Quick makes no package, installs nothing and does not invalidate a receipt or
write build/product identity. It writes only ignored run logs/summary and holds
the shared build lock. Missing source files, malformed versions, mismatched
package manifests and unsupported tools fail with a nonzero exit code.

The five packaging modules are `test_desktop`, `test_windows_package`, `test_server`,
`test_build_version` and `test_local_build`. Browser validation uses the existing
`@smoke` tag with one worker. Neither local Build nor Validate starts the complete
application/backend/browser regression. Full regression remains explicit through
`python scripts/validate.py --level full`. Native PE and EXE smoke checks are
mandatory even though application regression is targeted.

### Validate now, package later

```powershell
.\scripts\build-local.ps1 -Mode Validate
.\scripts\build-local.ps1 -Mode Package
```

A schema-2 receipt binds the exact clean source commit, tracked files, version,
Python environment, compiled frontend, tool versions and successful packaging
stages for at most 24 hours. Package rechecks it and current dependency audits;
it never treats a missing/stale receipt as permission to skip validation. Older
receipt schemas are rejected: rerun Validate. Quick does not touch the receipt,
but source/environment changes still invalidate it. Use the same optional version
override for Validate and Package. Never edit receipts to bypass checks.

## 6. Find and verify the output

Every invocation uses a fresh timestamp/random run ID. Read that run's summary,
not an older directory containing an EXE:

```text
dist/local/runs/<run-id>/build.log
dist/local/runs/<run-id>/summary.json
dist/local/packages/<local-version>/<run-id>/
  application/SAP-Lens.exe
  application/SAP-Lens.exe.sha256
  archive/SAP-Lens-Windows-x64-<local-version>.zip
  archive/SAP-Lens-Windows-x64-<local-version>.zip.sha256
  verification-report.json
  build-manifest.json
  service/                         # only with -IncludeService
  service-archives/                # only with -IncludeService
```

The optional service archive is
`sap-lens-win-service-x64-v<local-version>.zip` with a `.sha256` sidecar. It contains
the headless runtime, frontend, verified WinSW, service-manager EXE, management
script, documentation/licenses and manifest. Machine-specific service XML is
created during registration, not shipped with credentials.

No target output is overwritten. A failed required stage returns exit code 1;
`summary.json` records the stage and has no successful `artifact_directory`.
Partial outputs can remain for diagnosis; they are not overall build success.
If optional service packaging fails after the desktop export completed, that
desktop manifest certifies only the desktop portion. Consult the failed run
summary before using either output. Build locks prevent simultaneous local
packagers; no cleanup removes application installations or persistent user data.

### Read the summary and verify hashes manually

```powershell
Get-Content -Raw 'dist/local/runs/<run-id>/summary.json' | ConvertFrom-Json |
    Format-List mode,status,last_stage,seconds,artifact_directory
Get-FileHash 'dist/local/packages/<local-version>/<run-id>/application/SAP-Lens.exe' -Algorithm SHA256
```

Compare with `build-manifest.json` and the checksum sidecar. The builder already
verifies ZIP extraction and the extracted EXE against the original approved hash.
Checksums detect changed bytes, not publisher authenticity; outputs are unsigned.

## 7. Version and build identity

The authoritative product resource currently supplies the development version;
there is no second local version source. Stable, `alpha.N`, `beta.N`, `rc.N`, and
existing legacy `beta-N` overrides are supported within Windows numeric limits.
An explicit `-Version 1.0.0-rc.3` is only for an intentional local test package; it
never edits product metadata. Omit it for normal builds.

A source version such as `1.0.0-beta.2` becomes
`1.0.0-beta.2+local.<12-character-commit-SHA>` in the unofficial portable identity,
PE ProductVersion and manifests; its numeric PE FileVersion is `1.0.0.2`. Legacy
`1.0.0-beta-4` remains spelled that way when explicitly requested. There is no
automatic dot-to-hyphen conversion, sequence bump, tag or fabricated CI run.
The full source SHA is retained. Repeatable identity does not promise byte-for-byte
reproducibility of PyInstaller or ZIP output.

## 8. Pipeline internals

| Entry/helper | Owner and retained purpose |
| --- | --- |
| `scripts/build-local.ps1` | Canonical local Windows modes, locking, logs, environment restoration and failure summary |
| Root `build.ps1` / `build.sh` → `scripts/build-deployments.py` | Existing cross-platform deployment orchestration and remote builders; installer-first Desktop and other target archives |
| `scripts/build-windows.ps1` | Shared desktop compilation/audit/verification/smoke stages; targeted flag is used only by the local entry point |
| `scripts/local-build.py` | Read-only Quick checks, shared version resolution, local receipt/export, pinned WinSW acquisition |
| `scripts/build-server-windows.ps1` | Independent console/onedir headless runtime and .NET service-manager compiler |
| `scripts/package-windows-deployment.ps1` | CI/local cross-platform deployment packaging adapter; reuses canonical compilers |
| `scripts/build-desktop-installer.ps1` | Existing pinned Inno Setup wrapper and recipe checks, with per-user provisioning |
| `scripts/verify-windows-package.py`, `verify-server-bundle.py`, native smoke scripts | Mandatory PE/resources/identity/frontend/privacy, integrity and native lifecycle evidence |
| Release, Linux, Docker, install/manage and validation scripts | Separate active responsibilities; retained rather than deleted as alleged duplicates |

No obsolete standalone cleanup script was found safe to remove. Root wrappers
already delegate instead of reimplementing packaging. The legacy Windows release
workflow and independent deployment jobs keep their existing interfaces and
publication behavior. Local targeted receipts do not satisfy or replace CI/deployment
attestations. No workflow, release, product version or installer framework changed.

WinSW 2.12.0 x64 is acquired automatically and verified against the existing
server verifier's SHA-256 pin before atomic cache activation. Both CI and local
service builders reuse it. A valid cache is rechecked; a tampered cache fails
without silent overwrite. For an offline server build, pass an already verified
`-WinSW <path>` to `build-server-windows.ps1` after Validate, or provision the exact
pinned file as `backend/build/WinSW-x64.exe`. See the [service guide](WINDOWS_SERVICE.md#build-on-x64-windows).

### Environments, generated files and caches

| Location | Contents / behavior |
|---|---|
| `backend/build/python-env` | Dedicated build/test Python virtual environment |
| `backend/build/audit-env` | Separate pip-audit interpreter; not a packaging input |
| `backend/build/build-version.json` | Generated local or CI identity |
| `backend/build/local-validation.json` | Schema-2 packaging-validation receipt; valid up to 24 hours |
| `backend/build/local-build.lock` | Exclusive lock held during a local run |
| `backend/build/timings.jsonl` | Canonical stage timing records |
| `backend/build/local-test-settings/<run-id>` | Isolated local test configuration |
| `frontend/node_modules`, `frontend/dist` | Lockfile-installed frontend tools and compiled production assets |
| `backend/dist/SAP-Lens.exe` | Intermediate canonical executable; use the verified exported package for distribution |

Requirements in `backend/requirements-build.txt`, `requirements-desktop.txt`,
`requirements-dev.txt` and `scripts/requirements-audit.txt` control Python installs.
Frontend dependencies use `frontend/package-lock.json`. Global Python packages
are not modified. Build/test dependencies being installed does not mean they are
all bundled; PyInstaller and the package verifier control the actual distribution.

Normal pip/npm download caches and Playwright's versioned browser cache are reused.
Only the required Chromium headless shell is installed. actionlint 1.7.12's Windows
x64 archive is checked against its pinned SHA-256 before execution. Full virtual
environments and EXEs are not restored from untrusted caches. Clean PyInstaller
packaging remains enabled.

The wrapper sets Python I/O to UTF-8 before querying executable paths. It isolates
test settings, clears CSV environment inputs and restores changed process
environment variables/location after completion. Do not run another build or
modify source, dependencies or frontend outputs concurrently in the same checkout.
Never place real SAP exports in tracked folders or add them to the package.


### Environment variables read by the build scripts

These are set by the build orchestration or an administrator for networked or managed builds; none is needed for a normal local build, and none is stored in an image layer.

| Variable | Read by | Meaning |
|---|---|---|
| `SAP_LENS_FRONTEND_STAGE` | `Dockerfile` build argument | Docker stage that supplies `frontend/dist`; the packager passes `validated_frontend` so the image reuses the already validated frontend. |
| `SAP_LENS_BUILD_INFO` | `Dockerfile` build argument, `scripts/package-docker.py` | Compact JSON build identity (version, commit) validated and written into the image. |
| `SAP_LENS_BUILD_CA` | `scripts/package-docker.py` | Path of an optional CA bundle mounted as the build secret `build_ca` during networked builds only. |
| `SAP_LENS_BUILD_PROXY_HOST` | `scripts/package-docker.py` | Optional `host:ip` entry added to the build container for a managed proxy. |
| `SAP_LENS_AUDIT_PYTHON` | `scripts/build-deployments.py`, `package-docker.py`, `test-native-deployment.py` | Python interpreter that has `pip-audit` installed for the dependency audit step. |
| `SAP_LENS_EXPECTED_BUILD_JSON` | `scripts/verify-windows-package.py`, `release-windows.py` | Expected build identity the Windows package verification compares with the embedded metadata. |

## 9. Troubleshooting

Start with the final **failed stage**, then open that run's `build.log` and
`summary.json`. Preflight failures before output directories exist appear only in
the console. Keep the original exit code when automating; a nonzero code is failure.

| Symptom / stage | Diagnosis and action |
|---|---|
| Script not found | Confirm repository root and `Get-Item .\scripts\build-local.ps1`; obtain the reviewed local-build commits if missing |
| Unsigned script / execution policy | See the scoped bypass and trusted-file unblocking instructions in section 2; managed policies require IT approval |
| Missing/wrong Python | Check `py -3.12 --version` and x64 bitness; inspect `Get-Command python` if using the fallback |
| Wrong Node/npm | Check `node --version`, `npm --version`, `Get-Command node`; reopen the shell after installing supported Node 24 or 25 |
| Dirty source check | Review `git status --short`; commit only intended changes, then validate the final commit |
| Stale receipt / Package | Run Validate with the exact same version on the clean final commit; do not edit the receipt |
| Another local build / locked files | Let the other run finish; close SAP Lens. The lock file's existence alone does not mean a live lock is held |
| pip/npm/Playwright download or CA failure | Check approved proxy, trust and registry access. Do not disable TLS verification |
| Audit failure | Review the reported advisory and affected dependency. Update pins with compatibility tests; do not suppress it merely to finish packaging |
| Browser failure | Read the exact assertion and retained test trace; do not treat a test failure as proof of exhausted Actions credits |
| Metadata/package verification failure | Inspect the reported phase/category; use matching source, identity and freshly built assets. Do not skip the verifier |
| WebView2/startup smoke failure | Verify Evergreen Runtime and an interactive desktop, close old instances, then review isolated smoke-test diagnostics |
| Antivirus/SmartScreen intervention | Ask IT to inspect the unsigned executable and logs; do not disable endpoint protections |

For inspection of retained browser traces, from `frontend` use the installed CLI:

```powershell
node .\node_modules\playwright\cli.js show-trace 'C:\Path\To\trace.zip'
```

Test output location depends on Playwright configuration/CLI options; locate the
trace named in the failing test output. Review logs and traces before sharing:
they may include local tool paths or screenshots. Use synthetic data only.


## 10. Native Windows acceptance checks

Playwright runs Chromium and does **not** prove native WebView2, OS dialogs or UNC
access. After a successful package, launch the exported `application\SAP-Lens.exe`
and record the version/source identity and each result:

1. Confirm no console is needed for daily use, then close and reopen the app.
2. Test main navigation, breadcrumbs, Back/Forward and Previous/Next across list
   pages while filters/sorting remain active.
3. Check combobox search, keyboard selection, Escape/outside-click handling and
   dropdown placement in both light and dark mode.
4. Test native file selection and separate Role Catalogue/User Access CSV tabs
   with synthetic exports, including a local path with spaces/non-ASCII characters.
5. Use an authorized synthetic file on a real UNC share, for example
   `\\demo-server\synthetic-share\SAP Test\users.csv`; replace this example with
   your approved test share. Test unavailable-share, reconnect and access-denied
   behavior. Do not substitute production SAP data.
6. Confirm settings persist after replacing the EXE, and closing the app stops
   its owned service without orphaned processes. Existing configuration is stored
   outside the executable; do not delete it as a build troubleshooting step.

Automated smoke tests cover important lifecycle/security behavior; the interactive
checks above establish OS integration that browser mocks cannot establish.

### SoD report resources

The pinned backend runtime includes office-free DOCX/PDF generation. Windows
packaging collects python-docx templates, ReportLab font data and the license
metadata for python-docx, ReportLab, lxml and charset-normalizer. ReportLab's
bundled Bitstream Vera license remains included with its fonts. Docker and native
wheelhouse installations obtain the same resources from the pinned wheels; no
Word, LibreOffice or target-machine React build is required. Resource collection,
Linux rendering and Windows wheel availability have local checks. Packaged
Windows rendering and native Save-dialog acceptance still require Windows testing.

### Desktop installer-first archive

The standard Windows Desktop deployment ZIP ships only Setup as its launch choice,
with README/licenses and a `metadata/` manifest/installer receipt. The canonical
portable EXE, its checksum and its PE/privacy verification remain internal inputs.
The download round trip verifies both the installer and that retained internal
payload. Legacy **Build Windows Application** still builds the explicit portable
distribution; its exactly-two-file contract is unchanged. Release publication
continues attaching only archives, with no public checksum sidecars. See
[Desktop installation](WINDOWS_DESKTOP.md).
