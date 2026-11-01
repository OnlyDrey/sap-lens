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

For local commands use [Build](../deployment/BUILD.md). No YAML change is
required merely to skip one explicitly authorized push.

## Workflows and checks

| Workflow / file | Exact triggers | Jobs and responsibility |
| --- | --- | --- |
| Fast Validation / `.github/workflows/validate.yml` | Every push (including all branches/tags); every pull_request with no branch/path filters | Backend & Frontend: all backend/repository tests through `scripts/run-tests.py regression --backend` (parallel processes, deprecations as errors), pip consistency, workflow contracts/actionlint and frontend type checks |
| Build Deployment Packages / `.github/workflows/build-deployments.yml` | workflow_dispatch only; operating system (`all`, `windows`, `linux`) and package (`all` or one package) inputs | A planning job resolves and validates the selection, then Shared Validation & Frontend, then the selected independent Desktop, Service, Docker and native packaging jobs (unselected ones are skipped); publication takes only the planned, verified packages |
| Full Validation / `.github/workflows/full-validation.yml` | pull_request targeting main only; no push/manual/tag/release trigger | Backend & Repository and Frontend & Browser run independently in parallel |
| Build Windows Application / `.github/workflows/build-windows.yml` | workflow_dispatch only; caller selects branch/ref | Optional Reserve Release Version job before Windows Build & Verification; optional dependent Publish Verified Windows Release job for explicit beta/stable mode |

Full Backend installs test, build and audit requirements, checks dependencies,
runs the entire backend suite through the same runner (including the real synthetic PyInstaller archive
fixture), workflow validation, repository integrity/privacy, PowerShell parsing
and static safety guards, and audits the installed Python environment. Audit
tooling shares this disposable Linux validation environment; it is never used
to package an application. Windows audit tooling remains outside its isolated
package environment and audits the complete installed Windows dependency set.

Fast keeps the full backend policy (every module, run in parallel processes by the [test runner](TESTING.md)). As in the measured
baseline, the build-only real PyInstaller fixture is skipped when PyInstaller is
not installed; this is visible in the report. Full and Windows install it and
exercise that fixture. No existing tests are removed. New tests cover workflow
trigger matrices and rejected policy changes, job cycles, reporting failures and
raw ZIP tampering/member/extraction safety. Deprecations fail backend validation.

Full Frontend installs runtime Python dependencies for the synthetic browser
server, runs npm ci once, type checking, icon-catalog validation, one production
build, a production npm audit and the complete browser regression suite through
`scripts/run-tests.py regression --browser --no-build` (independent Playwright processes with their own
servers; one process on small runners). Canonical
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
resources and runtime API; see [workflow-driven versions](../deployment/RELEASES.md). Native smoke covers
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
in [manual releases](../deployment/RELEASES.md). See [packaging](../archive/validation/WINDOWS_PACKAGING.md) and [desktop](../architecture/DESKTOP.md).

All action uses remain official, immutable SHA pins; checkout credentials are
not persisted. Token permissions are contents:read only in Fast/Full; Windows
build also has actions:read for this run's report metadata. Only the manual beta/stable reservation job receives contents:write and the
dependent publication job contents:write/actions:read, using dedicated
Environments. The build job consumes a preallocated immutable version and stays
read-only. No secrets or privileged fork execution are introduced.
See [release permissions and administrator configuration](../deployment/RELEASES.md).
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

## Cross-platform build-only packaging

The additional manual **Build Deployment Packages** workflow supports Desktop,
Windows Service, Docker, Linux native and All. Shared validation is performed once
for the exact commit/run; independent platform jobs retain package audits, native
checks and distribution roundtrips. It never publishes releases or registry images.
The existing Windows release workflow remains unchanged. See
[deployment artifacts and attestation](../deployment/BUILD.md) and
[current packaging validation](../archive/validation/PACKAGING_VALIDATION.md). Four workflow files are
now explicitly covered by the repository workflow contract.
