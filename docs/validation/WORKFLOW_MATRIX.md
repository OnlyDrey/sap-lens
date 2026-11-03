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

## Local stabilization checkpoint — 2 November 2026

The Work Queue/filter, canonical review-coverage and restart-based Backup & Restore
implementation is delivered incrementally; this is **not** a full-regression pass.

- Full backend recheck: **993 tests, OK, four tool-dependent skips**. All four
  skipped PowerShell/PE-parser checks subsequently passed separately. No native
  Windows installer, WebView2, SCM, real systemd, reboot or UNC acceptance is claimed.
- Final directly affected bulk safety: **nine tests passed**, including protection
  of earlier Investigate/outdated decisions and revision changes during preview.
  The initial synthetic outdated-event fixture attempted mutation of a frozen model;
  it was corrected to construct an immutable prior-version fixture.
- Essential browser checks: **three passed** across the corrected shared-reviewer
  workflow, atomic bulk overwrite/history and Dashboard/queue coverage synchronization.
  The Dashboard check's initial navigation selector incorrectly requested a button;
  the real navigation link is now used. These checks used an isolated server/build,
  without restarting or replacing assets for the full run.
- Types and isolated production frontend build passed. Existing workflow/actionlint,
  PowerShell helper, Ruff, documentation, Lucide and dependency checks passed.
  Production npm and installed-Python audits: no known vulnerabilities. The broader
  development npm audit reports **11 moderate lint-toolchain findings** related to
  `GHSA-g3hv-75wg-m249`; no forced dependency changes were applied.
- The existing full browser run finished **733 passed / 20 failed**. Several SoD
  tests still used the former stacked-panel/reviewer-field contract and require
  targeted rechecks of the updated tab-aware selectors. Four startup-document
  cases were blocked by the managed browser's `file://` administrator policy.
  Unreviewed failures remain unresolved evidence; do not report this run as green.
- Outgoing privacy review found no new private artifacts, credential signatures or
  non-reserved email domains. Previously accepted historical branding is unchanged.
  The 230-item tracker retains its manual approval fields unchanged.

No packaging workflow, release, tag or native deployment run was manually dispatched.

### Targeted browser stabilization follow-up

The three failures in Actions run `41480098787` were reproduced from its logs:
two obsolete `Quick review details` rationale locators and one real presentation
regression where derived coverage hid the explicit activity decision. Rationale
selectors now use the role-review section; matrices preserve explicit decisions
and use derived labels only for pending manual decisions.

All 20 previously failing local scenarios are now covered by passing targeted
checks: 16 passed in the affected-case batch, the two long-username cases passed
after correcting the real SAP-user link accessible name, the Risk Acceptance row
case passed with explicit tab navigation, and the shared-reviewer scenario passed
in the earlier essential recheck. Tabbed-section/header expectations were updated
without removing assertions. Four startup cases render the exact generated HTML
with Playwright rather than navigating a managed-browser-blocked `file://` URL.
No full suite was restarted; native Windows/WebView2 acceptance is still separate.

## Lean development and stability follow-up — 2 November 2026

- FAST/FEATURE/FULL wrappers delegate to the existing runner. Fourteen policy/profile
  tests, a real FAST area run, a FEATURE workflow with retained JSON/HTML/JUnit, and
  the PowerShell plan command passed. FULL now explicitly selects the existing
  release-validation profile (regression plus available security/platform checks),
  rejects narrowing/skip-build flags, and never publishes or dispatches anything.
- Confirmed backend defect: metadata response preparation occurred after the file
  commit. An injected retained-source read failure reproduced a failed request with
  silently changed storage. Preparation now precedes the atomic commit for risks
  and activities. **104 affected backend tests passed**, including concurrent CAS,
  failed-write preservation, safe error references and subsequent request recovery.
  These stores are JSON/content-addressed snapshots, not SQLite. Native desktop
  process termination was not reproduced or claimed fixed.
- **Eight focused browser workflows passed**, plus the queue-progress/export
  recheck: configuration server/network error recovery retains drafts; only the
  clicked action spins; rapid writes preserve decisions; failures restore controls;
  a same-item competing decision is not automatically overwritten. Existing
  approval/evidence/frozen-period semantics remain enforced by the backend.
