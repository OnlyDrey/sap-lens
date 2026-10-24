# CI architecture

## Temporarily skip automatic CI

For a push that should not consume Actions minutes, put **`[skip ci]`** in its
commit message. GitHub supports this for `push` and `pull_request` workflows;
no YAML edit, repository setting or dependency change is needed.

```powershell
# After completing and locally validating the intended changes:
git add <intended-files>
git commit -m "Describe the finished change [skip ci]"
git push origin work
```

For a push, GitHub checks the messages of the commits included in that push.
For a pull request, the skip instruction must be in the PR's HEAD commit message.
Do not rewrite already published commits just to add this marker. If the intended
work is already committed locally, a real documentation change with `[skip ci]`
in its new HEAD commit can accompany it. Inspect the branch, clean status and
remote ancestry before pushing; never force-push to bypass remote changes.

**Resume:** make the next normal commit without a skip marker and push it.
No reactivation or YAML change is needed. Ensure that this new push does not
include other unpublished commits containing a skip instruction. The marker
remains in history but does not permanently disable a workflow.

Important boundaries:

- Skipping CI is not a passing validation. Run the applicable local checks first.
- Required PR checks can remain **Pending**, blocking merge. Do not remove branch
  protection; submit a normal commit when CI is available again.
- This does not cancel already queued/running workflows.
- Manual `Build Windows Application` remains available. A skip marker does not
  prevent an explicit manual dispatch, and no build should be dispatched while
  avoiding Actions usage.
- This applies to the current push/PR validation workflows; it is not a general
  switch for other GitHub automation or all event types.

For a longer pause, an administrator can open **Actions → the selected workflow →
… → Disable workflow** in GitHub, then use **Enable workflow** on the same page to
resume. Disable both Fast Validation and Full Validation if both should pause.
That changes remote workflow state and requires explicit authorization; it is
not performed by the local build scripts or by adding this documentation.
Re-enable before relying on required checks, then submit a normal commit/event.

The supported local alternative, including prerequisites, all four modes,
artifact paths and native Windows QA, is documented in
[Local Windows builds](LOCAL_WINDOWS_BUILD.md):

```powershell
.\scripts\build-local.ps1 -Mode Quick
.\scripts\build-local.ps1 -Mode Validate -Version 0.1.0
.\scripts\build-local.ps1 -Mode Build -Version 0.1.0
.\scripts\build-local.ps1 -Mode Package -Version 0.1.0
```

## Baseline and intent

Inspected branch `work` at local commit
`cd4921e558932d9dee0ceed97b4527262bf9f5a0`, clean working tree. Remote `work`
remained at `733e5dadef9b92ad430824d012a6c5d491dbe43e`; the local transport
maintenance commit was preserved. No push, dispatch, release or repository
settings change is part of this implementation.

Previously there were two workflows: Validate application (pushes restricted to
main/work, PRs restricted to main, plus manual dispatch) and Build Windows
application (manual). Validation ran one sequential Linux job. Windows ran one
job with all build/test/audit/lifecycle/artifact checks. There was already exactly
one npm install and production frontend compilation per Windows build; the
packager consumes that same output and the verifier compares its bytes.

## Workflows and checks

| Workflow / file | Exact triggers | Jobs and responsibility |
| --- | --- | --- |
| Fast Validation / `.github/workflows/validate.yml` | Every push (including all branches/tags); every pull_request with no branch/path filters | Backend & Frontend: all existing backend/repository tests, deprecations as errors, pip consistency, workflow contracts/actionlint and frontend type checks |
| Build Deployment Packages / `.github/workflows/build-deployments.yml` | workflow_dispatch only; platform selector and All | Shared Validation & Frontend, followed by independent Desktop, Service, Docker and native packaging jobs |
| Full Validation / `.github/workflows/full-validation.yml` | pull_request targeting main only; no push/manual/tag/release trigger | Backend & Repository and Frontend & Browser run independently in parallel |
| Build Windows Application / `.github/workflows/build-windows.yml` | workflow_dispatch only; caller selects branch/ref | Optional Reserve Release Version job before Windows Build & Verification; optional dependent Publish Verified Windows Release job for explicit beta/stable mode |

