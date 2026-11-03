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

### Automatic CI test-fixture correction

Read-only inspection of the earlier automatic runs found two fixture problems:
`run_plan` inherited GITHUB_ACTIONS=true on runners, so deliberately offline planning
cases entered real CI preflight; the workflow negative test mutated required=false,
which is now the valid source-derived version setting. The planner subprocess now
explicitly selects offline mode, while separate mocked CI-policy tests retain real
CI-mode coverage. The negative test now mutates required=true and still requires
rejection. No production guard or assertion was weakened.

Both affected modules passed 34 targeted tests with GITHUB_ACTIONS=true in the parent
environment. Earlier automatic runs remain failed historical evidence; the correction
requires a new automatic run. No manual workflow dispatch or full local regression ran.

### Refinement phase 1 — runtime scheduling alignment

Root cause: schedule-grid aligned field containers to their bottom edges, so the
Daily time helper text displaced the neighbouring Time zone label/control. The grid
now aligns fields at the start; FormField's existing accessible helper relationship
is retained. Five affected scheduling browser tests passed, including measured label
and control top-edge alignment, persistence, cron validation and runtime notes. Types
and production build passed. Scheduling rules/calculations were not changed.

### Refinement phase 2 — Backup & Restore presentation

Replaced the oversized status card with a compact status row and refresh action;
matched Create/Restore section icons, retained restart-based action labels and
sensitive-unencrypted-archive guidance, and exposed the selected filename with
client-side extension/empty/size validation. Existing integrity preview, explicit
replacement confirmation, automatic destination recovery and restart handoff remain.
Three affected browser cases passed (workflow plus narrow/light and desktop/dark);
the workflow recheck including invalid-extension and filename assertions passed.

### Work Queue cleanup (Phase 7.9)

Removed the redundant removal-recommendation column and per-row progress annotation.
The removal KPI/filter, API payloads, exports and completion calculations remain intact.
The initial desktop boundary assertion exposed inherited catalogue-column minimum widths;
the eight-column queue now has its own widths, retaining contained scrolling on narrow screens.
Validation: typecheck and production build passed; 11 initial filtering/navigation/group/export
browser checks passed, the affected bulk replacement/filter recheck passed, and all eight
light/dark 375/800/1280/1600 queue previews plus Dashboard synchronization passed.
Native Windows acceptance remains unexecuted. Other ongoing phase checks are tracked separately.

### Reference/template, footer and SoD presentation refinement

The distributable synthetic XLSX template is generated by `scripts/reference-template.py`
and parsed by the real reference importer. Its authenticated download and capability-bound
native Save dialog share the exact bundled bytes. A fixed-URL native bridge opens the
project repository externally; browser links use a normal protected new tab. The same
version footer is rendered in main pages and the Settings scroll area.

Targeted evidence: 26 desktop bridge tests, 16 metadata tests and the reference tests passed;
17 of 18 initial integration checks passed, including all eight footer theme/width cases,
reference import/reset/download and unchanged-inherited-field saves. The remaining
remediation expectation referenced the intentionally removed parent column; its regression
now asserts the seven columns and checks recommendation details after expansion.
Final targeted rechecks and complete regression results are recorded below when finished.
Type checking, production builds, changed-file lint/Ruff and documentation link checks passed
(94 Markdown files; no broken local links). External URLs were not fetched by the link check.

Focused backend review: storage remains atomic JSON snapshots with revision checks and
file locking, not a relational database. Synthetic metadata resolution (3 risks, 5 activities,
300 calls) measured median 0.658 ms and p95 2.331 ms in this environment. This does not
establish a production bottleneck; no speculative cache/database rewrite or speedup is claimed.
Original workbook/private source material, browser artifacts and local state remain outside Git.
Native Windows/WebView2, actual SCM/reboot/UNC and real systemd acceptance remain pending.

Final targeted rechecks: all 12 governance/review-coverage checks passed, including direct
assignment review, derived risk access coverage with formal acceptance still Pending,
remediation tracking/expansion and all eight light/dark 375/800/1280/1600 review previews.
The preceding targeted run passed all eight footer previews, reference/template download,
reference import and inheritance, and compact Settings checks. The four-test recheck passed
remediation, exact active-activity pills and inherited drafts; its review-method locator
identified a missing contextual trigger name. `Popover.triggerLabel` fixes that accessibility
issue, and the subsequent 12-test run passed. Final production build and TypeScript passed.