- Performance evidence used synthetic data and a retained old frontend against the
  same current backend. Review GET requests were consistently **13 → 5** (one POST
  in both versions), removing eight source-only option refetches. The controlled
  single-workflow DOM sample measured pending feedback **34.1 → 15.1 ms**, and
  confirmation after the test's request gate released **209.9 → 111.5 ms**; API
  response samples were **32 → 28 ms**. A later loaded batch measured 64.5 ms pending,
  679.2 ms confirmation and 158 ms API, so no stable elapsed-time improvement/SLA is
  claimed. These timings exclude the deliberate request hold and browser-driver
  actionability time. Atomic JSON index commit median was **0.70 ms** across nine
  samples; three API samples per category gave medians 13.62/13.65/12.14 ms for
  assignment/activity/risk decisions. No database transaction benchmark is implied.
- Production type/build checks passed. No complete backend/browser regression was
  rerun for this round, no deployment checks repeated, and dependencies did not
  change. Earlier production audits remain applicable; existing development-tool
  advisories and native Windows/WebView2/SCM/systemd/UNC acceptance remain separate.
- `SAP_SoD_Risk_and_Activity_Definitions.xlsx` was absent from the accessible workspace
  and attachments. Reference integration is blocked on that source. No reference
  contents/columns, activation rules or replacement metadata precedence were invented.

For independent complete local validation, activate the development environment and
run `python scripts/validate.py --level full --reports` (Windows/Linux). Native
acceptance still requires the actual target platform.


### SoD reference definitions — workbook integration (2026-11-02)

The previously missing workbook is now available. Its schema was inspected: 11 risk
records, 13 activity records and six terminology entries. The original file and its business
contents remain outside Git. A bounded, formula-free XLSX importer uses the existing lxml
dependency, a separate versioned private library and compare-and-swap atomic replacement.
Metadata resolution now follows the requested field precedence: non-empty local override,
imported metadata, curated reference. Only exact active matrix IDs are enriched; unmatched
library entries cannot activate access rules. Review captures retain values and library identity.

Validation: 137 distinct affected backend/runner tests passed across targeted runs
(catalogue, metadata, reference import, reports, periods, application request limits and
profile ownership). The existing seven-case metadata browser spec passed; its expanded
reference upload/visual workflow was rechecked successfully after correcting the test's
same-document navigation and exact region locator. Screenshots reviewed at 375 px/light
and 1280 px/dark; optional-column identifiers now wrap without clipping. Generated test
workbooks use isolated temporary configuration, not user paths.

TypeScript and production Vite build passed. Targeted ESLint and Ruff passed; the full
lint invocation also passed with its existing 111 warnings. Documentation links: 94 files,
zero failures. No dependencies or packaging files changed; prior audits/packaging evidence
is retained. Original workbook contents and generated screenshots are excluded from Git.
No new personal/company data or credentials were introduced. FULL regression and native
Windows/WebView2 acceptance were not run. This section is delivered with the focused
`feat(sod): integrate versioned reference definitions with provenance` commit.

### Browser multipart source replacement (2026-11-02)

All four CSV source types now support authenticated multipart upload and activation via
one canonical selection service. Browser users need no server paths; optional administrator
paths remain under Advanced settings. Native desktop file browsing is retained, and the
browser connected to a desktop backend can also upload through its existing session.
Generated private staging names, bounded files/fields, static mode, settings CAS and the
existing loader gate preserve the last valid snapshot and reject conflicting operations.
Failure cleanup never removes a committed/active file. The legacy raw staging API is retained.

Targeted evidence: affected server/automatic-import/SoD lifecycle/application run: 58 passed;
additional multipart/desktop-backend checks: 15 passed (overlapping modules);
packaging/multipart contracts: 17 passed, one existing platform-specific skip. Browser:
two headless upload/download/theme/viewport cases passed, one all-four-source validation/
failure-preservation workflow passed, three native-dialog mock workflows passed. Production
types/build, affected ESLint (two existing warnings), Ruff and documentation links passed.
The existing python-multipart installation is now explicitly pinned as a runtime requirement;
its targeted dependency audit reported no known vulnerabilities. No native Windows or Docker
image acceptance was executed; no FULL regression or manual workflow dispatch was performed.

### Effective reference fields in SoD editors (2026-11-02)

Root cause: risk/activity forms initialized exclusively from raw local annotations;
resolved reference values existed in the description API but did not populate inputs.
Also, parsing an attached workbook does not install it in another running application.
The provided workbook was rechecked: F019 and AP01 are exact reference IDs; its 11 risks,
13 activities and six terms are not automatically active matrix elements.

