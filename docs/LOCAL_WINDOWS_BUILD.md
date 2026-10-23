# Build SAP Lens locally on Windows

This guide takes a cloned repository through validation, EXE packaging and checksum
verification. Local builds use no GitHub Actions minutes and do not create remote
commits, tags or releases. They produce an **unsigned, unofficial local build**.

Run the commands in **PowerShell**, from the repository folder containing
`README.md`, `backend`, `frontend` and `scripts`. Do not paste them into Command
Prompt. The build requires developer tools; the finished EXE does not.

To **run from source without creating an EXE**, use the
[development guide](DEVELOPMENT.md). Quick/Validate perform checks and do not start
the application.

## Contents

1. [Command reference](#1-command-reference)
2. [Install and check prerequisites](#2-install-and-check-prerequisites)
3. [Prepare the checkout](#3-prepare-the-checkout)
4. [Build your first executable](#4-build-your-first-executable)
5. [Choose a mode](#5-choose-a-mode)
6. [Find and verify the output](#6-find-and-verify-the-output)
7. [Version and build identity](#7-version-and-build-identity)
8. [Pipeline internals](#8-pipeline-internals)
9. [Troubleshooting](#9-troubleshooting)
10. [Native Windows acceptance checks](#10-native-windows-acceptance-checks)
11. [CI, publication and validation boundaries](#11-ci-publication-and-validation-boundaries)

## 1. Command reference

Copy one command at a time. You do **not** need to run all five commands in order.
For a complete first build, use **Build**.

```powershell
# Development checks. Does not produce an EXE.
.\scripts\build-local.ps1 -Mode Quick

# Full validation. Does not produce an EXE.
.\scripts\build-local.ps1 -Mode Validate -Version 0.1.0

# Full validation, packaging, native smoke tests and verified ZIP.
.\scripts\build-local.ps1 -Mode Build -Version 0.1.0

# The same complete build, using an explicit beta version.
.\scripts\build-local.ps1 -Mode Build -Version 0.1.0-beta-4

# Package inputs validated previously with the same version and commit.
.\scripts\build-local.ps1 -Mode Package -Version 0.1.0
```

| Parameter | Accepted values | Default | Meaning |
|---|---|---|---|
| `-Mode` | `Quick`, `Validate`, `Build`, `Package` | `Build` | Work to execute |
| `-Version` | `MAJOR.MINOR.PATCH` or `MAJOR.MINOR.PATCH-beta-N` | `0.1.0` | Requested local version; no `v` prefix |

Always specify the mode explicitly so the intended work is clear. A bare
`.\scripts\build-local.ps1` performs a full Build, not a quick check.

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

## 3. Prepare the checkout

For a new checkout:

```powershell
git clone https://github.com/OnlyDrey/sap-lens.git
Set-Location .\sap-lens
git switch work
```

A GitHub **Download ZIP** extraction is not a Git checkout: it has no `.git`
history. Build and Package require a real clone to record the source commit.
If currently working in `Downloads\sap-lens-work`, preserve any edits there and
clone into a separate folder. Do not run `git init` just to fabricate a build
identity. Obtain the reviewed local-build commits in that clone before building.

For an existing checkout, navigate to its root. Quote paths containing spaces:

```powershell
Set-Location 'C:\Projects\SAP Lens\sap-lens'
Get-Item .\scripts\build-local.ps1
Get-Item .\docs\LOCAL_WINDOWS_BUILD.md
git branch --show-current
git log -1 --oneline
git status --short
```

If the script or guide is missing, your checkout does not contain the local-build
implementation. Obtain the intended reviewed commits through your normal Git
workflow. Do not reset or discard existing work to update the checkout.

**Build and Package require `git status --short` to produce no output.** Modified,
staged or untracked source files make these modes stop before packaging. Review
and commit intended changes; handle unrelated files individually. Avoid bulk
staging SAP exports, local configuration or credentials. Ignored build outputs do
not make the checkout dirty.

Quick and Validate can run while developing, but a later source commit changes
the identity. Run Validate again on the final clean commit before Package.

## 4. Build your first executable

Close any running SAP Lens EXE that might lock an older build. From the clean
repository root, run:

```powershell
.\scripts\build-local.ps1 -Mode Build -Version 0.1.0
$LASTEXITCODE
```

Expect a final `passed` summary, exit code **0**, and printed paths for **Verified
artifacts** and **Logs and summary**. The first run installs dependencies and a
Chromium headless shell; it can take longer than subsequent runs. No local build
time guarantee has been measured on Windows.

A successful Build already includes full validation. There is no need to run
Quick or Validate before it. A failure returns a nonzero exit code and names the
failing stage. Do not distribute files from an unsuccessful run.

For a beta-labelled local build, use:

```powershell
.\scripts\build-local.ps1 -Mode Build -Version 0.1.0-beta-4
```

This does not reserve or publish `v0.1.0-beta-4` on GitHub.

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
| [`scripts/build-local.ps1`](../scripts/build-local.ps1) | Mode selection, prerequisite checks, isolated tooling, logs, stage order and exit status |
| [`scripts/build-windows.ps1`](../scripts/build-windows.ps1) | Canonical dependency, frontend, audit, test, PyInstaller, verification and smoke stages used by CI and local builds |
| [`scripts/local-build.py`](../scripts/local-build.py) | Local identity, SHA-256 input fingerprints, receipt freshness and verified ZIP export |
| [`backend/version.py`](../backend/version.py) | Strict shared identity schema, local version rules and runtime metadata loading |
| [`scripts/write-windows-metadata.py`](../scripts/write-windows-metadata.py) | PE version resources generated from that identity |
| [`scripts/verify-windows-package.py`](../scripts/verify-windows-package.py) | x64 PE/GUI, versions, icon/manifest, embedded archives, frontend integrity, privacy and checksum checks |
| [`scripts/test-windows-exe.ps1`](../scripts/test-windows-exe.ps1) | Real EXE startup, lifecycle, session/origin and port-conflict checks |
| [`scripts/verify-artifact-zip.py`](../scripts/verify-artifact-zip.py) | ZIP digest, exact members, safe extraction and archive checks |

Build runs validation first, fingerprints its inputs, then packages with
PyInstaller `--clean --onefile --windowed --noupx`. It verifies the EXE, runs the
native smoke test, creates a two-file ZIP, verifies/extracts that ZIP, and fully
verifies the extracted EXE against the approved original hash. Verification is
not bypassed for local builds. See [Windows packaging](WINDOWS_PACKAGING.md) for
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

## 11. CI, publication and validation boundaries

| Local builds | GitHub Actions |
|---|---|
| Explicit local version with `+local.<SHA>` | Workflow-resolved build/beta/stable identity |
| Local SHA-256 and ZIP roundtrip | GitHub artifact-service digest plus package/ZIP checks |
| Output remains under `dist/local/` | Artifact upload/download and optional approved release publication |
| No remote writes or signing | Publication only through the configured, explicitly selected release path |

Both use the canonical build and verification scripts. Local builds do not need
`GITHUB_RUN_ID` and reject the GitHub Actions execution context. They do not push,
dispatch workflows, create/delete/move tags, publish releases or enable signing.
For controlled pushes without automatic CI, see
[temporarily skip automatic CI](CI_ARCHITECTURE.md#temporarily-skip-automatic-ci).

The entry point rejects Linux. Linux unit/browser/build/audit/static checks are
useful evidence but do not prove Windows package creation, WebView2 or UNC access.
The implementation's historical test results and outstanding Windows checks are
recorded separately in [Local build validation](LOCAL_BUILD_VALIDATION.md).
For application installation/lifecycle details, see [Desktop](DESKTOP.md); official
version reservation/publication is described in [Releases](RELEASES.md).