### Final validation policy update and delivery

At the user's request, the full regression was safely terminated during its backend stage;
its process tree was stopped and no browser regression had started. The preserved local
log is `build/validation/20261103T074214020660Z/validation.log` (ignored build output).
No full-suite pass/failure count is claimed: the interrupted backend worker did not emit
its final result JSON. Full regression is intentionally deferred to release preparation or
an explicit request; it is not a normal development prerequisite.

The preflight omission for `application-footer.spec.ts` is corrected in the canonical
Shared UI test map. Map completeness passed, all 20 test-runner/profile tests passed, and
all 94 Markdown documents passed local-link validation. The printed occupied-port message
in the runner tests is their intentional safety-guard scenario, not a stale live browser
server; port 18745 is unoccupied after shutdown.

Completed targeted evidence remains valid: 26 desktop bridge tests, 16 metadata tests,
reference importer/template/API tests, eight footer previews, eight queue previews, and
12 final review/remediation checks passed. TypeScript and production build passed after
the final application changes; Python lint, changed-component lint, Lucide verification
and whitespace checks passed. Earlier UI-only expectation/locator failures were corrected
and affected checks passed. No dependencies or product version changed. Full security/
release audits and native target-platform acceptance were not executed in this delivery.
Implementation commits: `0bf4f85`, `8845129`, `4ea85ab`, `de92369`. Original reference
workbooks, employee data and generated test artifacts are excluded from the commits.

### Source Details transaction-button consistency

Risk Source Details now uses the existing 14px `ListTree` icon on both ACTVT1 and
ACTVT2 transaction buttons. The Activity modal uses the same icon as its table;
all retain the shared compact Button and original drill-down handlers. Three focused
browser checks passed (existing table actions plus light/dark coverage of both slots,
Activity modal/table icons, button heights and exact transaction evidence). TypeScript,
production build, changed-component lint, Lucide and test-map checks passed. No backend
code changed, so backend tests were not repeated. Full regression was intentionally skipped.

The newly requested reference-completion phase is blocked on the absent
`SAP_SoD_Missing_Risks_P001_P002_P008_PR01.xlsx`. The older reference workbook is
available but is not a substitute for the requested definitions or PR01 source review.
No missing definitions, metadata coverage or source-discrepancy resolution is invented;
active rules, reference defaults, overrides, mappings and decisions remain unchanged.
Remaining attached reference/navigation phases are pending.

### Reference completion — supplied vendor definitions

The supplied missing-definitions XLSX was parsed by the real bounded importer, not
reconstructed from its filename. Library 1.0.1 adds P001, P002, P008 and PR01, including
all supported notes and review caveats; 14 reference tests passed. Original files remain
outside Git. Product version, active matrix, overrides and review history are unchanged.
Against the provided matrix (not a production database), reference coverage improves:
risk names/descriptions/impacts/controls/guidance 11/14 → 14/14; activity names/descriptions/
guidance 13/14 → 14/14. The 28 distinct risk/activity relationships and transaction metadata
(230/232 distinct transaction codes have text) are unchanged. Missing transaction text is
not fabricated. PR01's supplied mappings support vendor-master wording; historical label
conflicts remain explicitly documented and require human acceptance of the active ruleset.

### Effective configuration names and relationship contracts

Catalogue rows now expose an additive effective `display_name`, reused for name search,
sorting and catalogue CSV output. Local fields and precedence are unchanged. Active
risk/activity relationships are returned separately from retained historical relationships;
exact-ID detail endpoints avoid fuzzy/paginated lookup misses. Metadata carries factual
related IDs even when descriptions are missing, without inventing display text.
Targeted evidence: 20 catalogue, 14 reference and 18 metadata/API tests passed; two
focused table/pill browser checks, TypeScript and production build passed. Navigation
integration continues in the next phase; these additive endpoints do not alter evaluation.

### Shared Risk/Activity navigation and UI refinement

Settings now uses one bounded entity-detail workflow, shared header/navigation and the
existing Dialog, pills, InfoTip, Button and status components. Previous/Next collects the
originating filtered/server-sorted list across pages and rejects mixed catalogue/source
identities. Related pills navigate both directions; Back retains at most 20 locations.
Navigation/close confirms discard of changed raw local fields; unchanged inherited text
stays inherited. Missing exact entities produce controlled errors. Origin tab/search persist.

