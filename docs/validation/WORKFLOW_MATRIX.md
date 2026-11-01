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
| Each of the 7 targets, build only | Only selected jobs run; no publication | Selection and condition mutation tests | `all` executed: 1 package passed, 3 failed before repairs; other target combinations not runtime-verified | [41340859408](https://github.com/OnlyDrey/sap-lens/actions/runs/41340859408) | Partially verified | New build-only runs on repaired `work` |
| Shared validation without backend or browser suites | Lightweight checks only; receipt sealed | Packaging and contract tests | Shared Validation & Frontend passed at `513d388` | [41340859408](https://github.com/OnlyDrey/sap-lens/actions/runs/41340859408) | Verified on GitHub | No repair to shared architecture needed |
| Windows Desktop and Service packaging | Verified native packages and round trips | 127 targeted tests include nested-spec paths, expected identity and provenance; PowerShell parsing passed | Failed: service relative asset paths; desktop missing expected identity. Repaired in `6f64b68`, not rerun | [41340859408](https://github.com/OnlyDrey/sap-lens/actions/runs/41340859408) | Failed (before repair) | Approved new `windows-all` build-only dispatch; Windows runtime acceptance pending |
| Linux Docker packaging | Verified container package, smoke test and round trip | Existing packaging contracts | Completed successfully at `513d388` | [41340859408](https://github.com/OnlyDrey/sap-lens/actions/runs/41340859408) | Verified on GitHub | Unchanged by these fixes |
| Linux Native packaging | Audited wheelhouse, install/lifecycle and round trip | Canonical archive build and full user-mode lifecycle passed locally; no systemd | Failed before audit: `No module named pip_audit`. Pinned tooling provisioned in `6f64b68`; not rerun | [41340859408](https://github.com/OnlyDrey/sap-lens/actions/runs/41340859408) | Failed (before repair) | Approved new `linux-native` build-only dispatch; real systemd pending |
| Selected job failed, cancelled or skipped | No publication | Release eligibility tests | Not run | | Verified offline only | None |
| Unselected job ran | Publication refused | Release eligibility tests | Not run | | Verified offline only | None |
| Missing or corrupted artifact | Publication refused before any release exists | Collection tests | Not run | | Verified offline only | None |
| Failed smoke test | Package job fails; its outputs are never trusted | Eligibility tests | Not run | | Verified offline only | None |
| Duplicate release version | Refused; nothing overwritten | Publication tests | Not run | | Verified offline only | None |
| Publish disabled | No publish job; no release | Contract and build-only tests | Publish Release skipped in failed build-only run; successful build-only publication behavior still pending | [41340859408](https://github.com/OnlyDrey/sap-lens/actions/runs/41340859408) | Partially verified | Confirm skipped publication after successful builds |
| Stable from a branch other than `main` | Refused in the plan job and again at publication | Release ref tests | Not run | | Verified offline only | None |
| Missing environment approval | Publish waits or fails; nothing published | Contract tests (environment present); approval rules are repository settings | Not verifiable from the repository | | Pending | An administrator must confirm environment protection rules |
| Publication of selected, verified packages | Draft, upload, digest check, tag, publish | Fake GitHub API tests | Not run | | Verified offline only | Needs an approved test release, which has not been authorized |

## Build Windows Application (`build-windows.yml`, legacy)

| Scenario | Expected | Offline validation | GitHub runtime validation | Run | Result | Remaining action |
| --- | --- | --- | --- | --- | --- | --- |
| Build only | Build, verify, smoke test, upload; no regression stages | Release script, report and contract tests | No completed run recorded for the current form | | Pending | Needs an approved dispatch, or retire the workflow in favour of Build Deployment Packages |
| Beta or Stable release | Version reservation, then publication of the verified executable | Release script tests | No completed run recorded | | Pending | Needs an approved test release |

## Runtime validation plan

The smallest remaining runs follow. The earlier `all` run is recorded above and failed before these repairs. **New dispatches require explicit approval; the publication scenario also creates a public tag and release.** Stop when a run fails and fix first.

| Order | Run | Covers | Cost note |
| --- | --- | --- | --- |
| 1 | New Build Deployment Packages, `linux-native`, build only at repaired `work` | Pinned audit tooling, audited runtime lock, install/lifecycle, artifact round trip, other platforms skipped | One Linux job plus lightweight shared validation; no Docker rebuild |
| 2 | New Build Deployment Packages, `windows-all`, build only at repaired `work` | Desktop resolved identity and native package checks; service rooted assets and SCM smoke tests | Two Windows jobs plus lightweight shared validation; no Linux jobs |
| 3 | Fast Validation on the next frontend push and the next documentation-only push | Frontend and documentation selection paths, Playwright install and cache on the new workflow | No extra run: observe the pushes that happen anyway |
| 4 | Full Validation, manual (optional) | The manual form and report artifacts | Complete suites: roughly 19 runner-minutes under the previous automatic form, to be re-measured |
| 5 | Build Deployment Packages, `linux-native`, Alpha channel, publication enabled | Safe publication of one verified package, duplicate-version refusal on a rerun | Creates a public prerelease and tag; deleting them afterwards is also a manual, approved step |

Every Fast Validation run costs runner minutes too, so documentation and tracker updates are batched with code changes instead of being
pushed alone.

## Updating this matrix

Add a row or change a status only after a completed run (record its URL) or a new offline test. Never mark a runtime scenario
verified from a local run.

## Local repair evidence (not GitHub runtime acceptance)

Implementation: `6f64b68`; 1 November 2026. Targeted command:
`PYTHONPATH=backend:backend/tests .venv/bin/python -W error::DeprecationWarning -m unittest test_deployment_packaging test_windows_package test_deployment_selection test_deployment_release test_workflows test_artifact_zip test_release_automation test_repository_integrity test_repository_privacy -q`
— **127 passed**. No complete backend or browser suite executed.

Canonical native packager and `scripts/test-native-deployment.py` passed on Linux
Python 3.12, using a receipt sealed from successful lightweight checks (not bypassed):
production frontend/type checks, icon catalogue, pinned build-environment audit,
production npm audit, `pip check`, actionlint and PowerShell parsing. The generated
runtime lock was audited; exact wheels installed offline with hashes. User-mode
install/reinstall, import, restart, persistence, backup/restore, upgrade and
uninstall passed. Native Windows and real systemd were not run.

The `digest-mismatch: error` line was configuration. Native artifact download
reported identical expected/actual SHA-256 and succeeded. No retries or weaker
integrity policies were introduced. No corrected GitHub package run has been
started or marked passed.
