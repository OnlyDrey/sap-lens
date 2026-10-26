# Windows build performance

> Historical evidence: applies to the source/phase recorded below, not later
> commits. Use the [current documentation index](../../README.md) for instructions.

The Windows workflow remains manual. `scripts/build-windows.ps1` owns every build,
audit, test and packaging command. Its named stages let Actions expose individual
step durations; running it without `-Stage` runs the complete sequence, including
the packaged GUI smoke test. Individual stages assume their preceding stages have
completed; use the default full sequence for a standalone local build. Local Windows builds require Python 3.12, Node 24 and
PowerShell 7. User configuration and application behavior are unchanged.

Current workflow triggers, the newer 303-second Windows baseline and this implementation's unmeasured expectations are documented in [CI architecture](../../development/CI.md). The earlier benchmark results below remain historical measurements.

## Measurement

Each task records stopwatch seconds and its outcome in ignored
`backend/build/timings.jsonl`. One consolidated **SAP Lens — Windows Build Report**
combines those results with setup/cache/upload timestamps, version/source details,
package sizes, separate EXE/ZIP digests, audits and test stage status. Repeated
per-step tables and informational timing annotations have been removed. Partial
failures retain available records. The elapsed time at report excludes subsequent
post-job cleanup/cache saves; use the completed Actions run for final duration.
The manual **cold_cache** input disables npm/pip/Playwright cache restore/save.
See [packaging readiness](WINDOWS_PACKAGING.md) for verification and report limits.

