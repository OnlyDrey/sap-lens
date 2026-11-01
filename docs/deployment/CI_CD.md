# CI/CD architecture

SAP Lens separates validation from packaging. Three levels exist, and only the first runs automatically.

| Level | Workflow | Trigger | Purpose |
| --- | --- | --- | --- |
| A. Fast Validation | `validate.yml` | push to `work` or `main`; pull request to `main` | Cheap, change-based feedback |
| B. Build & Release | `build-deployments.yml` (all targets), `build-windows.yml` (legacy Windows desktop) | `workflow_dispatch` only | Build, verify and optionally publish selected packages |
| C. Full Regression | `full-validation.yml` | `workflow_dispatch` only | Complete backend and browser regression |

## Policy

Full Regression is **never** a prerequisite for building or publishing. It has no push, pull request or schedule trigger,
no workflow calls it, and neither the sealed validation receipt, the publish job, `release-windows.py` nor the build report
require its result. A passing run is evidence for milestones and troubleshooting, not a gate. Contract tests
(`scripts/check-workflows.py`, `backend/tests/test_workflows.py`) reject any change that reintroduces such a dependency.

## Level A: Fast Validation

`python scripts/run-tests.py changed` compares the pushed range (`BASE_SHA`, default `HEAD~1`) and selects checks from the
`change_rules` in `scripts/test-map.json`.

| Changed paths | Runs |
| --- | --- |
| Documentation only (`docs/**`, `*.md`, `assets/**`) | Mandatory checks only; no Node, no browser |
| Frontend source or configuration | Adds Node setup, type check, ESLint, icon catalogue check, production build, production `npm audit`, and the `@smoke` and changed browser specs (Playwright is installed only then) |
| Backend tests, frontend tests | The affected feature tests |
| Anything else (backend source, scripts, workflows, dependencies, unmapped paths) | The whole backend suite |
| Unusable base commit | Full baseline selection |

Mandatory on every run: dependency install, `pip check`, Ruff, workflow contracts, actionlint and the selected backend tests (which include the repository integrity and privacy tests whenever backend or repository files change). Optional steps (frontend and browser) depend only on the plan outputs, and the summary
labels a skipped optional step "not needed for this change". A step that ran must succeed.

Local equivalent: `python scripts/run-tests.py changed --plan` shows the selection; `python scripts/run-tests.py changed` runs it.

## Level B: Build & Release

`build-deployments.yml` takes one `build_target`: `all`, `windows-all`, `windows-desktop`, `windows-service`, `linux-all`,
`linux-docker`, `linux-native`. A planning job resolves it into the packages to build; unselected package jobs are skipped and
upload nothing.

Pipeline: `plan` -> `validation` (lightweight, once per run) -> selected package jobs (`desktop`, `service`, `docker`, `native`) -> `publish` (only if `publish_release`).

Shared validation contains only lightweight checks: type check, production build, icon catalogue, Python and JavaScript
dependency audits, `pip check`, Ruff, workflow contracts and lint, PowerShell parsing. These sealed checks form the receipt in
`scripts/deployment-package.py` (`CHECKS`). Package jobs add platform builds, package audits, native or container smoke tests and
a distribution round trip.

| Result | Meaning |
| --- | --- |
| selected, success | Built, verified, artifact uploaded |
| selected, failed | The job failed; nothing from it is publishable |
| unselected, skipped | Not part of the target; no runner used |
| cancelled | Run cancelled; nothing is published |
| not executed (dependency failed) | A needed job failed, so this one did not run |

Build-only runs (`publish_release` false) need no publication permission, environment approval or release token. The
`publish` job and its environments (`sap-lens-beta`, `sap-lens-stable`) apply only when publication is requested, and
`publish` takes exactly the planned packages after each is verified. It never reuses artifacts from another run or commit. Versions
use the channels Alpha, Beta, Release Candidate (RC) and Stable; a duplicate release version is rejected before publication.
See [releases](RELEASES.md) for channels and permissions.

## Level C: Full Regression

Manual only. Runs `Backend & Repository` and `Frontend & Browser` in parallel: complete backend suite, workflow contracts,
audits, type check, build, ESLint, the complete browser suite, with reports uploaded as 7-day artifacts. Use it before large
merges, after shared or security-sensitive changes, or when diagnosing a regression. Local equivalent:
`python scripts/run-tests.py regression --browser-jobs 3 --report <file>`.

## Caching and artifacts

- Caches hold only package-manager downloads (pip, npm) and the Playwright download directory, keyed by lock or requirement
  files. No virtual environment, `node_modules`, executable, credential or unverified artifact is cached.
- Package artifacts are produced and consumed within one run. Artifact identity is checked by ID and digest, and the sealed
  receipt records the commit, run and file hashes. Receipts expire after 24 hours.
- Only the selected packages are uploaded; checksums are verified before publication.

## Security gates

- Token permissions are `contents: read` by default. Write permission exists only in the isolated publish (and legacy
  version-reservation) jobs.
- Actions are pinned to full commit SHAs and checkout does not persist credentials.
- No `pull_request_target`. Fork pull requests cannot reach secrets, environments or release jobs.
- Release publication needs `publish_release`, a valid version and channel, verified packages and, for Beta and Stable, the
  matching protected environment.

### Security audit (workflows)

