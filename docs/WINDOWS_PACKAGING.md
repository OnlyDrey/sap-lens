# Windows packaging hardening and readiness

For current build/beta/stable modes and publication safeguards, see
[manual Windows releases](RELEASES.md). The hardening findings below record their
original implementation baseline.

## Current version metadata

The workflow resolves the full build identity before packaging, reserving beta/
stable tags early in a separate privileged job. The Windows build remains
read-only. Generated ignored backend/build/build-version.json is bundled once at
the EXE resource root; runtime, UI/API, PE resources and release naming consume
that identity. No tracked source is rewritten. Source fallback is 0.0.0-dev.local.

ProductVersion retains the full beta/dev suffix; FileVersion uses a numeric
four-component tuple (0.1.0-beta-1 → 0.1.0.1; stable → 0.1.0.0). Numeric dev
revisions are bounded by PE limits; full version strings remain distinct.
FileDescription/ProductName are SAP Lens. Signing is unchanged and disabled.
The existing package verifier now checks embedded JSON and the version runtime
module, and the native smoke test checks the actual health/API version against
the generated identity. All previous archive/privacy/asset/checksum checks remain.
See [release/recovery rules and PE limitations](RELEASES.md).

The remaining findings below record the earlier hardening baseline; references
to a hardcoded version constant or no publication predate workflow-driven versions.

## Baseline and decision

**IMPROVE CURRENT PACKAGING.** Retain Python/FastAPI, React/Vite, pywebview/WebView2,
PyInstaller and the existing `backend/desktop.py` entry point. One-file remains the
default; settings remain outside the executable in per-user application data.
Local paths and permitted network shares, development `.env` configuration,
classification semantics and runtime security boundaries are unchanged.

This task started on `work` at `04f5af3565f51067980d0491d6a4f470c26c0a2d` with a
clean tree. Fetching remote `work` returned
`3defa1b479108784ffc2d6bab55a2b1b7f82129f`; existing local-only commits were retained.
The baseline backend suite passed **68 tests**. The previous local settings/role
work had passed 28 browser cases; this task reruns them rather than assuming that
record proves the packaging changes.

There is no native Windows runner attached to this Linux session. No remote build
was authorized or started. A read-only attempt to download the historical Windows
artifact (run `39543711043`, artifact `12320229105`) was blocked at the storage
redirect by network policy. Its API metadata reported a 24,156,546-byte artifact;
that is historical metadata, not a measured size for this change. The current
one-file binary's actual archive contents and DLL inventory could not be inspected.
Do not infer an archive inventory from the earlier verifier's entry count alone.

## Confirmed findings and implementation

| File | Finding and change |
|---|---|
| `scripts/build-windows.ps1` | Canonical build retained; explicitly adds `--noupx`, records timings without repeated Markdown tables/notice annotations, resets stale local timing/report records at Environment, and owns downloaded-artifact verification |
| `scripts/verify-windows-package.py` | Adds strict x64/PE32+/GUI header guards, version/icon/manifest checks, raw duplicate detection, privacy/development input checks, complete production frontend byte comparison, nested archive readability, distribution shape and round-trip hash checks |
| `scripts/write-windows-metadata.py` | Exposes the same approved metadata to the writer and verifier; `backend/version.py` remains authoritative; no new publisher identity |
| `scripts/write-build-report.py` | Creates one report with one stage timing table, metadata/checksums/sizes, setup/cache/upload timings and partial failure results; API/report formatting failures cannot waive package verification |
| `.github/workflows/build-windows.yml` | Keeps manual dispatch, SHA-pinned actions and read-only permissions; uploads two verified files, downloads that artifact by this run's returned ID, revalidates it against the original EXE digest, then produces the consolidated report |
| `backend/tests/test_windows_package.py` | Synthetic positive/negative verifier cases, actual PyInstaller archive reader/writer regression, and a PE-resource parser adapter fixture |
| `frontend/playwright.config.ts` | Consistent bounded fixture/workflow budget; default assertion timeouts and zero retries retained |
| `frontend/tests/enterprise.spec.ts`, `frontend/tests/role-visuals.spec.ts`, `frontend/tests/settings-refinement.spec.ts` | Isolate long UI scenarios and asynchronous/brief feedback checks without changing app behavior, assertion coverage or retries |
| `backend/tests/test_desktop.py` | Repeated-launch test waits for the real load-URL event within the existing supported startup window, avoiding premature mock-window closure |
| `backend/tests/test_build_report.py` | Successful/failed/incomplete stage reporting, timing corruption, escaping, distinct digest scopes and API timeout fallback |
| `docs/DESKTOP.md`, `docs/BUILD_PERFORMANCE.md` | Distribution, integrity, reporting and verification boundary updates |
| `docs/WINDOWS_PACKAGING.md` | Baseline, findings, verification boundaries, validation record and delivery limitations |
| `docs/WINDOWS_CODE_SIGNING.md` | Documentation-only eligibility, publisher, provider/cost limitations and protected signing plan |