Full Backend installs test, build and audit requirements, checks dependencies,
runs the entire backend suite (including the real synthetic PyInstaller archive
fixture), workflow validation, repository integrity/privacy, PowerShell parsing
and static safety guards, and audits the installed Python environment. Audit
tooling shares this disposable Linux validation environment; it is never used
to package an application. Windows audit tooling remains outside its isolated
package environment and audits the complete installed Windows dependency set.

Fast retains the previous full unittest discovery policy. As in the measured
baseline, the build-only real PyInstaller fixture is skipped when PyInstaller is
not installed; this is visible in the report. Full and Windows install it and
exercise that fixture. No existing tests are removed. New tests cover workflow
trigger matrices and rejected policy changes, job cycles, reporting failures and
raw ZIP tampering/member/extraction safety. Deprecations fail backend validation.

Full Frontend installs runtime Python dependencies for the synthetic browser
server, runs npm ci once, type checking, icon-catalog validation, one production
build, a production npm audit and the complete browser regression suite. Canonical
`npm run build` retains its own TypeScript check; the explicit type-check step
provides earlier failure visibility. No second Vite compilation occurs. Browser
workers, zero retries, test deadlines and application code remain unchanged.

There is no separate frontend component-unit framework; the production browser
suite provides the existing interaction regression coverage. Fast deliberately
does not run a production build, browser install or security-feed lookup.
Audits remain blocking in Full and the independent manual Windows build.

## Caching, parallelism and concurrency

- Official setup actions cache npm/pip downloads, keyed by the frontend lockfile
  and Python requirement files respectively. Python/Node versions are fixed to
  3.12/24. No full virtualenv, node_modules, user data, frontend output, executable
  or PyInstaller intermediate is cached.
- Playwright caches only its official download directory in runner temp. Exact
  keys include namespace, runner OS, architecture and frontend lockfile (which
  locks Playwright/browser revision). No fallback browser keys. Both platforms
  still run the pinned installed CLI with `chromium --only-shell`; Linux uses
  `--with-deps` to provision system libraries even on a binary-cache hit. Cold
  misses install normally. Windows cold_cache retains its empty download caches
  and disables all cache restore/save operations.
- Setup/cache actions log hits/misses; validation summaries include cache-hit
  outputs when the action exposes them. GitHub's branch/default-branch and PR
  merge-ref cache scopes apply: a fork PR cannot publish a cache for a trusted
  branch. Caches contain no credentials and no outputs are promoted into a
  privileged workflow. There is no pull_request_target trigger.
- Fast keeps one runner to avoid another checkout/setup for short checks.
  Full uses two runners because browser work and backend/security checks are
  independent. Each needs its own Python environment (full test/build/audit
  requirements versus browser-server runtime only); this costs extra runner
  minutes but avoids serial wall time and isolates failures. No third summary,
  security or artifact job repeats installations/transfers.
- Fast concurrency groups include workflow, event type and PR number/ref.
  New pushes supersede old pushes; new PR updates supersede that PR's old runs.
  A push cannot cancel its overlapping required PR run. Full cancellation is
  isolated by PR number. Both events still trigger Fast as required.
- Windows builds use one repository-wide group, cancel-in-progress false.
  New pushes have no effect on active manual builds. GitHub permits one active
  and one pending run per group; another manual dispatch may replace an older
  pending run. The workflow does not cancel an active build. Artifact IDs and
  source/run identity remain distinct even though the artifact name is stable.
- No path filters or documentation shortcuts: required workflows always exist.
  Documentation/workflow/security/build edits receive the same appropriate
  coverage. Cross-workflow result reuse was rejected: main-only Full checks
  cannot attest to arbitrary manually built branches.

## Windows artifact lifecycle and security

The single Windows runner installs/builds/tests/audits independently; no generic
regression is silently skipped based on a different run. `scripts/build-windows.ps1`
remains canonical and still supports standalone `-Stage All`. It uses one fresh
isolated build environment, one npm ci/build, one-file/windowed PyInstaller with
`--clean --noupx`, unchanged icons/metadata/WebView2 assets, PE/x64 checks,
privacy/archive validation and the existing SHA-256 manifest. Generated offline
build metadata is bundled and compared with the fixed workflow version, PE
resources and runtime API; see [workflow-driven versions](RELEASES.md). Native smoke covers
first launch, restart, port conflict and clean owned-process shutdown.