Risk tables expose Related Activities; Activity tables expose active Related Risks with
accessible overflow into details. Header metadata, transaction icons and sticky editing
controls remain available. Exact-ID Source details no longer relies on fuzzy search.
Description-only report snapshots explicitly exclude the new UI relationship fields;
14 snapshot/report metadata tests passed after this compatibility correction.

Targeted UI evidence: 12 new navigation/source-guard/responsive cases and four existing
configuration-table checks passed. This includes cross-page navigation, repeated Risk ↔
Activity transitions, Back, discard accept/cancel, preserved drafts/filters and all eight
light/dark 375/800/1280/1600 layouts. Two metadata fixture failures were caused by retained
historical IDs moving target rows beyond page one; explicit searches and a neutral synthetic
R2 baseline correct those test assumptions. Both affected tests and both source/revision
checks passed together in the final four-test recheck. Assertions remain intact.
Earlier affected import/edit/color/transaction workflows passed; no full regression ran.
Build/typecheck, changed-component lint, Python lint, Lucide and test-map checks passed.
Screenshots were reviewed at light 375px and dark 1600px; all eight boundaries were asserted.
Original workbooks, generated browser artifacts and private state remain outside Git.

### Fast Validation #202–204 investigation and closeout

Actual GitHub log archives were retrieved for runs 41622087242 (#202, dd7a869),
41624819081 (#203, 8571572) and 41625364049 (#204, 67a2a86). All failed job
**Backend & Frontend**, step 11 **Run the selected backend tests**; exit code 1.
The failing command was `python scripts/ci.py run backend -- python scripts/run-tests.py changed --stage backend`.
No workflow/dependency files changed relative to the last successful #201 (64cfedf).
These are confirmed code/contract-test failures, not an environmental explanation.

- #202: 1045 backend tests, two skipped, three failures. Relationship-only fields entered
  description snapshots, failing `test_a_snapshot_carries_its_own_descriptions_only_for_risks_and_activities_in_scope`
  and `test_reports_without_any_description_are_unchanged`. Production fix 8571572 excludes
  those context fields. The third failure was the reference assertion below.
- #203 and #204: 1045 tests, two skipped, one failure each:
  `test_exact_case_and_prefix_ids_do_not_enrich_or_activate`, line 98, asserted
  `found['activities'] == {}`. The supported metadata API now intentionally carries active
  relationship context without descriptions. The assertion remained outdated after dd7a869.
- The corrected test asserts the complete expected imported A–E relationship dictionaries
  and empty origins, and explicitly excludes unmatched case/prefix reference IDs. Zero
  reference matches and absence of an enriched risk name remain mandatory. Assertions are
  strengthened around exact matching; the production matcher is unchanged.

The sole remaining failure was reproduced locally with Python 3.12 and
`-W error::DeprecationWarning` before correction. After correction: 31 focused reference,
report/snapshot and example-parser tests passed. The exact CI backend command, using
`CI=true` and `BASE_SHA=67a2a86df3142be4ed31b966dae6e68fd919c042`, selected nine affected/
repository modules and passed 93 tests, zero skipped/failed. This was NOT a full backend or
browser regression. Workflow logs contain intentionally mocked failure messages from runner
safety tests; final test outcomes, not those message substrings, determine success.

Reference inventory is now canonical in docs/data/SOD_MATRIX.md. The versioned 14/14/six
library, synthetic XLSX template, generator and separate synthetic matrix CSV are accounted
for. P001/P002/P008/PR01 are present in bundled data and exact round-trip tests. The template
remains synthetic, avoiding duplicate business data and preserving original source material
outside Git. README/AGENTS links remain valid; duplicated current configuration guidance was
already consolidated, and historical validation/privacy records are preserved.

No production/frontend code or dependencies changed in this closeout batch. Prior targeted
Playwright, TypeScript and production-build results for 67a2a86 remain applicable; they were
not redundantly rerun. No full regression, native platform acceptance, release or manual
workflow dispatch was performed. Historical #202–204 remain failed runs; a new automatic
Fast Validation result must be observed before claiming CI green for the corrected commit.

### Modal navigation header simplification

Risk and Activity detail headers now show only Previous, current position and Next.
The bounded internal history remains; related pills still navigate across entity types.
The existing unsaved-change guard protects cross-navigation and closing. Three focused
browser checks passed: discard accept/cancel and cross-entity transitions, filtered-list
boundaries/cross-page navigation, and the narrow layout. TypeScript/production build passed.
No full regression; no version or backend changes.

### Decision-first review status and popovers

Audited persisted enums: assignment Pending/Keep/Remove/Investigate, activity Pending/
Approved/Conditional/Remove, acceptance Pending/Accepted/Rejected. Lifecycle handles stale,
expired and historical evidence. Coverage is separate and cannot grant approval. Pure
subject-row summaries now expose the authoritative current decision; activities with mixed
supporting role decisions show Mixed decisions unless explicitly decided. Unanimous role
retention derives completion only. Risk primary badges show formal acceptance, while the
coverage progress count is labelled reviewed. No stored enum, approval gate or export changed.

Shared popovers retain user, period, assignment identity/validity, reviewer/time, evidence,
role-decision distribution and risk acceptance metadata without nested popovers. Bulk and
single actions refresh the same authoritative subject. Shared lifecycle labels show Keep as
Approved and Investigate in amber. A confirmed Escape bug closed the surrounding review panel
as well as its popover; the shared ownership guard now handles either document-listener order.

Targeted evidence: 52 coverage/bulk tests, 53 governance tests and an additional formal-
acceptance summary test passed. TypeScript/build and changed-component lint passed. Initial
browser checks passed bulk/progress workflows but exposed the shared Escape bug. All nine
affected keyboard/status rechecks passed, including eight light/dark 375/800/1280/1600
popover previews and explicit Keep/Remove/Investigate, mixed activity decisions and independent
risk acceptance. Two shared-library/Saved Filters Escape checks passed. No full regression.

### SoD request-local decision snapshot profiling

Stages 1–2 were delivered in `c30c3a5` and `58e5d01`; automatic Fast Validation runs
41650215869 and 41655377485 passed. The performance stage reuses one validated live
decision-store snapshot per request bundle, keeping response revisions coherent with
rows and avoiding repeated JSON parsing. Write/preview guards remain live; frozen-period
decisions and approval-date lifecycle remain unchanged. No source cache or dependency added.

Comparable isolated real-import/API profiles (200 synthetic users, 800 assignments, nine
samples) reduced subject-view p50 from 44–54 ms to 20–24 ms; store reads fell from two/three
to one on most routes. Explorer retains two separate reads. Complete measurements, tail
regressions/noise and memory caveats are in [SoD architecture](../architecture/SOD.md#measured-request-local-review-state-reuse).
No real employee data, uploaded workbooks or generated benchmark artifacts were committed.

FEATURE: 139 targeted tests passed in 74.582s across review coverage, bulk review, governance,
periods v2 and report metadata. Added request-snapshot read-count/coherent-revision tests
and confirmed fresh requests see committed decisions. Existing tests cover stale revisions,
atomic failure, source evidence changes, context isolation, frozen decisions and reports.
The logged injected RuntimeError in the governance failure test is expected; the suite passed.
Ruff, Python compilation, test-map ownership and documentation links (94 files) passed.
Stage 2 frontend typecheck/build, lint and focused browser evidence remain valid: this stage
changes no frontend code/assets/contracts. Full regression, dependency audits and packaging
were intentionally not repeated. Native Windows/WebView2/SCM, UNC and real systemd acceptance
remain unexecuted. New automatic CI status must be checked after push; local checks are not
a claim of platform package validation.

### Backup recovery and guided restart

The stopped-store archive engine is retained: atomic per-file writes are not a shared
transaction across settings, imported snapshots, review history and background jobs.
No online snapshot or remote restart is claimed. Backup requests now expose Waiting for
restart, Creating, Ready, Failed and Cancelled, normalize legacy pending records, and
recover interrupted creation at next startup. Restore journals remain authoritative;
cancellation cannot release active creation or journal-owned recovery. Corrupt metadata
without a journal is recoverable rather than an indefinite application-wide write freeze.

A pending backup leaves configuration GET readable (verified by API test). The reported
configuration error was not reproduced as an inherent pending-state failure. Settings now
provides Retry configuration and renders Backup & Restore independently. Validated uploads
are explicitly labelled staged server-side archives rather than current native file-input
selections. Upload validation has a 60-second bounded request and safe cancellation; neither
cancellation nor timeout confirms restoration. Existing startup verification, rollback,
credential exclusions, authentication and native/browser download boundaries are retained.

FEATURE evidence: 40 backup/scheduler tests plus the new scheduler-cancel recovery test
passed; after the final journal-state correction, all 25 backup tests passed. TypeScript /
production build and changed-component lint passed (Settings retains five pre-existing Hook
warnings). Nine browser workflow/theme/viewport checks passed; the initial configuration-
failure case exposed the startup gate blocking recovery. After adding the independent,
authenticated recovery entry, that case, safe validation cancellation and existing startup
retry behavior all passed (three focused rechecks). Loopback proxy routing initially blocked
test-server detection; command-local NO_PROXY for localhost fixed the environment issue.
No full regression or native Windows acceptance was run; screenshots cover both themes at
375/800/1280/1600. Scheduling/history is a separate additional stage, not claimed here.

### Backup schedule, retention and history

Private destination-local scheduling reuses RefreshSchedule/cron rules, disabled by default,
with retention default seven successful scheduled archives. A scheduled occurrence queues a
restart request (not unattended online archive creation), claims once, skips busy imports or
operations, and retains fifty request outcomes. The single-process runtime lease remains
mandatory; no multi-worker writer support or host restart API was added. Backup-schedule
errors are isolated from the independent data-refresh scheduler.

History records verified archive size/hash/source/status; manual archives are never pruned.
Confirmed deletion and retention protect active/journal-owned operations, staged restore
originals and recovery archives. Free space is checked before stopped-state creation, and
downloads revalidate canonical archive integrity. Missing archives no longer report Ready.
The five-zone UI shows schedule limitations, local storage usage, recent history and recovery.

FEATURE: 46 backup/scheduler tests passed; 31 backup tests passed after integrity checks;
21 focused authorization/test-profile checks passed. Additional schedule isolation/claim
rechecks (2) and corrupt-download HTTP regression (1) passed. Twelve affected browser cases
ran with one worker: eleven passed; adding the schedule checkbox exposed an ambiguous old
restore test locator. Naming the actual restore-confirmation checkbox fixed it; its focused
recheck passed. Coverage includes both themes at 375/800/1280/1600, initial configuration
failure recovery, safe upload cancellation, restore preview/confirmation and schedule errors.
Representative light desktop/dark mobile screenshots were inspected; no page overflow.
TypeScript/production build, focused lint, Ruff, docs and test-map checks passed. Full
regression, native Windows lifecycle and real service restart acceptance remain unexecuted.

### Revised SoD decision model — backend

The approved model supersedes the earlier coverage-only activity presentation. A current
Keep supplier derives activity Approved even alongside Remove/Investigate; all Remove
derives Remove; otherwise Investigate wins over Pending. Current explicit activity review
wins and exposes disagreement. Legacy Conditional events remain intact (primary Investigate).
Stale approvals grant nothing; no-supplier access does not derive removal. Normal risk
review is a separate kind in the existing append-only store and uses the same evidence,
revision, permission and period guards; it does not alter role events or formal acceptance.
Normal risk decisions are exposed separately in subject data for the next UI migration.

Targeted evidence: initial four-module run executed 125 tests, with 115 passing and ten
failures (obsolete primary-label expectations and a three-kind queue-count assumption).
Updated expectations follow the newly approved rules; queue totals still count each review
category once. Sixteen coverage/semantic tests and the three affected queue cases passed
after correction; fifteen frozen-period/report-metadata checks passed. An additional explicit
activity Investigate/no-suppliers/permission check passed. Normal risk period isolation,
append-only history, independent formal acceptance and frozen persistence are covered.
Ruff/docs/whitespace checks passed. No full regression or frontend rebuild was needed for
this backend-only stage; shared badge/action/UI migration is the next stage, not claimed here.

### Revised SoD decision model — shared review UI

Roles, Activities and normal Risk Review share Approved/Remove/Investigate/Pending badges
with CheckCircle2/Trash2/Search/Clock3 and semantic tones. Risk Review and Formal acceptance
have separate actions/forms and histories in the same Risks tab. Popovers expose role-derived
sources, explicit disagreement, supplier decisions and independent formal metadata. New
primary-badge demos use isolated values in the Component Library. Current catalogue role
descriptions are not substituted into frozen-period headers.

Thirteen focused SoD browser cases passed after correcting a Risk-label/filter-map collision
caught by the first run (stopped once the shared cause was confirmed). Tests cover normal
risk Approved/Remove/Investigate without formal acceptance or role changes, bulk updates,
all themes/widths, keyboard/Escape/focus and reviewer draft retention. Two final component-
library/disagreement checks passed. Three affected scope/mobile-layout checks passed; the
wide-row check found action wrapping. A compact, labelled formal-acceptance IconButton and
secondary formal status restored alignment; its focused browser recheck passed.
TypeScript/production build, focused lint, documentation links and Lucide catalog passed.
No full regression, product-version change or native platform acceptance was performed.

### Automatic CI closeout — configuration cache concurrency

Fast Validation runs 41676113856 (`0122b96`) and 41677451557 (`441cbf7`)
failed `test_legacy_migration_keeps_original_backup`: the migration notice became None.
The actual logs were downloaded and inspected. This was a real cache-miss race, not an
assumed fixture failure: lru_cache permits duplicate concurrent function execution even
though the loader locks its body. A second miss reread the migrated file and cleared the
first caller's notice. Public configuration reads/cache clearing now take the existing
RLock before entering the cache, retaining its external cache_clear/cache_info contract.

An eight-thread synthetic reproduction measured eight misses, distinct results and a lost
notice with the old cache behavior; single-flight reads measured one miss, one shared result
and a retained notice. Fifteen configuration tests passed, including the new concurrent
migration regression. Sixty-eight backup/scheduler/SoD-import checks passed after the fix.
No full local regression was run. Historical failed CI runs remain failed; a new automatic
run is required before claiming the final remote commit has green CI.

### Final SoD integration and CI UI closeout

Removal verification now checks all actual imported assignments, including expired and
non-conflicting records; disappearance from a filtered SoD result is not removal. One
coherent source cut is reused for remediation rows/counters/actions, restricted to affected
users. Assignment history/popovers expose source hash/import time and the original event ID;
Remove events are never rewritten. Newer source evidence, complete matching within the
supplied export scope and no validation errors are required for verified absence. External
CSV truncation cannot be proven from these schemas; full-export scope remains an operator
responsibility. Frozen review/report evidence retains its captured semantics.

Matrix, Explorer and remediation primary badges now use the same effective projection as
the review panel; raw lifecycle, explicit-review counters/filters, formal acceptance and
existing CSV columns keep their meanings. Conditional compatibility was corrected during
final semantic review: a current Conditional event is Approved with recorded conditions,
not Investigate. Its form option, required controls, raw event and history are retained.
No fifth primary badge or synthetic approval record was introduced.

Targeted evidence: 44 matrix/review/remediation/coverage tests passed; 35 source lifecycle,
frozen-period and report checks passed; 10 verifier source-cut rechecks and three final
raw-presence/history/frozen checks passed. Six browser integration cases, a removal-popover
recheck and Conditional approval/form compatibility check passed. The original role decision
and later source provenance remain separately inspectable. No complete regression was run.

Actual CI 41679706854 failed seven changed browser cases: six source-layout cases still
expected the retired duplicate `.source-file-row`, and the legacy Conditional tile inherited
the new primary-label projection. The source tests now assert one Browse / Upload action,
no redundant Browse CSV button and a usable optional advanced path field across three
widths/both themes. The counter is explicitly Conditional activities (legacy). All seven
failed cases passed locally after correction; no assertions were disabled or skipped.

Final restore review added explicit cancellation of an inactive validated preview, releasing
its retention protection without clearing an active operation/recovery lock. Backend and
browser preview-cancel/confirm checks passed. Authenticated administrator HTTP download was
verified byte-for-byte; read-only users remain denied. Existing mocked native-dialog tests
remain unit evidence, not native Windows acceptance. Latest TypeScript/production build,
focused ESLint, Ruff, Lucide catalog, documentation links and test-map/whitespace checks passed.
Dependencies, product version and main were unchanged. Changed-code review introduced no
real employee data/reference workbooks or detected credential-pattern matches. Full local
regression, dependency re-audits and native Windows/SCM/systemd acceptance were intentionally
not repeated. Historical CI failures remain failed runs; final automatic CI must be reported
separately after push, without claiming unexecuted package/runtime acceptance.
