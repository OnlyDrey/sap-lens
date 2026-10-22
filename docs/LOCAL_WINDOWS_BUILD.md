# Local Windows builds

Local builds require no GitHub Actions credits, credentials, tags or releases.
They reuse `scripts/build-windows.ps1`, the same PyInstaller arguments, package
verifier and native EXE smoke tests as CI. Signing remains disabled. They are
unofficial local packages, not GitHub releases.

## Prerequisites and first setup

Use Windows x64 with:

- Git for Windows.
- Python **3.12 x64**, including the `py` launcher, `venv` and pip.
- Node.js **24 LTS**, including npm **10 or 11** (the lockfile is authoritative).
- Windows PowerShell **5.1**, or PowerShell **7**.
- Microsoft Edge **WebView2 Evergreen Runtime**, needed for the real desktop test.
- Internet access to the package registries, vulnerability databases, Playwright
  browser distribution and GitHub's pinned actionlint download. GitHub Actions
  and GitHub authentication are not required.

Clone the repository, switch to the desired branch, and open PowerShell in the
repository root. Paths containing spaces or Unicode are supported. No admin
rights are needed by the script. Install missing prerequisites using your
organization's approved method. If an approved execution policy blocks local
scripts, follow the organization's policy; the build does not change it.

```powershell
git clone https://github.com/OnlyDrey/sap-lens.git
cd sap-lens
git switch work
.\scripts\build-local.ps1 -Mode Quick
```

The script checks the OS and tool versions before installing dependencies.
Python packages go into `backend/build/python-env`, and `pip-audit` into the
separate `backend/build/audit-env`; global Python packages are not modified.
Pinned build requirements install PyInstaller **6.22.3**, pywebview **6.2.1** and
the project's pinned pip. npm uses `npm ci` and `package-lock.json`. Existing pip
and npm download caches are reused; installed virtual environments are never
restored from untrusted caches. Playwright installs the exact locked version's
Chromium headless shell when needed and reuses its normal browser cache.
`actionlint` 1.7.12 is provisioned from its checksum-verified Windows x64 archive.
No complete EXE or build output is trusted from a cache.

## Modes

```powershell
# Fast development checks; no production build, browser suite or EXE.
.\scripts\build-local.ps1 -Mode Quick

# Full validation, no EXE; explicit version also prepares Package's receipt.
.\scripts\build-local.ps1 -Mode Validate -Version 0.1.0

# Full validation, clean one-file packaging, verification, native smoke, ZIP roundtrip.
.\scripts\build-local.ps1 -Mode Build -Version 0.1.0
.\scripts\build-local.ps1 -Mode Build -Version 0.1.0-beta-4

# Reuse the full validation above, with freshness/integrity checks.
.\scripts\build-local.ps1 -Mode Package -Version 0.1.0
```

Quick installs pinned dependencies, runs backend tests, frontend type checks,
Lucide consistency, workflow contracts/actionlint, PowerShell parsing/static
guards and `git diff --check`. It invalidates an older full-validation receipt.

Validate and Build additionally compile production frontend assets, run all
browser regressions, check Python dependency consistency and run full installed
Windows Python and production JavaScript vulnerability audits. Backend tests
include repository/privacy, migration, API, CSV, desktop and package-verifier
regressions; deprecations remain errors. Failed audits or tests stop the build.
A Validate run alone cannot establish native packaged-EXE correctness.

Build and Package require a **clean Git checkout**, including no untracked source
files. Commit your intended source changes before building. They run the same
clean, one-file, windowed, x64, UPX-disabled PyInstaller build as CI, followed by
PE/subsystem, version, icon, manifest, embedded identity, archive, frontend,
privacy and checksum checks. They run the actual EXE smoke suite: first launch,
shutdown/restart, port conflict, loopback/session protections and WebView2 startup
where the desktop environment permits it. The exact two-file ZIP is extracted
through the canonical ZIP verifier and the extracted EXE is fully verified again.
No personal CSV, local settings or branding is added to the distribution.