The previous script checked a GUI subsystem offset but not x64 machine/magic or
complete resource metadata. Converting archive names directly to a set concealed
duplicates and only caught exact `.env`, settings/runtime JSON, CSV and log names.
It did not compare the full compiled frontend or downloaded bytes. These are
verified source findings, not claims that a historical artifact contained secrets.

UPX was previously implicit: PyInstaller could use it if available. Whether it was
actually present in a historical runner was not established. `--noupx` makes the
new policy explicit; native size/startup effects remain to be measured. No Python
module or DLL exclusion was added without a native inventory and regression proof.
No new runtime or declared build dependency was introduced: `pefile` is already a
Windows dependency of PyInstaller; the verifier uses it only during packaging.

## Verification contract and limits

The unsigned verifier requires:

- Exactly `SAP-Lens.exe` and `SAP-Lens.exe.sha256` in the distribution directory;
  regular nonempty files, an exact SHA-256 manifest and an optional original digest.
- Valid bounded PE headers, AMD64 (`0x8664`), PE32+ and Windows GUI subsystem.
- ProductName, FileDescription, FileVersion, ProductVersion, OriginalFilename,
  InternalName and the approved CompanyName, including matching fixed versions.
- One version resource, one icon group, icon payloads matching `assets/sap-lens.ico`,
  and one `asInvoker` manifest without UI-access elevation. The current unsigned
  workflow rejects an unexpected Authenticode certificate table.
- A readable CArchive with bounded entries and a valid table, checked for duplicate
  names **before** the PyInstaller reader converts them to a dictionary. Windows
  case/slash aliases, traversal and absolute paths are rejected.
- Required product assets, Python runtime, WebView libraries, desktop entry point,
  embedded API/WebView modules and frontend JavaScript. Every generated frontend
  file, including lazy icon chunks, must match the bundled names and bytes.
- Readable/decompressible members, Python PYZ modules and the standard-library ZIP.
  Python bytecode is inspected/deserialized, never executed by the verifier.
- No `.env` variants, known credentials/private-key files, user configuration,
  SAP CSVs, logs including rotated logs, test/fixture directories, `node_modules`,
  caches, source maps, PDBs, development source/configuration or unexpected helper
  executables/scripts. Legitimate packaged DLLs and the public `certifi/cacert.pem`
  trust store remain permitted; generic JSON assets are not broadly forbidden.

The package report lists archive names, embedded module names, counts and potential
build-only modules for review. Test-only `httpx`, pip, pytest and PyInstaller are
review candidates if found, rather than guessed exclusion rules. PyInstaller
packages dependencies reached through analysis/hooks, not every package installed
in its environment. Python's stdlib ZIP/bytecode, .NET/WebView loaders, Pillow/regex
extensions and application modules must not be pruned based solely on filenames.
Actual DLL necessity and development-module inclusion require the next native
inventory. There are no speculative size or antivirus-driven exclusions.