The baseline is successful Windows run
[39469463871](https://github.com/OnlyDrey/sap-lens/actions/runs/39469463871),
commit `70a696e5415bc4495471da36b70ca3cd024e95ba`. Its job elapsed time was
**213 seconds**, including runner preparation and cleanup. Individual baseline
commands were not instrumented: the command figures below come from timestamped
logs or tool-reported durations and are approximate, rather than stopwatch
measurements. The initial ~four-minute figure was the user's observation.

## Changes and cache boundaries

- Cache only the official Playwright browser download directory. The exact key
  includes a namespace version, Windows platform, architecture and the complete
  frontend lockfile hash, which includes the locked Playwright version/browser
  revision. There are no fallback keys. Cache misses install normally; hits still
  run Playwright's installer to check that required components exist.
- Install Chromium with `--only-shell`: these tests use headless mode without a
  full-browser channel. Playwright selects its headless shell and required helper
  binaries; the unused full Chrome distribution is no longer downloaded.
- Retain npm/pip download caches and fresh isolated application environments. Do
  not cache installed Python environments, project executables, settings, test
  output or PyInstaller intermediates. Audit tooling is pinned separately and
  installed in the runner's host interpreter, outside the packaged environment;
  this removes the second virtual environment and its bootstrap.
- Install pinned build pip together with build/test dependencies. Simply removing
  the previous floating pip upgrade exposed vulnerable pip 25.0.1 from Python
  3.12's bundled environment: the trial build correctly failed its audit. The
  final build pins pip 26.2.2; audit failures are never ignored.
- `npm ci --no-audit --no-fund` removes the install's redundant advisory lookup;
  the explicit, blocking production JavaScript audit still runs. Known development
  advisories remain recorded in [security review](../../architecture/SECURITY.md).
- Upload the already compressed one-file EXE without additional ZIP compression.
  The same checksum and privacy/asset verification still precede upload.

## PyInstaller and validation decisions

Production packaging retains `--clean`. A manually selected **benchmark_packaging**
input runs an additional same-job incremental package after the clean package,
using the identical arguments and inputs. The resulting EXE must still pass full
asset/privacy/checksum verification and the native GUI/lifecycle smoke test. It
adds benchmark time and defaults to false. No intermediate executable is restored
from another run. Locally the equivalent option is `-BenchmarkPackaging`.

Cross-run PyInstaller caching would need to account for Python patch version,
PyInstaller/hooks versions, resolved Windows dependencies, source/assets, metadata,
frontend output, runner image and build implementation. Restoring executable
intermediates adds integrity and invalidation complexity. A same-job incremental
measurement is an upper bound on potential savings, not a cross-run cache result.

Fast Validation remains lightweight: backend/repository tests and frontend type
checks on every push/PR. Full Validation adds production/browser/security checks
for PRs targeting main. No automatic workflow packages an EXE. The manual
Windows workflow independently reruns every test/audit, including Windows-only
Python dependencies, production browser regressions, package verification and
native startup/duplicate-launch/port-conflict/shutdown tests. No CI result is
assumed or reused. A verified commit-result gate was not introduced: its policy,
permissions and fallback complexity are unnecessary for the small generic checks
and would not replace the Windows-specific coverage.

## Benchmark results

Final runs use the same code commit, `3defa1b479108784ffc2d6bab55a2b1b7f82129f`:

- **Cold:** [39543707145](https://github.com/OnlyDrey/sap-lens/actions/runs/39543707145),
  `cold_cache=true`: cache actions disabled and empty job-local npm/pip/browser
  directories. All checks passed.
- **Warm:** [39543711043](https://github.com/OnlyDrey/sap-lens/actions/runs/39543711043),
  normal cache settings. Existing npm/pip caches and the exact Playwright cache
  were accessed; the browser cache's last-access timestamp and installer timing
  confirm reuse. All checks passed.

Seconds below are measured, except approximate baseline command intervals marked
`~`. Workflow elapsed includes queue/provisioning; job elapsed excludes the initial
queue. Setup/cache/upload timings come from second-resolution Jobs API timestamps;
command timings come from stopwatches. Rows are not a sum: totals include shell,
metadata, summaries, cache-save and cleanup overhead.

| Metric | Baseline | Final cold | Final warm |
|---|---:|---:|---:|
| Workflow elapsed (dispatch to completion) | 223 | 236.00 | 195.00 |
| Windows job, including cleanup | 213 | 231.00 | 190.00 |
| Environment setup / checkout / tool actions | 37 | 24.00 | 35.00 |
| npm installation | ~14 | 17.55 | 9.80 |
| Frontend compilation | ~7 | 9.64 | 7.68 |
| Python environment creation | ~5 | 7.23 | 3.64 |
| Python dependencies (includes secure pip) | ~13 | 17.79 | 8.87 |
| Audit tooling (includes old audit venv bootstrap) | ~9 | 11.32 | 6.54 |
| Python vulnerability audit | ~2.6 | 3.01 | 3.61 |
| Production JavaScript audit | ~0.8 | 0.85 | 1.45 |
| Backend tests | 14.43 | 16.18 | 16.62 |
| Playwright cache restore | 0 | 0.00 | 4.00 |
| Playwright installation | ~18.3 | 9.52 | 3.01 |
| Playwright tests (11 baseline / 17 final) | 23.1 | 36.94 | 25.79 |
| PyInstaller (clean) | 22.44 | 24.37 | 17.24 |
| Package verification + checksum | <1 | 0.32 | 0.23 |
| EXE smoke test | 34 (job step) | 31.43 | 28.26 |
| Artifact upload | 3 | 3.00 | 2.00 |

The final warm workflow took **3:15**, compared with the baseline **3:43** (28
seconds less); its job took **3:10**, compared with **3:33** (23 seconds less).
The completely cold workflow took **3:56**, with a **3:51** job. The target of
less than two minutes was **not achieved**.

Warm Playwright setup was **7.01 seconds including its four-second cache restore**,
compared with approximately 18.3 seconds before. Cold headless-only installation
was 9.52 seconds. These directly measure browser setup; PyInstaller and GUI startup
still run normally and their timing differences must not be attributed to caching.
The final 17-case browser suite also performs more isolated setup than the original
11-case suite.

Runner/network variation is substantial. Earlier successful exploratory jobs took
185 seconds with a cold browser cache (including the optional packaging benchmark),
182 seconds warm and 234 seconds warm, before the test-isolation fix. Those runs
are [39542266182](https://github.com/OnlyDrey/sap-lens/actions/runs/39542266182),
[39542589368](https://github.com/OnlyDrey/sap-lens/actions/runs/39542589368) and
[39542758590](https://github.com/OnlyDrey/sap-lens/actions/runs/39542758590).
These are single samples, not a guaranteed total-duration improvement or a
statistically controlled comparison. No estimate is presented as a measured result.

The opt-in same-job PyInstaller experiment in run 39542266182 measured **19.29
seconds clean versus 0.64 seconds incremental**. Cross-run cache restore/save was
not tested or enabled; those savings cannot be claimed for a persistent cache.

### Storage and remaining opportunities

The new browser cache occupies **122,265,776 bytes (116.60 MiB)** per platform,
architecture and lockfile key. The current pip download cache is **26.88 MiB**
(previous key: 26.13 MiB), and the existing npm cache is **30.65 MiB**. The new pip
key temporarily coexists with its old entry until normal cache eviction. No
installed environments, build intermediates or project executables are cached.

The remaining serial costs are frontend/Python installation and compilation,
audits, backend/browser regressions, clean packaging and repeated native GUI
startup/shutdown. Artifact upload is already only 2–3 seconds. Further work should
benchmark parallel independent preparation/validation stages and potentially a
faster Windows runner. Persistent PyInstaller caching needs a complete resolved
Windows dependency/input identity and integrity review before adoption. Skipping
Windows tests or changing the single-EXE distribution format is not part of this
optimization.

### Validation before delivery

Before the latest code push, local validation passed: **65 backend tests**, **17
Playwright cases**, the production TypeScript/Vite build, `pip check`, the Python
installed-environment audit, production npm audit and `actionlint`. The full local
npm audit separately reports the existing seven development advisories described
below. The protected README is unchanged byte for byte.

Both final Windows runs passed the full security audits, backend/browser tests,
clean PyInstaller package, SHA-256/asset/privacy verification and native EXE smoke
suite. Each verifier reported 132 archive entries and the expected product assets.
The standard validation workflow for the tested code commit also passed:
[39543705864](https://github.com/OnlyDrey/sap-lens/actions/runs/39543705864).
Branch: `work`. Final documentation delivery adds no runtime/build changes after
these measured runs; the delivery SHA is recorded in the final handoff.

## Regression reliability and remaining limits

The cold-cache trial exposed a pre-existing browser-test race: the header's
**Open settings** button remains clickable during the asynchronous save; reopening
before `onClose` runs can leave the settings closed when the test looks for a tab.
The regression now waits for the saved settings to close before reopening. The
same test also shared one 30-second budget across six screenshot/viewport/theme
cases; those cases now run independently. The suite grows from 11 to 17 tests,
retaining all six light/dark viewport combinations, screenshots and layout checks.
Timeouts and the zero-retry policy are unchanged. No application code was changed.

Earlier exploratory runs are not successful benchmark samples when an audit or
test failed. One audit trial correctly rejected Python's bundled vulnerable pip;
subsequent builds use the pinned secure version. Browser failures led to the
explicit save synchronization and isolated visual cases above, rather than retries
or weaker assertions. The additional test setup means final browser timings should
not be presented as a reduction against the earlier 11-test suite.

Full production npm and Windows Python audits remain blocking. A separate local
full npm audit still reports the existing seven development-only advisories
(five high, two moderate) in the Tailwind 3 toolchain; no production JavaScript
advisories were reported. Addressing those requires a separate, validated toolchain
upgrade; no advisory ignore list was introduced for this performance work.

Native Windows packaging/GUI lifecycle checks run in Actions. This Linux environment
cannot run the Windows EXE/WebView2 itself. Explorer launch, native file dialogs,
SmartScreen/signing policy and a clean target PC remain manual acceptance checks.
GitHub redirected detailed logs to changing Azure storage hosts blocked by the
cloud network policy; timing/test/package annotations and the Jobs API provided
measurement and failure evidence. The saved environment draft adds the observed
`productionresultssa0.blob.core.windows.net` host; publishing that draft is still
required for persistent access, and other redirected hosts may need explicit access.

The benchmark numbers above are historical measurements for commit `3defa1b`, not
new measurements of subsequent settings/icon-catalog or packaging-hardening work.
Artifact download/reverification adds work, and the current frontend/test suite is
larger. No current Windows duration or speedup is claimed without a native run.

## CI architecture baseline and implementation record

## Baseline and intent

Inspected branch `work` at local commit
`cd4921e558932d9dee0ceed97b4527262bf9f5a0`, clean working tree. Remote `work`
remained at `733e5dadef9b92ad430824d012a6c5d491dbe43e`; the local transport
maintenance commit was preserved. No push, dispatch, release or repository
settings change is part of this implementation.

Previously there were two workflows: Validate application (pushes restricted to
main/work, PRs restricted to main, plus manual dispatch) and Build Windows
application (../../development/manual). Validation ran one sequential Linux job. Windows ran one
job with all build/test/audit/lifecycle/artifact checks. There was already exactly
one npm install and production frontend compilation per Windows build; the
packager consumes that same output and the verifier compares its bytes.


## Measured baseline and unmeasured expectations

Measured from successful source `733e5da…`, not from the new workflows:

| Stage | Windows run 39618620170 | Validation run 39618607839 |
| --- | ---: | ---: |
| Wait before job start (includes scheduling/provisioning) | 4 s | 53 s |
| Job setup / checkout | 3 / 9 s | 4 / 4 s |
| Node / Python setup, including cache work | 10 / 7 s | 17 / 10 s |
| Browser-cache configuration / restore | 1 / 3 s | — |
| Python venv creation / dependencies | 10 / 14 s | no venv / 9 s |
| npm install / frontend compilation | 23.45 / 13.88 s (39 s step) | 9 s / none |
| Python audit tooling / vulnerability check | 9.24 / 3.48 s | none |
| Backend tests | 18 s step | 8 s step |
| Browser setup / tests / production npm audit | 9.91 / 67.32 / 1.38 s (79 s step) | no browser / 1 s audit |
| Frontend explicit type check | included in build | 4 s |
| PyInstaller / package verification | 35 / 3 s | — |
| Packaged EXE smoke | 37 s | — |
| Artifact upload / download / revalidation | 4 / 2 / 3 s | — |
| Consolidated report | 6 s | none |
| Complete job / dispatch-to-completion | 303 / 308 s | 71 / 124 s |

Step figures are GitHub timestamps rounded to seconds; finer command figures
are existing stopwatch logs. Setup steps overlap their cache operations, so do
not add cache time twice. Queue time cannot be cleanly separated into runner
startup versus capacity from these timestamps.

No updated workflow has been dispatched: no measured speedup, cold/warm result
or target achievement is claimed. Parallel Full jobs should remove serial
backend work from the frontend critical path. Linux browser caching should save
downloads on hits; system library provisioning still costs time. Direct use of
the installed Playwright CLI avoids npx resolution, and parallel metadata API
requests may trim part of the six-second report cost. These are expectations,
not measured savings. Fast's added lint/contracts may offset moving audit work
to Full. Under 60 s Fast, 1–2 min Full and 3–4 min Windows remain aspirations.
Windows browser tests, frontend compilation and native smoke remain bottlenecks;
cross-run PyInstaller caching, DLL pruning and splitting Windows across runners
were rejected without evidence of safe net benefit.

Additional cache storage is one Linux Playwright headless-browser cache per
platform/architecture/lockfile key, besides the existing Windows/npm/pip caches;
its actual size/hit rate remains to be measured. No new mutable build cache.

## Local validation and next native checks

Completed locally on 2026-10-21: 108 backend/repository tests with deprecations
as errors, all 30 browser tests (5.8 minutes, one worker, zero retries), npm ci,
type check, production build, icon-catalog check, pip check, Python audit and
production npm audit, actionlint 1.7.12, trigger/policy contracts, PowerShell
parser/static guards and existing timing/error-preservation checks, metadata
generation and git diff/integrity checks. All passed. The exact Full Backend
requirement combination was also installed in a fresh isolated Linux virtualenv;
pip check, its installed-environment audit and all 108 tests passed there too.

The validated source/build/test/workflow patch SHA-256 (documentation excluded)
is `420d10d311c339b51c6480e5345fa1137124ef4662a489e0e7291644fcfc4fa0`.
Existing seven Tailwind development advisories remain; production audits report
zero. Read-only-home cache warnings and NO_COLOR/FORCE_COLOR messages in this
cloud are environmental. The negative timing tests deliberately emit warnings.
No updated GitHub workflow or native Windows validation was executed.

Changed implementation files and purpose:

| Paths | Purpose |
| --- | --- |
| `.github/workflows/validate.yml`, `.github/workflows/full-validation.yml`, `.github/workflows/build-windows.yml` | Exact three-workflow trigger/job/cache/concurrency/coverage policy |
| `scripts/ci.py` | Timed command execution, accurate validation summaries, checksum-pinned actionlint |
| `scripts/check-workflows.py`, `scripts/check-powershell.ps1` | Offline CI contracts and PowerShell syntax/static guards |
| `scripts/build-windows.ps1`, `scripts/verify-artifact-zip.py` | Canonical raw-ZIP verification, strict backend deprecations and installed Playwright CLI |
| `scripts/write-build-report.py` | Descriptive job recognition, incomplete-state handling and parallel metadata reads |
| `backend/requirements-dev.txt` | Test-only YAML parser pin |
| `backend/tests/test_workflows.py`, `backend/tests/test_ci_report.py`, `backend/tests/test_artifact_zip.py`, `backend/tests/test_build_report.py` | Positive/negative regression contracts for new orchestration and reporting |
| `docs/development/CI.md`, `docs/archive/validation/BUILD_PERFORMANCE.md`, `docs/architecture/DESKTOP.md`, `docs/archive/validation/VALIDATION.md`, `docs/development/DEPENDENCY_MAINTENANCE.md` | Architecture, measured baseline and current workflow references |

Run the complete documented [local suite](VALIDATION.md), including:

```sh
python scripts/check-workflows.py
python scripts/ci.py lint
pwsh -NoProfile -File scripts/check-powershell.ps1
python -W error::DeprecationWarning -m unittest discover -s backend/tests -v
```

The suite uses synthetic data only. Native Windows/WebView2 lifecycle, the
Windows-only dependency audit, official raw-ZIP round-trip integration and
actual cold/warm updated workflow timings require real runners. Linux tests
cannot establish those results. The artifact action still bundles the upstream
DEP0005 dependency; raw download no longer invokes that extractor, but no upstream
fix or suppression is claimed. See [deprecation maintenance](../../development/DEPENDENCY_MAINTENANCE.md).

After explicit approval, push the finished branch and select Actions → Build
Windows Application → Run workflow → work (normal benchmark inputs false).
One manual Windows run should verify the complete pipeline and report. A PR
targeting main is separately needed to measure Full Validation and its two
required jobs; do not add a manual Full trigger to sidestep that policy.