The shared metadata API now exposes inherited values/provenance and original reference
text separately. Editor fields show local-or-inherited values, keep untouched inheritance
out of local storage and support Reset to inherited. Refetches preserve unsaved local
state; forms retain their initial revision/definition for conflict protection. Reference
status reports installed state/revision, current matches, unmatched references and active
IDs lacking definitions. Workbook selection also uses bounded authenticated multipart,
reusing the atomic library service; the previous PUT API remains compatible. No import
changes review decisions, description-review status, periods or immutable evidence.

Targeted validation: catalogue/metadata/reference/report modules: 56 passed; updated
reference multipart/body-limit plus application tests: 18 passed (overlapping reference
module). The complete affected metadata browser spec: eight passed, including rendered
F019/AP01 inheritance, unchanged saves, reset, reimport, exact matching, missing fields,
source provenance and preservation of unsaved drafts. TypeScript/production build,
affected ESLint, Ruff, diff and documentation-link checks passed. Original workbook and
screenshots remain outside Git. Production-installation match counts require its live
reference status, not test-fixture counts. FULL/native Windows acceptance was not run.

### Product version and release branch policy (2026-11-02)

Authoritative source: backend/resources/product-version.json, current development
version 1.0.0-beta.2. Live releases were read only: v1.0.0-beta.1 exists. Source/npm
mirrors and runtime/frontend asset identity agree; CI stamps mirrors from its single
resolved build identity. Stale ignored metadata from a different local commit is not
used to identify the checkout; frozen/CI identity validation remains strict.

Deployment planning resolves auto numbering from paginated tags/releases, counts both
legacy beta-N and dotted beta.N, checks base/branch/commit/sequence/collisions before
expensive jobs and passes one result to all jobs. Prerelease publication requires work;
stable builds/publication require main and stable source metadata. Publication checks
branch SHA, annotated-tag commit and selected verified artifact identities/checksums.
No automatic promotion, tags/releases or workflow dispatch occurred.

Targeted evidence: 90 version/selection/release tests passed; affected packaging and
release rechecks passed (one existing platform skip). Final publication/policy tests:
30 passed. Production TypeScript/Vite build passed and actual frontend asset version
was compared with backend and package mirrors. Workflow contracts, actionlint,
PowerShell parser/service-helper checks, Ruff and documentation links passed. Windows
native packaging/runtime and a real release were not executed. FULL was not run.


### Bundled reference defaults (2026-11-02)

The supplied curated business definitions now ship as versioned JSON (11 risks, 13
activities, six terms), with no original workbook/author metadata, employees, assignments
or private paths. Fresh installations inherit defaults; existing private libraries survive
upgrades. Exact active-ID enrichment and field-level local/imported precedence are unchanged.
Reset defaults is confirmed, CAS/atomic, and limited to the reference library. Immutable
history, local annotations and active matrix are preserved.

Targeted reference/metadata/backup/packaging modules passed after correcting a new backup
fixture's class placement; the corrected backup and reference recheck passed 13 tests.
A dedicated resource archive roundtrip passed. Windows frozen-path and missing-resource
behavior, custom upgrade preservation and existing backup/restore are covered. The browser
inheritance/reset/cancel/override-preservation workflow passed. TypeScript/production build,
Ruff and documentation links passed. Windows/Linux resource copy contracts are checked;
native Windows, actual Docker image and real systemd acceptance remain unexecuted.

### Settings consolidation and single source file action

SoD Risk Configuration now keeps its page title, compact reference coverage/reset,
Risks/Activities navigation, search and tables. Optional custom workbook import is
under Advanced reference settings. The duplicate catalogue heading, Settings-only
export/source shortcuts, introductory paragraph and evaluation disclosure were removed;
underlying services and evidence semantics remain intact.

All Data Sources have one primary Browse / Upload file action, native on desktop and
multipart in browsers. Advanced server source path contains only its path input, not a
second Browse action. Static upload behavior is explicit, and manual-path mode/refresh,
source health, previews, change inspection and failure preservation remain unchanged.

Validation: 31 of 32 affected browser scenarios passed initially; the remaining new test
used textbox instead of the real searchbox role. That locator was corrected and five
final targeted workflows passed, covering the corrected compact UI, headless multipart
uploads, preserved catalogue CSV service and SoD-only refresh. Existing affected responsive
cases cover both themes at 375/800/1280/1600 px; representative 375/light and 1280/dark
screenshots were reviewed. TypeScript/Vite production build passed; affected ESLint passed
with existing warnings. Documentation links and diff checks passed. A supplementary local
Alpha/Beta/RC desktop-identity parser correction passed 14 version tests. No FULL regression,
native Windows/SCM, real systemd acceptance, release or manual workflow dispatch occurred.
Only the primary agent was active; no additional agents were launched.