Package requires a successful Validate/Build with the **same explicit version**,
less than **24 hours** old, on the same clean commit. A receipt fingerprints all
tracked sources, production frontend bytes, Python environment contents (except
bytecode) and Python/Node versions. Modified/missing files, a new commit/version,
incomplete validation or an expired receipt require Validate again. Package does
not reinstall frontend/backend dependencies or reuse unverified outputs. It
reruns current Python and production JavaScript vulnerability audits before
packaging. Audits still need network access. Receipts protect against accidental
stale inputs; they are not signatures against a malicious local account.

A lock prevents concurrent local runs in one checkout. Do not concurrently run
other tools that modify the checkout, virtual environment or frontend assets.

## Versions and output

Explicit versions accept `MAJOR.MINOR.PATCH` and `MAJOR.MINOR.PATCH-beta-N`, within
Windows' 16-bit version-component limits. To distinguish unofficial packages,
`0.1.0-beta-4` becomes **`0.1.0-beta-4+local.<12-character-source-SHA>`**.
This deterministic identity is shared by the UI, backend, embedded metadata,
Windows ProductVersion and local manifest. The numeric PE FileVersion is
`0.1.0.4` (or `0.1.0.0` for base versions). No run number is invented, no reserved
beta tag is consumed, and official CI identity/allocation is unchanged. The UI
labels these packages “Local build”. Rebuilding the same source/version preserves
identity; PyInstaller/ZIP bytes are not claimed to be bit-for-bit reproducible.

Everything is Git-ignored:

```text
dist/local/runs/<timestamp-id>/
  build.log                   # transcript of stages and diagnostics
  summary.json                # success/failure, source/version, stages, duration

dist/local/packages/<local-version>/<timestamp-id>/
  application/SAP-Lens.exe
  application/SAP-Lens.exe.sha256
  archive/SAP-Lens-Windows-x64-<local-version>.zip
  archive/SAP-Lens-Windows-x64-<local-version>.zip.sha256
  verification-report.json
  build-manifest.json
```

The ZIP contains **only** `SAP-Lens.exe` and `SAP-Lens.exe.sha256`. Reports and logs
stay outside it. The manifest is written only after complete verification, includes
EXE/ZIP SHA-256 and sizes, local source identity and validation receipt. The ZIP
hash is a local digest, not a GitHub artifact-service digest. Failed runs return
nonzero and identify their last stage; no success manifest is created. A failure
before writable output/tool prerequisites are established is reported to the
console. Logs may contain local tool paths; review them before sharing.

## Troubleshooting and native QA

- **Wrong/missing Python:** run `py -3.12 --version`; install the x64 3.12 release.
- **Wrong Node/npm:** use Node 24 and its supported npm; reopen PowerShell after installation.
- **Locked files:** close SAP Lens before packaging; allow the previous local run
  to finish. Do not delete user configuration to resolve a build failure.
- **Missing WebView2/display session:** install the approved runtime and run from
  an interactive Windows desktop. Do not bypass the smoke test.
- **Proxy/certificate errors:** configure approved registry/proxy/CA trust; do not
  disable TLS verification or skip audits. Cold-cache setup needs downloads.
- **Stale Package receipt:** run Validate again after the latest commit using the
  exact same `-Version`. Do not edit the receipt.
- **Security audit failures:** investigate the reported dependency and update pins
  with regression testing. Production and development advisories are different;
  no finding is suppressed automatically.
- **Encoding:** fixture generation writes UTF-8 bytes; HTTP HTML fixtures declare
  UTF-8. Python process I/O is explicitly UTF-8 in local builds.

Automated Playwright tests run in Chromium and **do not replace native desktop
validation**. On the generated EXE, manually check navbar/routes/breadcrumbs,
global Previous/Next across pages, keyboard/mouse combobox placement in light/dark
modes, native file pickers and both CSV tabs. Test an authorized **synthetic** CSV
on an actual UNC share with spaces/non-ASCII names, unavailable share/reconnect,
and permissions denied. Confirm configuration survives EXE replacement, startup
and shutdown leave no orphaned processes, and no terminal is required to run the
finished app. No real SAP data is required for these checks.

Linux can run unit/browser/type/build/audit/static checks but cannot run this
Windows entry point or prove native WebView2, PE packaging or UNC access. See
[CI architecture](CI_ARCHITECTURE.md) and [desktop architecture](DESKTOP.md) for
those validation boundaries. Local builds never push, dispatch workflows, create
or move tags, publish releases or enable signing.