Checked from the repository on the current head. Repository and environment settings cannot be read from here and are listed as unverified.

| Area | Result |
| --- | --- |
| Action pinning | Every `uses:` is a full commit SHA |
| Checkout credentials | `persist-credentials: false` on every checkout |
| Triggers | No `pull_request_target`; Fast Validation is the only automatic workflow and runs with `contents: read` |
| Token permissions | Read-only by default; `contents: write` only in the publish job (and the legacy version reservation and release jobs) |
| Untrusted input | Workflow inputs reach scripts through `env`, never interpolated into `run` text; versions and channels are validated by the planner |
| Secrets | None referenced; publication uses the scoped `github.token` |
| Caches | Download caches only, keyed by lock files; nothing from a cache is promoted into a release |
| Artifacts | Same-run IDs with digest checks, sealed receipt bound to commit, run and attempt, receipt expiry 24 hours |
| Docker image | Runs as UID 10001 with a health check; base images are pinned by tag, not digest |

**Confirmed issue, fixed:** Stable / Production publication from the deployment pipeline was restricted to `main` only by an optional
administrator environment rule, not in code (the legacy Windows release did enforce it). The plan job and the publish step now refuse
Stable from any other ref, and a build-only run is unaffected.

**Hardening recommendations (not vulnerabilities, not applied):**

- Add Dependabot for the `github-actions` ecosystem so SHA pins do not go stale (no `.github/dependabot.yml` exists).
- Pin the Docker base images by digest once an update process exists.
- Confirm in repository settings that `sap-lens-stable` has required reviewers and a main-only branch rule, and `sap-lens-beta` exists (unverified).
- Consider retiring the legacy `build-windows.yml` once Build Deployment Packages has a verified Windows Desktop run, to remove a second privileged release path.
- Optional build provenance attestation (`actions/attest-build-provenance`) would add a signed record; the sealed receipt and digests cover integrity within a run.

## Local commands

| Command | Use |
| --- | --- |
| `python scripts/check-workflows.py` | Workflow contracts |
| `python scripts/ci.py lint` | actionlint |
| `python scripts/run-tests.py changed --plan` | Fast Validation selection |
| `python scripts/run-tests.py targeted <feature>...` | Feature tests |
| `python scripts/run-tests.py regression` | Full Regression |

## Runtime validation status

Offline contract tests cover every workflow. Per-scenario status, with run URLs, is kept in the
[workflow validation matrix](../validation/WORKFLOW_MATRIX.md); a scenario counts as verified on GitHub only after a completed run
is recorded there. No workflow is dispatched and no test release is published without explicit approval.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Fast Validation runs more than expected | `changed --plan`; shared or unmapped paths select the whole backend by design |
| Optional step missing from the summary | Expected when the plan says "not needed for this change" |
| A build target built nothing | Planner summary: the target resolved to other packages |
| Publish skipped | `publish_release` false, a selected package failed, or the run was cancelled |
| Receipt rejected | Older than 24 hours, or built from a different commit or run |

## Package stabilization — 1 November 2026

Run [41340859408](https://github.com/OnlyDrey/sap-lens/actions/runs/41340859408),
source `513d388ea005abc5f60e8fa8dedaa0f760b298a8`, passed selection, shared
validation and Docker. Three package-stage failures were repaired in `6f64b68`:

| Target | Confirmed cause | Fix and retained verification |
| --- | --- | --- |
| Linux Native | The job interpreter had no `pip_audit` module; the audit did not run | Install the existing pinned `scripts/requirements-audit.txt` before the smoke test. Audit the complete generated hash-locked requirements; offline installation still checks wheel hashes. |
| Windows Service | PyInstaller rebased relative data sources under `backend/build/server`, its spec directory | Root frontend, icon, image, identity, version resources and backend search paths at the repository root. Reuse the consumed frontend; no second Node build. |
| Windows Desktop | The verifier received no `SAP_LENS_EXPECTED_BUILD_JSON` from the deployment job | Pass the shared validation job's resolved identity through the job environment. Keep exact schema/commit/run/version equality and all package checks. Missing or malformed expected identity now has a fixed privacy-safe diagnostic. |

The native download's expected and actual digests matched. `digest-mismatch:
error` in the log is the action's fail-closed configuration, not a detected
mismatch. No digest, receipt, audit or package-identity check was relaxed.

Local evidence: 127 targeted package/workflow/repository tests passed; actionlint,
Ruff, PowerShell parsing and service-helper tests passed. A real Linux x86-64
archive built through the canonical packager, passed its runtime audit and
hash-checked offline installation, then passed user-mode start/restart, import,
persistence, backup/restore, upgrade and data-preserving uninstall. Type checking,
production frontend build and production JavaScript audit also passed.

These results do **not** establish repaired GitHub jobs, native Windows packaging,
SCM/WebView2 or real systemd acceptance. See the [runtime matrix](../validation/WORKFLOW_MATRIX.md).
No complete backend/browser suite or workflow dispatch was required for this fix.

For minimum-cost remote confirmation, manually dispatch **new** build-only runs
on the repaired `work` SHA: `linux-native` and `windows-all`, with
`publish_release=false`. This skips the already-successful Docker job. A single
`all` run is an alternative that shares validation once but rebuilds Docker.
Re-running the old failed run would test its original commit, not these fixes.
Full Regression remains optional and is not a build/release prerequisite.
