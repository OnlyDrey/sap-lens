# Build and obtain deployment packages

Runtime support, an automated packaging test, and native acceptance are different
claims. The scripts/workflow below implement packaging; a downloadable Actions
artifact exists **only after an approved run succeeds**. No run is started by these
documents. See [actual validation](../archive/validation/PACKAGING_VALIDATION.md).

## Find your build path

- [Actions: one target or All](#manual-build), [artifact names and download](#outputs).
- [Local cross-platform builds](#local-cross-platform-builds), [prerequisites](#build-time-prerequisites), [commands](#commands), [cross-host builders](#cross-host-builds), [outputs](#outputs-and-verification).
- [Windows Quick/Validate/Build/Package](#windows-only-development-modes), [Windows prerequisite setup](#2-install-and-check-prerequisites), [mode contracts](#5-choose-a-mode), [troubleshooting](#9-troubleshooting).
- [Install the result](README.md#choose-a-target), [release policy](RELEASES.md), [validation limits](README.md#validation-status).

Build commands belong here; platform guides own installation and operations.

## Manual build

Open Actions → **Build Deployment Packages** → Run workflow, select the intended
branch (normally `work`), then choose:

- `Windows Desktop`
- `Windows Server Service`
- `Linux Docker`
- `Linux Native/systemd`
- `All`

Supply base `version`, such as `0.1.0`, a `release_channel`, and a positive
`prerelease_number` for prereleases. Publication is controlled separately by
`publish_release`, **false by default**. All selected artifacts embed the same
resolved version, source commit and workflow run/attempt.

| Channel | Example |
| --- | --- |
| Alpha | `0.1.0-alpha.1` |
| Beta | `0.1.0-beta.1` |
| Release Candidate (RC) | `0.1.0-rc.1` |
| Stable / Production | `0.1.0` |

Base components and prerelease numbers are limited to 65535 for Windows PE
compatibility. Leading zeros, suffixes in the base, invalid channels and malformed
numbers are rejected. Stable ignores a valid supplied sequence; leaving it blank
is supported. There is no automatic sequence allocation: deliberately choose an
unused version when publishing. Legacy desktop `beta-N` tags are not moved or
reused by this SemVer scheme.

With `publish_release=false`, only Actions artifacts are created: **no tag or
GitHub Release**, even for a Stable version. An embedded version/tag name is
candidate metadata, not proof of publication. No binary signing or registry push
is enabled. Existing **Build Windows Application** retains its independent,
legacy desktop build/beta/stable release behavior unchanged.

With `publish_release=true`, every selected platform must finish its native
packaging and artifact roundtrip successfully. Only then can the isolated,
write-scoped publisher collect those exact same-run artifact IDs, verify their
names/checksums against successful job outputs, stage a draft, verify every
uploaded release asset's server-side SHA-256, create an owned annotated version
tag and publish. Alpha/Beta/RC are prereleases; Stable is a normal/latest release.
All selected packages, checksum sidecars and a source/digest manifest are attached.
A failed/skipped/cancelled selected platform prevents publication. Build-only runs
still upload successful independent platform packages when a sibling fails.

Publication asks GitHub to generate release notes from repository history, keeping
the validated-package/source explanation as the prefix. Authorized maintainers can
review/edit the published notes using GitHub's Release editor. The workflow does
not pause its private draft for manual editing; use existing environment approval
before publication. Build-only mode creates neither a draft nor release notes.
GitHub Releases remains the release-history record; no CHANGELOG.md is used.

### Examples after workflow registration

For test packages: select `All`, base `0.1.0`, `Beta`, sequence `1`, and leave
**Publish release unchecked**. Download each successful job's Actions artifact.

For a Beta release: select the desired targets, base `0.1.0`, `Beta`, an unused
sequence (for example `2`), and explicitly check **Publish release**.

For Stable: select the desired targets (normally `All`), base `0.1.0`,
`Stable / Production`, and explicitly check **Publish release**. Existing
`sap-lens-stable` environment protection applies; prereleases use `sap-lens-beta`.
No repository/environment settings are modified by these source changes.

The CLI equivalent for a build-only run, **after the workflow is registered**:

```bash
gh workflow run build-deployments.yml --repo OnlyDrey/sap-lens --ref work \
  -f platform=All -f version=0.1.0 -f release_channel=Beta \
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
| Windows Desktop | `SAP-Lens-Windows-Desktop-x64-<version>.zip` |
| Windows Service | `SAP-Lens-Windows-Service-x64-<version>.zip` |
| Linux Docker | `SAP-Lens-Linux-Docker-amd64-<version>.tar.gz` |
| Linux native/client | `SAP-Lens-Linux-Native-x64-<version>.tar.gz` |

After the selected job and roundtrip succeed, open the completed Actions run's
**Artifacts** section and download the selected platform stem. Alternatively, use
`gh run download <run-id> --repo OnlyDrey/sap-lens --name <artifact-name>` for an
authorized run. Downloading is not a build or publication action.

Every artifact contains its archive plus `<archive>.sha256`, retained for 14 days.
GitHub wraps these files in another downloadable ZIP: extract that wrapper first.
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
desktop packages include their Python runtime. See [Actions artifacts](#outputs)
and the platform [deployment guides](README.md) for installation/runtime
prerequisites. Automated package smoke tests do not replace native desktop,
SCM reboot/recovery/UNC, systemd boot or physical mobile-browser acceptance.

## Windows-only development modes

The root entry points above build deployment distributions. For fast checks or
legacy portable EXE development, run these from the repository root:

```powershell
.\scripts\build-local.ps1 -Mode Quick
.\scripts\build-local.ps1 -Mode Validate -Version 0.1.0
.\scripts\build-local.ps1 -Mode Build -Version 0.1.0
.\scripts\build-local.ps1 -Mode Build -Version 0.1.0-beta-4
.\scripts\build-local.ps1 -Mode Package -Version 0.1.0
```

These modes produce the portable desktop output, not all four deployment packages.
Legacy beta-hyphen versions remain supported here; deployment channels use dotted
SemVer. Package requires the matching fresh validation receipt; it is not an
unchecked shortcut.

## 2. Install and check prerequisites

### Supported build machine

Use Windows x64 and a **64-bit** PowerShell session. ARM and 32-bit shells are
rejected. The script accepts Windows PowerShell 5.1 or PowerShell 7. Install tools
through your organization's approved software process; the script needs no admin
privileges and does not change execution policy.

| Tool | Required version | Purpose |
|---|---|---|
| Git for Windows | Available on `PATH` | Source identity and clean-checkout checks |
| Python | **3.12 x64**, with `venv` and pip | Backend, tests, packaging and verification |
| Node.js | **24 LTS (recommended) or 25** | Frontend tools and browser tests |
| npm | **10 or 11** | Lockfile-based dependency installation |
| PowerShell | **5.1 or 7**, x64 | Build orchestration |
| Edge WebView2 | Evergreen Runtime | Actual desktop startup/smoke testing |

### Install each prerequisite

Use your company's software portal first if this is a managed PC. Installer
permissions depend on your organization; **running the build** does not require
administrator rights. Review installer prompts rather than disabling controls.

1. **Git for Windows:** install from [git-scm.com](https://git-scm.com/downloads/win).
   Enable Git on the command line so `git.exe` is available on `PATH`. If Windows
   Package Manager is permitted, the equivalent package is:

   ```powershell
   winget install --id Git.Git --exact
   ```

2. **Python 3.12 x64:** obtain a Python 3.12 Windows installer from the
   [official Python Windows downloads](https://www.python.org/downloads/windows/)
   or your approved software portal. Include pip, the Python launcher (`py`) and
   `venv`; enable the installer's PATH option where available. Do not substitute
   Python 3.13/3.14 merely because it is newer. With permitted winget access:

   ```powershell
   winget install --id Python.Python.3.12 --exact
   ```

3. **Node.js x64 and npm:** prefer a **24.x** Windows x64 `.msi` from the
   [official Node.js 24 archive](https://nodejs.org/download/release/latest-v24.x/).
   Keep **npm package manager** and **Add to PATH** enabled in the installer.
   Installing Node.js this way installs npm too; do not install npm separately
   to repair a missing Node installation. Avoid blindly choosing “latest LTS”
   if it points to an unvalidated major version. Node 25 is also accepted; use
   the [official Node.js 25 archive](https://nodejs.org/download/release/latest-v25.x/)
   if you already standardize on that version. Node 25 is an odd-numbered,
   non-LTS release; Node 24 remains the recommended build/CI baseline.
   Node 25 reached upstream end of life on **2026-06-01**, so compatibility
   acceptance does not mean it receives security maintenance. Prefer Node 24
   for maintained tooling.

   For an approved winget-based installation, first inspect available versions:

   ```powershell
   winget show --id OpenJS.NodeJS.LTS --exact --versions
   ```

   If it lists a 24.x version, substitute that exact value below; the angle-bracket
   placeholder is not a runnable version string:

   ```text
   winget install --id OpenJS.NodeJS.LTS --exact --version <available-24.x.y-version>
   ```

   Use the MSI or your software portal if winget no longer offers that version.
   The local build accepts npm major 10 or 11. Check the installed npm version;
   do not upgrade globally to a new major just because npm prints an update notice.

4. **PowerShell:** Windows PowerShell 5.1 is normally already installed on Windows.
   Use its x64 edition, not Windows PowerShell (x86). PowerShell 7 is optional;
   install from [Microsoft's PowerShell installation guide](https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-windows)
   or, when permitted:

   ```powershell
   winget install --id Microsoft.PowerShell --exact
   ```

   `powershell.exe` starts Windows PowerShell; `pwsh` starts PowerShell 7. Either
   supported x64 shell can run `build-local.ps1`.

5. **Microsoft Edge WebView2 Evergreen Runtime:** install the x64 Evergreen
   Runtime from [Microsoft](https://developer.microsoft.com/microsoft-edge/webview2/),
   even if you use a different browser. The Edge browser's presence alone is not
   the acceptance check for the runtime. An approved winget installation is:

   ```powershell
   winget install --id Microsoft.EdgeWebView2Runtime --exact
   ```

   The desktop also needs .NET Framework 4.6.2 or later, normally supplied by
   supported Windows 10/11 installations. Ask IT to enable it if missing; Python's
   pinned desktop dependencies are installed by the build, not manually.

`winget` itself is supplied by Microsoft's App Installer on supported Windows
systems. If `winget` is unavailable or blocked, use the official installers or
software portal; the SAP Lens build does not require winget.

**Close PowerShell and open a new window after installing tools.** Existing
windows keep the old PATH. You do not need to reboot simply to refresh a shell's
PATH in the usual case.

### Verify tools before running a build

Open a new PowerShell window after installing tools. Check:

```powershell
$PSVersionTable.PSVersion
$env:PROCESSOR_ARCHITECTURE  # Expected: AMD64
git --version
py -3.12 --version          # Expected: Python 3.12.x
py -3.12 -c "import struct; print(struct.calcsize('P') * 8)"  # Expected: 64
node --version             # Expected: v24.x.x or v25.x.x
npm --version              # Expected: 10.x.x or 11.x.x
```

The script first tries `py -3.12`. If unavailable, it tries `python` on `PATH` and
checks that it is Python 3.12 x64. If using that fallback, replace `py -3.12` with
`python` in the diagnostic commands above.

Install the [official WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)
if absent, or ask IT to provide it. Run builds from an interactive Windows desktop
for the GUI smoke test.

### Fix “npm is not recognized” / PATH problems

First test both tools in the new PowerShell window:

```powershell
node --version
npm --version
Get-Command node -ErrorAction SilentlyContinue
Get-Command npm -ErrorAction SilentlyContinue
where.exe node
where.exe npm
```

- If **both are missing**, install Node.js 24 or 25 x64 with npm and PATH enabled.
- If **node works but npm is missing**, repair the Node.js installation and enable
  its npm component. Avoid downloading an unrelated npm executable.
- If the installer completed but **this window still cannot find them**, reopen
  PowerShell. A standard system-wide installation usually lives in
  `C:\Program Files\nodejs`, but a managed/per-user installation can differ.
- If multiple installations are listed, use the approved version manager or
  installer to select Node 24 or 25. Do not delete unrelated installations blindly.

To diagnose a standard installation without changing global PATH:

```powershell
$nodeDirectory = Join-Path $env:ProgramFiles 'nodejs'
Test-Path (Join-Path $nodeDirectory 'node.exe')
Test-Path (Join-Path $nodeDirectory 'npm.cmd')
# Run only if both files above exist and this is your trusted Node 24/25 installation:
& (Join-Path $nodeDirectory 'node.exe') --version
& (Join-Path $nodeDirectory 'npm.cmd') --version
$env:Path = $nodeDirectory + ';' + $env:Path
node --version
npm --version
```

The PATH change above affects this session only. Repair the installer/PATH setting
through your approved process for a persistent fix. If `npm.ps1` is found but
blocked as unsigned, that is an execution-policy error, not a missing npm package;
use the trusted-source process-scoped policy instructions below where permitted.

Do not solve a missing npm command by manually skipping the Frontend stage.
The compiled frontend is required in the Windows package.

### Supported range versus minimum version

The local wrapper and frontend manifest accept **`>=24 <26`**: Node 24 and 25.
CI continues to use Node 24. According to the
[official Node.js release schedule](https://github.com/nodejs/Release/blob/main/schedule.json),
Node 25 ended support on 2026-06-01; Node 24 is supported until 2028-04-30.
The installed Vite and Playwright engine ranges
include Node 25, so their declared requirements do not require rejecting it.
Changing Node versions invalidates a Package validation receipt; run Validate
again before Package.

Compatibility checks on Linux passed with Node **24.19.0** and **25.9.0**:
lockfile installation, type checking and production builds on both versions;
all **71 browser tests** on Node 25; and PowerShell version-gate regression tests.
Native Windows packaging with Node 25 has not been executed in this environment.

A bare `>=24` would also accept Node 26 and all future majors without testing
them. Those are not enabled automatically. npm remains restricted to major 10
or 11; npm's own major version is independent of the selected Node major.

### Network access

The first run needs access to Python/npm registries, vulnerability databases,
Playwright's browser downloads and GitHub's actionlint release assets. Warm caches
reduce downloads but **do not make the full build offline**: security audits still
query current vulnerability data. GitHub authentication is not needed by the build
script; cloning a private repository may require your existing Git credentials.

Preserve approved proxy and CA configuration. Do not disable certificate checks
or skip audits to work around a corporate network error.

### PowerShell blocks unsigned or downloaded scripts

An error such as “the file is not digitally signed” is an execution-policy
failure **before the build starts**. It does not indicate a Python, npm or
packaging failure. Downloaded GitHub ZIPs may mark extracted files as originating
from the internet (Mark of the Web).

First inspect the effective policies:

```powershell
Get-ExecutionPolicy -List
Get-ExecutionPolicy
```

After reviewing and trusting the source, choose **one** of these approaches.
Do not change machine-wide policy to run a local build.

**Option A — allow all scripts in the current PowerShell window only:**

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\build-local.ps1 -Mode Quick
```

`Process` affects this window and its child processes, including the build's
helper scripts. It does not persist after the window closes and needs no admin
rights. It permits unsigned scripts in this session, so run only trusted code.
To restore the process override without closing the window:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Undefined
```

**Option B — start a separate build process with a temporary bypass:**

```powershell
# Windows PowerShell 5.1; run from the repository root.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-local.ps1 -Mode Quick
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-local.ps1 -Mode Build -Version 0.1.0

# Alternatively, if PowerShell 7 is installed:
pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-local.ps1 -Mode Quick
```

The override applies only to that new process. Replace the mode/version as needed;
Validate and Package use the same syntax.

**Option C — remove the internet marker from trusted repository scripts:**

```powershell
Get-ChildItem -LiteralPath .\scripts -Filter '*.ps1' -File | Unblock-File
.\scripts\build-local.ps1 -Mode Quick
```

This unblocks all PowerShell scripts directly inside this repository's `scripts`
folder, including the canonical builder and verification helpers. It does not
unblock your entire Downloads folder or change execution policy. Under
`RemoteSigned`, removing the marker allows trusted local unsigned files. It does
not satisfy an `AllSigned` policy; unblocking persists for those files.

**Managed PCs:** `MachinePolicy` and `UserPolicy` (Group Policy) take precedence
over a process override. If those enforce signing or prohibit execution, stop
and request an approved approach from IT. Bypass is not a way around Group Policy,
application control or endpoint protection. The build script never changes these
policies automatically.

**Correct script and working directory:** `-Mode` is a parameter of
`build-local.ps1`. `build-windows.ps1` is the lower-level builder and uses `-Stage`,
not `-Mode`. Prefer the local entry point:

```powershell
# If currently inside the repository's scripts folder:
Set-Location ..
.\scripts\build-local.ps1 -Mode Quick
```


## 5. Choose a mode

### Coverage matrix

“Reuse” means the step must already have passed for the exact inputs, verified
through a fresh validation receipt. It does not mean the check is optional.

| Operation | Quick | Validate | Build | Package |
|---|---|---|---|---|
| Check OS/tool versions and generate local identity | Yes | Yes | Yes | Yes |
| Require clean Git checkout | No | No | Yes | Yes |
| Install pinned Python dependencies; `pip check` | Yes | Yes | Yes | Reuse |
| `npm ci`, type checks and Lucide catalog check | Yes | Yes | Yes | Reuse |
| Production frontend compilation | No | Yes | Yes | Reuse |
| Backend regression suite, deprecations as errors | Yes | Yes | Yes | Reuse |
| Browser regression suite | No | Yes | Yes | Reuse |
| Windows Python and production JavaScript audits | No | Yes | Yes | Rerun |
| Workflow contracts/actionlint, PowerShell checks, Git whitespace checks | Yes | Yes | Yes | Reuse |
| Write full-validation receipt | No | Yes | Yes | Reuse |
| Clean EXE packaging, package verification, native smoke tests | No | No | Yes | Yes |
| ZIP roundtrip, extracted EXE verification, output manifest | No | No | Yes | Yes |

Quick still installs the pinned build/test toolchain and runs all backend tests;
it is lighter than Build, not a dependency-free syntax check. Quick also
**invalidates any earlier full-validation receipt**.

### Validate now, package later

Use this when you want to separate validation from executable generation:

```powershell
# Start from the final clean commit.
.\scripts\build-local.ps1 -Mode Validate -Version 0.1.0

# Later, using the exact same checkout and version:
.\scripts\build-local.ps1 -Mode Package -Version 0.1.0
```

Package requires `backend/build/local-validation.json` from a successful Validate
or Build. It rejects a receipt if:

- It is missing, malformed, incomplete, more than **24 hours** old or future-dated.
- The source commit or requested version differs.
- Tracked source files or production frontend files changed or disappeared.
- Python environment files changed, excluding generated bytecode.
- The recorded Python or Node version changed.
- The working tree is dirty.

For example, Validate with `0.1.0` does not authorize Package with `0.1.0-beta-4`.
Changing code, committing it, or running Quick means Validate must run again.
Do not edit or copy receipts to bypass the checks. They guard accidental stale
inputs, not a malicious user who controls the local machine.

Package does not rerun regression tests or reinstall frontend/backend packages.
It does provision the separate audit environment as needed, reruns current audits,
and then rebuilds the EXE with the normal clean packaging process.


## 6. Find and verify the output

Every run has a timestamp plus random suffix to keep logs and packages separate.
All paths below are Git-ignored:

```text
dist/local/
  runs/<run-id>/
    build.log                   PowerShell transcript
    summary.json                Mode, identity, tool versions, stages, duration
  packages/<local-version>/<run-id>/
    application/
      SAP-Lens.exe               Verified application, ready to launch
      SAP-Lens.exe.sha256        Expected EXE SHA-256
    archive/
      SAP-Lens-Windows-x64-<local-version>.zip
      SAP-Lens-Windows-x64-<local-version>.zip.sha256
    verification-report.json     Extracted package verification results
    build-manifest.json          Completed package identity, hashes and sizes
```

Open the exact **Verified artifacts** directory printed by the successful run;
do not choose an older directory merely because it contains an EXE. Quick and
Validate produce logs/summary but no new verified application package.

The ZIP contains exactly `SAP-Lens.exe` and `SAP-Lens.exe.sha256`. Logs, manifests
and reports stay outside it. The manifest is written only after export and all
required checks pass. A partially written directory without a success manifest
is not a verified distribution.

### Read the summary and verify hashes manually

Use the printed paths, replacing these example placeholders:

```powershell
$runDirectory = 'C:\Projects\sap-lens\dist\local\runs\<run-id>'
Get-Content -Raw (Join-Path $runDirectory 'summary.json') | ConvertFrom-Json |
    Format-List mode, status, last_stage, seconds, artifact_directory

$packageDirectory = 'C:\Projects\sap-lens\dist\local\packages\<local-version>\<run-id>'
$manifest = Get-Content -Raw (Join-Path $packageDirectory 'build-manifest.json') |
    ConvertFrom-Json
$exe = Join-Path $packageDirectory 'application\SAP-Lens.exe'
$actual = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $manifest.exe_sha256) { throw 'EXE checksum mismatch' }

$zip = Get-ChildItem -LiteralPath (Join-Path $packageDirectory 'archive') -Filter '*.zip'
if (@($zip).Count -ne 1) { throw 'Expected exactly one ZIP' }
$zipHash = (Get-FileHash -LiteralPath $zip.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
if ($zipHash -ne $manifest.zip_sha256) { throw 'ZIP checksum mismatch' }
'EXE and ZIP SHA-256 match the manifest.'
```

Checksums detect changed files; they do not establish publisher authenticity.
The EXE remains unsigned. Confirm the source/manifest came from your trusted
build. Do not bypass your organization's endpoint or application policies.


## 7. Version and build identity

| Requested version | Resolved application / ProductVersion | Numeric PE FileVersion |
|---|---|---|
| `0.1.0` | `0.1.0+local.<12-character-commit-SHA>` | `0.1.0.0` |
| `0.1.0-beta-4` | `0.1.0-beta-4+local.<12-character-commit-SHA>` | `0.1.0.4` |

The shared identity includes the full source SHA and mode `local-build`. The UI
shows “Local build”. Backend/API, embedded JSON, PE resources and package manifest
use the same identity. No GitHub run ID or run number is fabricated, and the local
tag field is empty. The beta sequence is explicit; it does not auto-increment.

Use versions without leading zeros, a `v` prefix or arbitrary suffixes. Numeric
Windows version components must fit 0–65535; beta N must be 1–65535. Rebuilding the
same source/version preserves identity, but PyInstaller and ZIP bytes are not
promised to be bit-for-bit reproducible.


## 8. Pipeline internals

### Source of truth

| File | Responsibility |
|---|---|
| [`scripts/build-local.ps1`](../../scripts/build-local.ps1) | Mode selection, prerequisite checks, isolated tooling, logs, stage order and exit status |
| [`scripts/build-windows.ps1`](../../scripts/build-windows.ps1) | Canonical dependency, frontend, audit, test, PyInstaller, verification and smoke stages used by CI and local builds |
| [`scripts/local-build.py`](../../scripts/local-build.py) | Local identity, SHA-256 input fingerprints, receipt freshness and verified ZIP export |
| [`backend/version.py`](../../backend/version.py) | Strict shared identity schema, local version rules and runtime metadata loading |
| [`scripts/write-windows-metadata.py`](../../scripts/write-windows-metadata.py) | PE version resources generated from that identity |
| [`scripts/verify-windows-package.py`](../../scripts/verify-windows-package.py) | x64 PE/GUI, versions, icon/manifest, embedded archives, frontend integrity, privacy and checksum checks |
| [`scripts/test-windows-exe.ps1`](../../scripts/test-windows-exe.ps1) | Real EXE startup, lifecycle, session/origin and port-conflict checks |
| [`scripts/verify-artifact-zip.py`](../../scripts/verify-artifact-zip.py) | ZIP digest, exact members, safe extraction and archive checks |

Build runs validation first, fingerprints its inputs, then packages with
PyInstaller `--clean --onefile --windowed --noupx`. It verifies the EXE, runs the
native smoke test, creates a two-file ZIP, verifies/extracts that ZIP, and fully
verifies the extracted EXE against the approved original hash. Verification is
not bypassed for local builds. See [Windows packaging](../archive/validation/WINDOWS_PACKAGING.md) for
the detailed contract.

### Environments, generated files and caches

| Location | Contents / behavior |
|---|---|
| `backend/build/python-env` | Dedicated build/test Python virtual environment |
| `backend/build/audit-env` | Separate pip-audit interpreter; not a packaging input |
| `backend/build/build-version.json` | Generated local or CI identity |
| `backend/build/local-validation.json` | Full-validation receipt; valid up to 24 hours |
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