Upload contains exactly SAP-Lens.exe and SAP-Lens.exe.sha256, with the same
SAP-Lens-Windows-x64 name, compression level zero and 14-day retention. The
SHA-pinned official download action downloads that exact upload ID as a raw ZIP,
with digest-mismatch explicitly set to error. `scripts/verify-artifact-zip.py`
independently compares the ZIP digest to the upload output and rejects missing,
extra, duplicate, directory, symlink, encrypted, unsafe or unsupported members.
It requires exactly two regular files, a nonempty EXE no larger than 512 MiB and
a checksum file no larger than 128 bytes. It validates local headers/CRC before
publishing files in a new directory and never uses extractall or overwrites an
existing destination. Synthetic tests exercise these failure paths.

The downloaded EXE then passes the existing package verifier again, including
comparison to the original pre-upload EXE hash. Raw ZIP digest, manifest/EXE
digest and embedded package contents are distinct checks. Do not distribute an
artifact from an otherwise failed run. Signing remains disabled. Build mode does
not publish; explicit beta/stable modes use the isolated publication path described
in [manual releases](RELEASES.md). See [packaging](WINDOWS_PACKAGING.md) and [desktop](DESKTOP.md).

All action uses remain official, immutable SHA pins; checkout credentials are
not persisted. Token permissions are contents:read only in Fast/Full; Windows
build also has actions:read for this run's report metadata. Only the manual beta/stable reservation job receives contents:write and the
dependent publication job contents:write/actions:read, using dedicated
Environments. The build job consumes a preallocated immutable version and stays
read-only. No secrets or privileged fork execution are introduced.
See [release permissions and administrator configuration](RELEASES.md).
actionlint 1.7.12 is downloaded from its upstream release and checked against a
fixed SHA-256 before execution, without a floating install or third-party action.
PyYAML 6.0.3 is added only to test requirements for duplicate-safe offline YAML
contract parsing. Runtime dependencies and lockfiles are unchanged.

## Reports and required checks

`scripts/ci.py` measures commands and preserves their exit codes. Each validation
job writes one concise summary even after earlier failure, using actual step
outcomes (not inferred successful telemetry) and available test counts/timings.
Missing/skipped mandatory steps are incomplete. Command phase elapsed time
excludes earlier checkout/setup; the completed Actions job is authoritative for
wall-clock duration. Test skips are explicit. The workflow result is GitHub's
combination of its jobs; a successful Frontend summary cannot attest to Backend.

The Windows report retains application/source/runner/tool versions, validation,
one-file format, EXE/artifact sizes, distinct checksums, unsigned policy and stage
timings. It recognizes the descriptive job/step names, cannot report overall
success with missing mandatory stages, and fetches independent read-only API
metadata concurrently. API/formatting failures cannot waive blocking verifiers;
unavailable metadata is shown rather than invented. The report runs before
post-job cleanup, so its elapsed time is not final workflow duration.

Suggested required checks for main, if the owner later configures them:
Fast Validation / Backend & Frontend, Full Validation / Backend & Repository,
and Full Validation / Frontend & Browser. GitHub rules select actual check/job
names; confirm those after the first PR run. No branch protection or repository
settings are changed here. Manual Windows builds should not be a universally
required PR check because they intentionally do not automatically run.

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
| `docs/CI_ARCHITECTURE.md`, `docs/BUILD_PERFORMANCE.md`, `docs/DESKTOP.md`, `docs/VALIDATION.md`, `docs/DEPRECATIONS.md` | Architecture, measured baseline and current workflow references |

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
fix or suppression is claimed. See [deprecation maintenance](DEPRECATIONS.md).

After explicit approval, push the finished branch and select Actions → Build
Windows Application → Run workflow → work (normal benchmark inputs false).
One manual Windows run should verify the complete pipeline and report. A PR
targeting main is separately needed to measure Full Validation and its two
required jobs; do not add a manual Full trigger to sidestep that policy.

## Cross-platform build-only packaging

The additional manual **Build Deployment Packages** workflow supports Desktop,
Windows Service, Docker, Linux native and All. Shared validation is performed once
for the exact commit/run; independent platform jobs retain package audits, native
checks and distribution roundtrips. It never publishes releases or registry images.
The existing Windows release workflow remains unchanged. See
[deployment artifacts and attestation](DEPLOYMENT_PACKAGES.md) and
[current packaging validation](PACKAGING_VALIDATION.md). Four workflow files are
now explicitly covered by the repository workflow contract.