Text assets are checked for selected private-key/token signatures without printing
matches. **This is not complete secret detection, antivirus scanning, provenance
attestation or a complete audit of compiled bytecode/DLL strings.** Use clean,
reviewed build inputs; do not introduce production exports, branding or private
`.env` values into a build checkout. A checksum from the same unsigned download
shows byte consistency, not a trusted publisher identity.

## Artifacts and report

GitHub supplies the only distribution ZIP. There is no additional ZIP layer.
The executable is already internally compressed, so upload compression remains 0;
retention remains 14 days, missing files are errors, and only the two named files
are uploaded. Failure diagnostics remain separate, synthetic and short-lived.

The maintained SHA-pinned download action performs its supported artifact-digest
validation. The subsequent blocking verifier also compares the downloaded EXE to
the digest recorded **before upload**. A self-consistent but changed EXE/manifest
pair cannot pass that comparison. Both files and native package contents are
reverified. An artifact may exist on a failed run; distribute only after the entire
workflow, including round-trip verification, succeeds.

The report distinguishes the **GitHub artifact ZIP SHA-256** from the
**SAP-Lens.exe SHA-256**. It includes artifact size when the API supplies it,
application/source/runtime details, test/audit stage results, unsigned status and
one consolidated stage table. Stopwatch records are written in `finally` blocks.
Interrupted records retain earlier completed tasks; partially completed stages do
not become “Passed.” Setup/cache/upload timestamps supplement local timings.

At report time the job has not completed post-job cleanup/cache saves. The summary
therefore labels elapsed duration **at report**, from the run start when available,
and does not pretend it is a measured final workflow duration. The completed
Actions run remains authoritative. Timing API/report-formatting failures emit a
warning and retain available local results; package verification failures remain
blocking. Local `pwsh -NoProfile -File scripts/build-windows.ps1` still invokes the
canonical complete build without requiring GitHub or a downloaded artifact.

## One-file versus one-folder

One-file preserves the existing single-EXE deployment contract. A one-folder
benchmark was **not run** because native Windows/WebView2 execution is unavailable.
Do not replace the default based on Linux archive timings or estimated antivirus
benefits. The existing incremental PyInstaller benchmark remains a separate opt-in
cache experiment, not a packaging-format comparison.

A controlled future native comparison must reuse the same commit, Windows runner,
resolved Python dependencies, frontend and metadata. Record unpacked distribution
size, compressed transfer size and several cold/warm startup samples. Test WebView2
resources, CSV picker/local and permitted UNC paths, network failures, settings
persistence, metadata/icon, single instance and shutdown for both outputs. Account
for every required file and the operational cost of keeping a folder intact. Keep
one-file unless a measured meaningful gain survives the full comparison.

## Signing and remaining validation

See [Windows code signing readiness](WINDOWS_CODE_SIGNING.md). Signing remains
unconfigured and no provider enrollment, credentials or signing attempt occurs.
A future signed-release policy must explicitly extend the unsigned verifier's
signature policy and verify the expected publisher before generating final hashes.

Pending Windows-only validation: native PyInstaller build, actual PE/resource and
complete DLL/module inventory, EXE smoke/lifecycle tests, real WebView2, artifact
round-trip execution, clean-PC launch, picker/network-share behavior, settings
upgrades, Explorer branding/DPI and download/endpoint-policy behavior. Static YAML
and PowerShell checks and Linux synthetic tests do not establish those outcomes.

## Regression reliability and test limits

Import mapping, classification preview and registry customization now have separate
independent UI scenarios. All original mapping, display/color/icon, relationship,
transaction, domain and persistence assertions remain. Role-visual cases seed the
same synthetic saved settings through the guarded API rather than repeating an
unrelated import wizard. Icon search waits for its lazy control to be interactive.

