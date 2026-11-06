# CI architecture

## Policy: CI runs only on push to `main`

Fast Validation is triggered **only** by a push to `main` (a completed merge). Pushes to `work` or any other branch, pull requests, schedules, other workflows and
repository events never start a workflow, so development pushes consume no Actions minutes. The trigger is `push` to `main`, not `pull_request`.
Full Validation and the two Build workflows are `workflow_dispatch` only and are run by hand only when the repository owner explicitly authorizes it.

Validation therefore happens locally: Fast Validation after each development phase (`python scripts/validate.py --level fast`, targeted tests per
[Testing](TESTING.md)) and the complete local regression (`python scripts/run-tests.py regression` and the full browser suite) before merging into `main`.
`scripts/check-workflows.py` and `backend/tests/test_workflows.py` fail on any other trigger, so the policy cannot drift unnoticed. Merging into `main` and
publishing releases still require explicit authorization.


## Skipping CI on a push to `main`

Pushes to `work` and pull requests no longer start CI. For a push to `main` that should not consume Actions minutes, put **`[skip ci]`** in its
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

For local commands use [Build](../BUILD.md). No YAML change is
required merely to skip one explicitly authorized push.

## Workflows and checks

| Workflow / file | Exact triggers | Jobs and responsibility |
| --- | --- | --- |
| Fast Validation / `.github/workflows/validate.yml` | push to `main` only (no `work`, feature-branch or pull_request trigger) | One job, Backend & Frontend: checks selected from the change (`scripts/run-tests.py changed`). Mandatory: pip check, Ruff, workflow contracts, actionlint, portable PowerShell checks and selected backend tests. Frontend changes add type check, ESLint, icon catalogue, build, production audit and browser smoke |
| Build Deployment Packages / `.github/workflows/build-deployments.yml` | workflow_dispatch only; one `build_target` dropdown (`all`, `windows-all`, `windows-desktop`, `windows-service`, `linux-all`, `linux-docker`, `linux-native`) | A planning job resolves the selection, then lightweight shared validation (no backend or browser suite), then the selected independent Desktop, Service, Docker and native packaging jobs (unselected ones are skipped); publication takes only the planned, verified packages |
| Full Validation / `.github/workflows/full-validation.yml` | workflow_dispatch only; no push, pull_request, schedule or workflow_call trigger | Backend & Repository and Frontend & Browser run independently in parallel. Never a prerequisite for building or publishing |
| Build Windows Application / `.github/workflows/build-windows.yml` | workflow_dispatch only; caller selects branch/ref | Optional Reserve Release Version job before Windows Build & Verification (no regression stages); optional dependent Publish Verified Windows Release job for explicit beta/stable mode |

The three-level model (Fast Validation, Build & Release, Full Regression), the change-selection table, target
selection and the no-prerequisite policy are described in [CI/CD architecture](../deployment/CI_CD.md). The sections below describe current behavior verified against the workflow files; superseded explanations are in Git history.

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
- Fast Validation runs one job (`Backend & Frontend`) so short checks share one checkout and setup; Full Validation (manual) runs
  `Backend & Repository` and `Frontend & Browser` in parallel because they are independent and need different Python environments.
  Build Deployment Packages runs a planning job, one lightweight validation job, then only the selected package jobs.
- Concurrency groups (verified in the workflow files): Fast Validation uses workflow, event type and PR number or ref, with
  cancel-in-progress, so a newer push supersedes an older one and a push never cancels a PR run. Full Validation is grouped by ref
  without cancellation. Build Deployment Packages is grouped by ref (publication has its own group); none cancels an active run.
- Fast Validation selects work from the change (see [CI/CD architecture](../deployment/CI_CD.md)); there are no path filters in
  the trigger, so the workflow always exists and reports a result, and the plan step decides what runs.
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
with digest-mismatch explicitly set to error. `scripts/packaging/verify-artifact-zip.py`
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
in [manual releases](../deployment/RELEASES.md). See [Windows Desktop](../deployment/WINDOWS_DESKTOP.md) and [desktop architecture](../architecture/DESKTOP.md).

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

`scripts/testing/ci.py` measures commands and preserves their exit codes. Each validation
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

Suggested required check for `main`, if the owner configures one: `Fast Validation / Backend & Frontend`. Full Validation and the
build workflows are manual by design and must not be required checks (a required check that never starts blocks merges).
No branch protection or repository setting is changed by this documentation.

## Build Deployment Packages

The manual **Build Deployment Packages** workflow takes one `build_target` (`all`, `windows-all`, `windows-desktop`,
`windows-service`, `linux-all`, `linux-docker`, `linux-native`). Lightweight shared validation runs once for the exact commit and
run, then only the selected package jobs run with their package audits, native checks and distribution round trips. Publication is
a separate guarded job that is off unless requested. The legacy Windows release workflow is retained separately. Details:
[CI/CD architecture](../deployment/CI_CD.md), [build guide](../BUILD.md), [artifacts and attestation](../BUILD.md#output-layout).
