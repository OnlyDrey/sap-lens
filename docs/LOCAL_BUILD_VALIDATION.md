# Local build validation record

## Cross-platform implementation checkpoint

The root `build.ps1`/`build.sh` share one Python coordinator and the existing
canonical Windows, Docker and Linux package implementations. Explicit SemVer
local metadata uses schema 3, with no fabricated CI run or tag. Schema 1 developer
and legacy release identities and schema 2 deployment CI identities remain readable.

A local <=24-hour receipt binds the clean Git source, compiled frontend, Python
environment, tool versions, host and successful mandatory checks. CI never falls
back to a local receipt. Only standard POSIX venv interpreter/lib aliases are
allowed while hashing; unrelated symlinks remain rejected. Ordinary Windows
release admission is unchanged. Native local Windows uses its already validated
host environment; CI still installs/audits its Windows-specific dependencies.

Docker packaging now consumes the validated frontend stage. Ordinary source
Docker builds retain their frontend compilation path. Docker context privacy
exclusions remain after the compiled-asset allowlist. All requested targets are
reported independently, including unavailable builders and failed prerequisites.
Cross-host use requires explicit trusted SSH hosts, exact clean commits, host-key
verification and same-invocation manifests; there is no cross-compiler or silent skip.

Targeted local receipt/orchestration tests: **10 passed**. Existing deployment
contracts/publication tests: **29 passed**. PowerShell parsing/static guards,
shell syntax, actionlint, workflow contracts and whitespace checks passed.
A clean-source checkpoint is required before the actual CLI/package integration
run because the build system deliberately refuses uncommitted inputs.

Native Windows/WebView2/SCM/UNC and remote Windows/Linux builder integration have
not been tested here. Final Linux package results will be appended after actual
execution, separately from these unit/static results. No pushes, tags, releases
or workflow dispatches have occurred. Installation feature work is still gated on
this phase's available validation.

## Historical Windows-only validation record

The following is the earlier developer-build record, retained for context.

# Local build implementation validation

Historical implementation evidence, not a guarantee that a later checkout or
machine has passed validation. For current commands, see
[Local Windows builds](LOCAL_WINDOWS_BUILD.md).

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

## Final cross-platform CLI integration — 25 October 2026

Validated source: `d8a6604f2afda02adb4a11fc42b74e7f536cd5f5`.
The All-target command produced the two available Linux artifacts and returned
nonzero for the two explicitly unavailable Windows builders, as required. It did
not rerun shared validation for sibling targets. Output and manifest:
`dist/0.1.0-alpha.1-validation3/` (ignored).

- Full local backend: **376 passed**, zero skipped, 16.722 seconds.
- Browser: **233 passed**, 6.7 minutes, production assets and explicit system
  Chromium QA override; this did not exercise browser-binary download or WebView2.
- Types, production frontend build, icon catalog, dependency consistency,
  workflow/actionlint and PowerShell guards: passed through the actual CLI.
- Audits of all installed build/runtime Python versions, production JavaScript,
  actual Docker runtime and native wheelhouse: no known vulnerabilities.
- Docker: **built, archive verified and runtime smoke-tested**. Actual
  frontend/auth/import/health/version/restart/recreation persistence passed.
  Additional image inventory found no CSV, snapshots, personal settings, secrets,
  tests, Git history or node_modules under the application, and no data in /data.
- Linux Native: **built, archive verified and installed/runtime smoke-tested**.
  Offline hash-locked wheelhouse, Unicode/space paths, startup/version/import,
  shutdown, synthetic upgrade/configuration/data preservation and uninstall passed.
  This was user-mode process testing; **systemd was not running/tested**.
- Both artifacts were copied to fresh download directories and verified again with
  `check-deployment-download.py`: exact contents, identity and SHA-256 passed.
- The actual `--reuse-validation` native command passed receipt admission,
  packaging and installation/runtime checks in **13.31 seconds**, without another
  browser/backend suite. An independent output directory preserved prior artifacts.
- PowerShell facade parsing and malformed-version rejection were exercised on
  Linux/PowerShell; this is not Windows host validation.

| Target | Bytes | SHA-256 |
| --- | ---: | --- |
| Docker `0.1.0-alpha.1` | 64810689 | `38a2bab864ea8eb93c9f10fc28a3966f38a9da4b1130b7799671291c888de55c` |
| Linux native `0.1.0-alpha.1` | 14001437 | `b4ee081fd52b9fdfd084fbbbf80265daeac0e7131c0f64c4e2d9f14fa34052ea` |

All-target validation/build duration: **500.78 seconds** on this Linux host.
Archives include timestamps; repeat builds are not claimed byte-identical. Their
identity, dependency wheel hashes and artifact digests are validated independently.

The first attempt found an old API-mode assertion excluding Alpha/RC; it was
corrected with an exact metadata/API comparison. A subsequent run exposed an
inherited validation-only config path in native installation smoke testing; the
handoff now removes those overrides, without relaxing server configuration
validation. Buildx also needed a writable `BUILDX_CONFIG` in this managed cloud
workspace (normal Docker credentials/configuration were preserved). Prior failed
reports remain intact; no failed artifact was marked successful.

Windows native, remote SSH integration, SCM/WebView2/reboot/recovery/UNC, real
Ubuntu baseline/systemd and physical-client acceptance remain pending. The current
Linux host uses glibc 2.41; compatibility checks are not target-distribution tests.
No pushes, Git tags, GitHub Releases, image pushes or Actions dispatches occurred.
The next phase can implement installation/lifecycle improvements; these package
results do not claim that the new installer requirements already exist.