Brief clipboard feedback is captured by a DOM observer explicitly installed before
input, including its visible bounds. Exact clipboard contents, keyboard/click
interaction and message expiry remain asserted. No application timer is extended
or frozen. The repeated-launch backend fixture waits for the actual load-URL event
before checking the live HTTP session and closing its mock window. Production
readiness/shutdown deadlines and capability/identity/cleanup assertions are intact.
Its 17-case lifecycle suite passed three consecutive runs (51 executions); native
GUI/Windows boundaries are mocked, so this is not Windows acceptance.

Local traces showed aggregate 30- and 60-second limits expiring during fixture
startup or at the end of otherwise valid complete workflows. The browser project
now uses a **120-second aggregate E2E budget**, including fixtures. Assertions keep
the default five-second limit and retries remain zero. This bounded test-runner
allowance is a performance/validation limitation, not evidence of fast Windows
startup. Earlier failed/incomplete attempts are not counted as passes. One local
run was invalidated by overlapping trace output; final validation is serialized
with an external single-run lock and separate targeted output directories.

## Dependency inspection follow-up

The installed pywebview 6.2.1 distribution contains WebView2 managed assemblies,
three architecture-specific loader DLLs, legacy WebBrowserInterop DLLs and
`pywebview-android.jar`. Its bundled hook collects `webview/lib` data and dynamic
libraries on Windows, plus shared JavaScript resources. The CLR-loader hook also
collects its Windows .NET loader DLLs. These are inspected package/hook source
facts, not a claim that the blocked historical EXE was fully inventoried.

The Edge renderer references the Core/WinForms WebView2 assemblies and adds all
three loader locations to the search path. Android JAR and legacy/foreign-
architecture resources are candidates for a narrowly scoped future packaging
review. Their actual collection and the effect of removing them must be checked
on Windows before exclusions are introduced. No speculative hook override or DLL
pruning is included in this change.

## Known dependency warnings

At the packaging baseline, dependency manifests and lockfiles were unchanged. The full npm audit
reports seven existing development-only advisories (five high, two moderate) in
the Tailwind 3 toolchain. They are reported rather than suppressed; the separate
production-only audit remains blocking. A future toolchain migration needs its
own compatibility validation. The baseline Starlette TestClient transport warning
and the official artifact action's upstream Node warning are tracked in
[Deprecation maintenance](DEPRECATIONS.md). Windows-only Python dependencies still
require the canonical Windows audit, not an inference from Linux packages.


## Final local validation record

All required available checks completed on the final source without edits during
the run. The validated build/test/workflow patch SHA-256 (excluding documentation)
is `6af5c0fe94c321ae1a377612da6821d24d837d79944e3075abe8f82c18de5655`.
No application source, protected README, canonical PNG/ICO, dependency manifest or
lockfile changed in this task.

| Executed command/check | Final result |
|---|---|
| `git diff --check`, `git diff --cached --check` | Passed |
| `actionlint` | Passed |
| PowerShell 7.6.7 parser on both build/smoke scripts | Passed |
| Actual PowerShell timing function: success, failure, blocked timing destination | Passed; failed actions remain failures and log-only failures remain nonfatal |
| `.venv/bin/python scripts/write-windows-metadata.py` | Passed; generates authoritative version metadata text, not a native PE |
| `npm --prefix frontend ci --cache /workspace/.npm-cache` | Passed |
| `node scripts/sync-lucide-catalog.mjs --check` | Passed |
| `npm --prefix frontend run check:types` | Passed |
| `npm --prefix frontend run build` | Passed |
| `.venv/bin/python -m unittest discover -s backend/tests -v` | **84 passed**, including 14 package-verifier and five report tests |
| `.venv/bin/python -m pip check` | Passed |
| Python installed-environment vulnerability audit | Passed; no known vulnerabilities in the audited Linux environment |
| `npm --prefix frontend audit --omit=dev` | Passed; zero production advisories |
| `npm --prefix frontend audit --json` | Seven existing development advisories, recorded above |
| `PLAYWRIGHT_EXECUTABLE_PATH=/usr/bin/chromium PATH=/workspace/sap-lens/.venv/bin:$PATH npm --prefix frontend run test:browser -- --reporter=line,github` | **30 passed (9.3 minutes)**; one worker, zero retries, the documented aggregate budget |