## Implementation validation record (2026-10-22)

Baseline: clean `work` at `cc61f74bf7e45cd8160cbd9ed1ebfa6dc12a7ce6`.
Read-only logs for run `39801318105` confirmed 61 passed / five failed browser
cases, before packaging. This was a test failure, not evidence of exhausted
Actions credits. The bootstrap document already declared `<meta charset="utf-8">`.
The five fixtures used Python `print()` with redirected CP1252 stdout on Windows,
then decoded the bytes as UTF-8 in Node. An ellipsis became byte `85` and then the
replacement character U+FFFD **before** `route.fulfill()` received the HTML.
Reproducing the same redirected encoding on Linux produced the identical failure.
`contentType: 'text/html'` alone was not the root cause.

The shared fixture now writes explicit UTF-8 bytes with `sys.stdout.buffer`,
uses Python UTF-8 mode and declares UTF-8 in synthetic HTTP responses. All five
exact status assertions remain. The new regression forces CP1252 stdout even on
Linux, checks the exact rendered ellipsis, HTTP charset and `document.characterSet`,
and checks a subsequent status update. Production bootstrap branding is unchanged.

Executed on Linux (Python 3.12.14, Node 24.19.0, npm 11.9.0, PowerShell 7.6.7):

| Check | Command (repository root unless specified) | Result |
|---|---|---|
| Dependency installation | `npm --prefix frontend ci --no-audit --no-fund` | Passed |
| Lucide catalog | `node scripts/sync-lucide-catalog.mjs --check` | Passed |
| Types | `npm --prefix frontend run check:types` | Passed |
| Production frontend | `npm --prefix frontend run build` | Passed |
| Backend | `python -W error::DeprecationWarning -m unittest discover -s backend/tests -v` | 209 passed |
| Browser (system Chromium) | `PLAYWRIGHT_EXECUTABLE_PATH=/usr/bin/chromium npm --prefix frontend run test:browser -- --reporter=line` | 67 passed; original 66 retained |
| Workflow contracts | `python scripts/check-workflows.py` | Passed |
| Workflow schema/expressions | `python scripts/ci.py lint` | Passed |
| PowerShell syntax/static guards | `pwsh -NoProfile -File scripts/check-powershell.ps1` | All four scripts passed |
| Python consistency | `python -m pip check` | Passed |
| Installed Linux Python audit | Separate audit interpreter: `python -m pip_audit --path <build-venv-site-packages> --progress-spinner off` | No known vulnerabilities |
| Production JavaScript | `npm --prefix frontend audit --omit=dev` | Zero vulnerabilities |
| All JavaScript (informational) | `npm --prefix frontend audit --json` | Existing 7 development advisories: 5 high, 2 moderate |
| Whitespace/integrity | `git diff --check` | Passed |

Sixteen new backend tests cover deterministic local identities, metadata resources,
invalid versions, complete/stale/modified receipts, Unicode/space paths, source and
environment changes, strict ZIP roundtrip/reverification, export failure handling,
requirement-driven tool checks, checksum-verified Windows actionlint provisioning,
non-Windows rejection and invalid PowerShell modes. Archive/PE malformed-input,
privacy and checksum regression coverage remains in the existing suite.
Windows actionlint extraction is tested with a synthetic archive; the executable
is never run in that unit test. Export tests stub the native PE subprocess while
running the real ZIP verifier; they do not prove Windows packaging success.

Bootstrap screenshots were inspected in light/dark mode at 800/1280 pixels; the
status text renders intact. No dependency versions or workflow triggers changed.
The README and canonical branding assets are untouched. The development advisories
remain visible; resolving them requires a separate compatible dependency review.
No vulnerabilities were suppressed.

**Pending:** native Windows PowerShell 5.1/7 end-to-end execution, full Windows-only
Python dependency audit, actual EXE packaging/PE verification and smoke tests,
WebView2/file-picker/UNC testing. No Windows artifact was built on Linux. No push,
workflow dispatch, tag or release was performed for this task.
