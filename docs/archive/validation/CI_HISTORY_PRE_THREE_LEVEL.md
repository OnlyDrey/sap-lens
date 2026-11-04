# CI explanations before the three-level model

Superseded passages moved verbatim from [`docs/development/CI.md`](../../development/CI.md) on 2026-11-04. They describe the earlier
model (complete backend and browser suites on every push and pull request, Full Validation on pull requests to `main`). They are kept
for history only; current behavior is in [CI/CD architecture](../../deployment/CI_CD.md).

## Workflow detail before the three-level model (Full Validation on every PR, complete suites in Fast)

Full Backend installs test, build and audit requirements, checks dependencies,
runs the entire backend suite through the same runner (including the real synthetic PyInstaller archive
fixture), workflow validation, repository integrity/privacy, PowerShell parsing
and static safety guards, and audits the installed Python environment. Audit
tooling shares this disposable Linux validation environment; it is never used
to package an application. Windows audit tooling remains outside its isolated
package environment and audits the complete installed Windows dependency set.

Fast selects backend tests from changed paths using the [test runner](../../development/TESTING.md); script and workflow changes select all modules. As in the measured
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
suite provides the existing interaction regression coverage. Fast runs frontend build, browser smoke and the production JavaScript audit when its change plan selects them.
Python dependency audits remain blocking in Full and the independent manual package builds.

## Runner layout, concurrency and path-filter notes before the three-level model

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

## Suggested required checks before the three-level model

Suggested required checks for main, if the owner later configures them:
Fast Validation / Backend & Frontend, Full Validation / Backend & Repository,
and Full Validation / Frontend & Browser. GitHub rules select actual check/job
names; confirm those after the first PR run. No branch protection or repository
settings are changed here. Manual Windows builds should not be a universally
required PR check because they intentionally do not automatically run.

## Cross-platform packaging summary before the build_target dropdown

## Cross-platform build-only packaging

The additional manual **Build Deployment Packages** workflow supports Desktop,
Windows Service, Docker, Linux native and All. Shared validation is performed once
for the exact commit/run; independent platform jobs retain package audits, native
checks and distribution roundtrips. It publishes a GitHub release only when `publish_release` is explicitly enabled and every selected package passes; it does not push registry images.
The existing Windows release workflow remains unchanged. See
[deployment artifacts and attestation](../../BUILD.md) and
[current packaging validation](PACKAGING_VALIDATION.md). Four workflow files are
now explicitly covered by the repository workflow contract.