The isolated audit command was:

```sh
/workspace/sap-lens-dev/audit-venv/bin/python -m pip_audit --path /workspace/sap-lens/.venv/lib/python3.12/site-packages --cache-dir /workspace/.pip-audit-cache --progress-spinner off
```

PowerShell tooling was downloaded outside the repository from Microsoft's official
GitHub release and checked against its published SHA-256 before use. Linux parser
and timing-function checks used an isolated local fixture; no Windows build was
executed. The canonical Windows build, real PE parser/resource verification,
packaged smoke test, WebView2, artifact round trip and one-folder comparison remain
**pending**, not passed. The historical artifact's blocked download and unverified
CA pricing/eligibility alternatives remain explicit limitations.

Delivery is a local commit on `work`, with its SHA in the handoff. No push, GitHub
build, signing attempt or release publication was performed. The repository's
[pre-push policy](../AGENTS.md) requires explicit approval before pushing while
required Windows validation remains unavailable.

### CI verifier import failure (run 39751089179)

The beta attempt at source `92e15942a7c2c0aeb23ada1ab35d468312bc1656`
failed before PE parsing: direct execution of `scripts/verify-windows-package.py`
with `GITHUB_ACTIONS=true` imported `version` before adding `backend` to the
Python search path. This raises `ModuleNotFoundError`; the previous generic
exception handler hid the category. Unit tests had already added that directory
and therefore missed the standalone-process failure. The verifier now establishes
its own source import path, and a subprocess regression supplies synthetic
`0.1.0-beta-1` metadata without an inherited `PYTHONPATH`.

Failure diagnostics identify the verification phase, an allowlisted exception
category and a bounded cause category. Third-party messages, traceback filenames,
archive member names and contents remain withheld. Policy rejections retain their
application-authored, value-free reason. No verification rule is relaxed.

The failed run logged full product version `0.1.0-beta-1` and numeric PE version
`0.1.0.1`. Its executable was not uploaded, so actual PE resources cannot be
inspected from that run; neither malformed resources nor parser incompatibility
has been established. Synthetic archive/resource tests are not native Windows
validation. A newly authorized Windows build must still exercise PE parsing,
packaged startup and artifact integrity end to end.

Read-only inspection confirmed `v0.1.0-beta-1` points to that source commit and
there was no GitHub release. The reservation remains intact. The next independent
beta allocation for base `0.1.0` ordinarily selects `v0.1.0-beta-2`; do not delete,
move, reuse or blindly rerun the reserved beta-1 attempt.

Local validation of this fix (Linux): `git diff --check`,
`.venv/bin/python scripts/ci.py lint`,
`.venv/bin/python scripts/check-workflows.py`, PowerShell 7
`-NoProfile -File scripts/check-powershell.ps1`, `npm --prefix frontend ci`,
`node scripts/sync-lucide-catalog.mjs --check`, frontend `check:types` and `build`,
`.venv/bin/python -W error::DeprecationWarning -m unittest discover -s backend/tests -v`
(**180 passed**), `.venv/bin/python -m pip check`, the installed-environment
Python audit above (no known vulnerabilities), `npm --prefix frontend audit --omit=dev`
(zero vulnerabilities), and Playwright with system Chromium (**42 passed**) all
passed. Full npm auditing still reports seven existing development advisories
(five high, two moderate); dependencies were not changed. Synthetic package tests
still reject bad resources, corrupt archives, unexpected files and checksum
mismatches. Native Windows/PE/WebView2 execution remains pending. No remote build,
tag/release mutation or push was performed during this fix.
