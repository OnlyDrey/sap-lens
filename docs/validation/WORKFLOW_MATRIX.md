# Workflow validation matrix

What each workflow is expected to do, how it was validated offline, and what a completed GitHub run has shown. A scenario counts as
**Verified on GitHub** only when a completed run is recorded here with its URL. Passing offline tests never upgrade that status.

Status classes: Verified on GitHub, Verified offline only, Partially verified, Failed, Pending.

Offline validation means `python scripts/check-workflows.py` (contracts), `python scripts/ci.py lint` (actionlint) and the tests in
`backend/tests/test_workflows.py`, `test_deployment_selection.py`, `test_deployment_release.py`, `test_deployment_packaging.py`,
`test_release_automation.py` and `test_test_profiles.py`.

## Fast Validation (`validate.yml`)

| Scenario | Expected | Offline validation | GitHub runtime validation | Run | Result | Remaining action |
| --- | --- | --- | --- | --- | --- | --- |
| Push to `work`, backend-only change | Backend and mandatory checks run; Node and browser steps skipped and reported as not needed | Trigger matrix, change-selection tests, summary tests | Run completed, Node and browser steps skipped, about 1.5 min | [41335937097](https://github.com/OnlyDrey/sap-lens/actions/runs/41335937097) | Verified on GitHub | None |
| Push to `work`, documentation-only | Mandatory checks only, no Node | Change-selection tests | Not run | | Verified offline only | Observe on the next documentation-only push |
| Push to `work`, frontend change | Adds type check, ESLint, catalogue, build, audit, browser smoke | Change-selection tests, contract test for optional steps | Not run | | Verified offline only | Observe on the next frontend push (browser cache and Playwright install are untested on the new workflow) |
| Pull request to `main` | Same selection; base is the PR base SHA | Trigger matrix | Not run | | Verified offline only | Observe on the next PR |
| Push to another branch or tag | No run | Trigger matrix | Not applicable | | Verified offline only | None |
| Unusable base commit | Falls back to the full baseline selection | Change-selection tests | Not run | | Verified offline only | None |

## Full Validation (`full-validation.yml`)

| Scenario | Expected | Offline validation | GitHub runtime validation | Run | Result | Remaining action |
| --- | --- | --- | --- | --- | --- | --- |
| Manual dispatch | Backend & Repository and Frontend & Browser run; reports uploaded as artifacts | Contracts, report-step contract | The manual form has not been run (earlier runs used the previous automatic form) | | Verified offline only | Needs an approved manual dispatch |
| Any push, pull request, schedule, `workflow_call`, `workflow_run` | No run | Trigger matrix and drift tests | Not applicable | | Verified offline only | None |
| Build & Release or publication depends on it | Rejected | Policy mutation tests | Not applicable | | Verified offline only | None |

## Build Deployment Packages (`build-deployments.yml`)

| Scenario | Expected | Offline validation | GitHub runtime validation | Run | Result | Remaining action |
| --- | --- | --- | --- | --- | --- | --- |
| Invalid target | Plan fails before any runner; nothing selected | Planner tests | Not run | | Verified offline only | None |
| Each of the 7 targets, build only | Only selected package jobs run; others skipped; no publication permission needed | Selection matrix, workflow-condition tests | Last run before the lightweight validation failed in the Windows package jobs (test path assertion, since fixed) | [41331855340](https://github.com/OnlyDrey/sap-lens/actions/runs/41331855340) | Failed (before fix) | Needs an approved dispatch after the fix |
| Shared validation without backend or browser suites | Lightweight checks only; receipt sealed | Packaging and contract tests | Not run | | Verified offline only | Needs an approved dispatch |
| Windows Desktop and Service packaging | Package built, smoke tested, round trip verified | Packaging tests (PowerShell and Windows items not run on Linux) | Failed before fix; not rerun | [41331855340](https://github.com/OnlyDrey/sap-lens/actions/runs/41331855340) | Failed (before fix) | Needs an approved dispatch on Windows runners |
| Linux Docker and Linux Native packaging | Package built, smoke tested, round trip verified | Packaging tests | Not run since the lightweight change | | Verified offline only | Needs an approved dispatch |
| Selected job failed, cancelled or skipped | No publication | Release eligibility tests | Not run | | Verified offline only | None |
| Unselected job ran | Publication refused | Release eligibility tests | Not run | | Verified offline only | None |
| Missing or corrupted artifact | Publication refused before any release exists | Collection tests | Not run | | Verified offline only | None |
| Failed smoke test | Package job fails; its outputs are never trusted | Eligibility tests | Not run | | Verified offline only | None |
| Duplicate release version | Refused; nothing overwritten | Publication tests | Not run | | Verified offline only | None |
| Publish disabled | No publish job; no environment approval | Contract tests | Not run | | Verified offline only | None |
| Stable from a branch other than `main` | Refused in the plan job and again at publication | Release ref tests | Not run | | Verified offline only | None |
| Missing environment approval | Publish waits or fails; nothing published | Contract tests (environment present); approval rules are repository settings | Not verifiable from the repository | | Pending | An administrator must confirm environment protection rules |
| Publication of selected, verified packages | Draft, upload, digest check, tag, publish | Fake GitHub API tests | Not run | | Verified offline only | Needs an approved test release, which has not been authorized |

## Build Windows Application (`build-windows.yml`, legacy)

| Scenario | Expected | Offline validation | GitHub runtime validation | Run | Result | Remaining action |
| --- | --- | --- | --- | --- | --- | --- |
| Build only | Build, verify, smoke test, upload; no regression stages | Release script, report and contract tests | No completed run recorded for the current form | | Pending | Needs an approved dispatch, or retire the workflow in favour of Build Deployment Packages |
| Beta or Stable release | Version reservation, then publication of the verified executable | Release script tests | No completed run recorded | | Pending | Needs an approved test release |

## Runtime validation plan

The smallest set of real runs that moves the pending rows above to verified. **None of these has been run: each needs explicit approval
because it dispatches a workflow, and the last creates a public tag and release.** Runs are ordered by value; stop when a run fails and fix first.

| Order | Run | Covers | Cost note |
| --- | --- | --- | --- |
| 1 | Build Deployment Packages, `all`, build only (no publication) | The Windows path-confinement fix on a Windows runner, Windows Desktop and Service, Linux Docker and Native, lightweight shared validation without suites, receipt, artifact digests, no publication permission needed | One shared validation, two Windows and two Linux package jobs; read the real minutes from the run and record them here |
| 2 | Build Deployment Packages, `linux-native`, build only | Skipped, unselected package jobs start no runner; the planner summary | One Linux package job plus the shared validation |
| 3 | Fast Validation on the next frontend push and the next documentation-only push | Frontend and documentation selection paths, Playwright install and cache on the new workflow | No extra run: observe the pushes that happen anyway |
| 4 | Full Validation, manual (optional) | The manual form and report artifacts | Complete suites: roughly 19 runner-minutes under the previous automatic form, to be re-measured |
| 5 | Build Deployment Packages, `linux-native`, Alpha channel, publication enabled | Safe publication of one verified package, duplicate-version refusal on a rerun | Creates a public prerelease and tag; deleting them afterwards is also a manual, approved step |

Every Fast Validation run costs runner minutes too, so documentation and tracker updates are batched with code changes instead of being
pushed alone.

## Updating this matrix

Add a row or change a status only after a completed run (record its URL) or a new offline test. Never mark a runtime scenario
verified from a local run.
