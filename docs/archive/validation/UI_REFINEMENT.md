# UI refinement records

> Historical evidence: applies to the source/phase recorded below, not later
> commits. Use the [current documentation index](../../README.md) for instructions.

## UI completion and data-aware refinement — 2026-10-22

Baseline: clean `work` at `4267d0d2006968f50947cd37ba3a60f3193fe406`.
The earlier local commits `893acb9` and `4267d0d` remain in history. Both user
requests are implemented as one combined refinement; neither supersedes the
other. The actual current production frontend was built and browser-rendered
before changes. That baseline already used header navigation, independent import
tabs and the shared combobox; its remaining layout gaps were confirmed visually.
There is one frontend entry (`frontend/src/main.tsx` → `App.tsx`) and no duplicate
rendered page implementation. Tests serve freshly built `frontend/dist` through
the real isolated backend, not a static design mock or an older executable.

### Implemented changes

| Area | Rendered improvement |
| --- | --- |
| Global header | Existing integrated primary navigation retained, with compact icon labels/tooltips; no second content navigation. History now preserves meaningful app destinations and detail traversal. |
| Import sources | Both tabs use the same numbered Source file / CSV Import Format / Column mapping / Validation & preview cards. File and folder action share a row; compact preset icon toolbar has accessible names, tooltips and built-in protections. Automatic inspection and independent drafts/mappings remain. |
| Release filters | Shared responsive surface, bounded CSV-driven searchable facets, explicit unavailable-selection warnings, Reset filters and grouped assignment/display controls. Table/Matrix is one segmented selector next to results. |
| Investigation tables | Larger text, deliberate row padding/widths, distinct role/copy/navigation affordances, singular/plural labels and separate status evidence. Relevant role counts open the supported user details. |
| User details | Balanced identity and validity/account cards, responsive stacking, lock state presented once for one account; distinct source records retained in expandable evidence. Single-page table pagers removed; global detail navigation preserved. |
| Role Lookup | Existing module colors and cards retained. The comparison plus remains an actual Add action. Card footers align; statistics use consistent number/label sizing. |
| Comparison | Readable matrix count/percentage cells are keyboard buttons. Dialog uses native modal focus containment, Escape and explicit focus restoration. Shared rows have a meaningful Layers fallback, readable descriptions and one page scroll; exclusive columns remain side by side with deliberate horizontal overflow. Calculations unchanged. |
| SAP identifiers | Readable monospace, compact centered copy controls and full wrapping; copy confirmation retains a full row. Navigable identifiers have an arrow separate from their copy button. |
| Diagnostics | Separate private cards for both configured/loaded sources, counts, load timestamps and static error categories. Export remains allowlisted and path/data-free. Availability describes last-read evidence, never an unperformed live UNC check. |
| Branding | Padded logo preview, aligned/wrapping action group with icons and shorter visible reset action; upload validation/storage untouched. |
| Loading/navigation | Native handoff replaces bootstrap history. App Back/Forward has a first-view boundary initialized before configuration/startup rendering and does not reload or start the backend. Initial setup, contextual CSV loading and a service-unavailable retry banner are distinct. |

[Facet behavior and investigation semantics](../implementation/ACCESS_INVESTIGATION.md#data-aware-release-filters-and-navigation),
[API additions](../../architecture/API.md#get-apiaccessrelease-options) and
[desktop handoff/native acceptance](../../architecture/DESKTOP.md#navigation-handoff-and-backforward-validation)
record the architecture and privacy boundaries. No dependency, lockfile,
classification, CSV schema, persisted configuration schema, README branding,
canonical asset, packaging format, signing or workflow change belongs to this task.

### Changed files

Exact paths for the combined task (new files included):

```text
backend/cache.py
backend/data_loader.py
backend/desktop.py
backend/diagnostics.py
backend/routers/access.py
backend/tests/test_desktop.py
backend/tests/test_user_access.py
docs/archive/implementation/ACCESS_INVESTIGATION.md
docs/architecture/API.md
docs/architecture/DESKTOP.md
docs/archive/validation/UI_REFINEMENT.md
frontend/src/App.tsx
frontend/src/components/Access/ReleaseFilter.tsx
frontend/src/components/Access/ReleaseRoles.tsx
frontend/src/components/Access/Shared.tsx
frontend/src/components/Access/UserAccess.tsx
frontend/src/components/Layout/AppLayout.tsx
frontend/src/components/Layout/StartupGate.tsx
frontend/src/components/RoleComparison/ComparisonView.tsx
frontend/src/components/RoleList/RoleCard.tsx
frontend/src/components/RoleList/RoleList.tsx
frontend/src/components/Settings/Diagnostics.tsx
frontend/src/components/Settings/ImportPresets.tsx
frontend/src/components/Settings/ImportSection.tsx
frontend/src/components/Settings/SettingsView.tsx
frontend/src/components/Settings/SourceStatus.tsx
frontend/src/components/Shared/Combobox.tsx
frontend/src/components/Shared/InvestigationNavigation.tsx
frontend/src/components/Shared/RoleIdentifier.tsx
frontend/src/hooks/useViewHistory.tsx
frontend/src/index.css
frontend/src/main.tsx
frontend/tests/access-investigation.spec.ts
frontend/tests/data-aware-ux.spec.ts
frontend/tests/desktop.spec.ts
frontend/tests/global-navigation.spec.ts
frontend/tests/investigation-ux.spec.ts
frontend/tests/ux.spec.ts
```

### Validation and visual evidence

Final complete validation passed against unchanged tracked **and new** source;
file manifests were compared before/after the run. No test was removed, skipped
or configured to retry. Backend count increased from 186 to 193; browser count
from 55 to 66. Intentional UI assertions were updated for fragment routes
(also explicitly checking capability removal), hidden single-page pagers and
Tab moving into the next combobox. An earlier run exposed an obsolete empty-
fragment assertion; the final complete suite passed after correction.

| Executed command/check | Final result |
| --- | --- |
| `git diff --check` | Passed |
| `.venv/bin/python scripts/ci.py lint` | Passed (workflow YAML/schema/expressions) |
| `.venv/bin/python scripts/check-workflows.py` | Passed (triggers, permissions, concurrency, job/artifact contracts) |
| PowerShell 7 `-NoProfile -File scripts/check-powershell.ps1` | Passed on Linux (syntax/static guards, not Windows execution) |
| `npm --prefix frontend ci --cache /workspace/.npm-cache` | Passed |
| `node scripts/sync-lucide-catalog.mjs --check` | Passed |
| `npm --prefix frontend run check:types` | Passed |
| `npm --prefix frontend run build` | Passed; tests served these fresh production assets |
| `.venv/bin/python -W error::DeprecationWarning -m unittest discover -s backend/tests -v` | **193 passed**, 5.686 seconds |
| `.venv/bin/python -m pip check` | Passed |
| Isolated `pip_audit --path /workspace/sap-lens/.venv/lib/python3.12/site-packages --cache-dir /workspace/.pip-audit-cache --progress-spinner off` | No known vulnerabilities in the installed Linux environment |
| `npm --prefix frontend audit --omit=dev` | Zero production vulnerabilities |
| `PLAYWRIGHT_EXECUTABLE_PATH=/usr/bin/chromium PATH=/workspace/sap-lens/.venv/bin:$PATH npm --prefix frontend run test:browser -- --reporter=line` | **66 passed**, 2.4 minutes, one worker, zero retries |

The complete npm audit retains seven pre-existing development advisories (five
high, two moderate); no package or lockfile changed. Environmental pip cache
ownership and NO_COLOR/FORCE_COLOR notices remain visible. No application Python
deprecation occurred under strict warnings. Windows-only dependency auditing
and native executable validation remain pending a Windows runner.

Visual review covered 104 current required-surface captures (26 per theme/width),
plus three-role comparison/dialog captures in both themes. Four overview sheets
and same-width before/after comparisons were inspected, with full-size review
of details, source cards, branding, loading and comparison. Header navigation,
separate source tabs, popup geometry, readable status/identifiers and intentional
contained table overflow were verified. Review found and corrected a duplicate
legacy loading strip. Startup preview now uses a fresh HTML navigation, so the
real palette script executes under the startup document's CSP; it is not a
misleading setContent preview inheriting the app's stricter response CSP.

**Implemented and visually verified:** the modified frontend surfaces listed
above, in light/dark at 1280 and 800 px. **Implemented but not natively verified:**
the desktop startup replacement and actual mouse Back/Forward inside WebView2.
**Not performed:** native file dialogs, permitted UNC reads, Windows packaging,
packaged smoke/PE verification and interactive target-PC acceptance. No requested
frontend feature was deliberately deferred. Availability is explicitly last-read
evidence; the diagnostics endpoint intentionally does not probe a possibly
stalled network share. Existing packaged verification rules are unchanged.
Screenshots and exact command logs are outside Git in
`/workspace/sap-lens-dev/ui-completion/`. Baseline and current images cover light
and dark at 1280×900 and 800×900, including every import stage, Table/Matrix,
combobox popups, details, comparison, source diagnostics, branding, contextual
loading and the authored startup document. These are synthetic local fixtures.
Native Windows/WebView2, actual file dialogs/UNC and a newly packaged executable
are not available here and remain pending explicit authorization and a Windows
runner/target PC. No push, remote build, tag or release is authorized/performed.


## Global navigation and desktop readiness — 2026-10-22

Baseline: clean `work` at `893acb90d0fcdbe1ec8170b0ab2a7faad0076111`; the
previous UI work is retained. This follow-up removes the page-local detail limit
without another redesign. User and release navigation now asks the same list API
for a global position and adjacent identities, with all filters/sorting retained.
It requests `limit=1`, not an unbounded list, and does not cache one response per
visited identity. Loading/errors disable traversal, missing/filtered records stay
explicitly unresolved, and deleted users no longer display stale cached details
once their detail request fails. Normal list responses are unchanged.

Returning from details restores the original table page and focus/scroll where
possible. After a shrinking refresh, obsolete user/release/matrix page offsets
are clamped. An unchanged debounced release search no longer resets pagination.
Direct user investigations locate their true global index; direct release
investigations use the same all-status context in both details and their list.

New synthetic backend and browser tests exercise 125 matching records, boundary
crossings, ascending/descending tie order, filtering, first/last controls, direct
investigations, refresh/removal and origin restoration. Existing UI tests and
all native packaging/security guards are retained. README, dependency manifests,
classification, CSV schemas and Windows/release workflows are unchanged.

The execution environment is Linux, with no attached Windows desktop, Wine,
WebView2 automation or accessible SMB share. Native acceptance remains **pending**;
no old Windows run is claimed to validate this new candidate. The concrete
[target-PC QA checklist](../../architecture/DESKTOP.md#candidate-native-desktop-qa) separates build/
smoke evidence from actual UI, native picker and UNC acceptance. No push,
workflow dispatch, tag change or release publication is authorized/performed.

### Local verification of global navigation

The final source passed the following Linux checks before commit; no tests were
removed and no retries were enabled:

| Command/check | Result |
| --- | --- |
| `git diff --check` | Passed |
| `.venv/bin/python scripts/ci.py lint` and `.venv/bin/python scripts/check-workflows.py` | Passed |
| PowerShell 7 `-NoProfile -File scripts/check-powershell.ps1` | Passed (Linux parsing/static checks) |
| Parser-only check of the native QA fixture block in `docs/architecture/DESKTOP.md` | Passed; no Windows execution claimed |
| `npm --prefix frontend ci --cache /workspace/.npm-cache` | Passed |
| `node scripts/sync-lucide-catalog.mjs --check` | Passed |
| `npm --prefix frontend run check:types` and `npm --prefix frontend run build` | Passed |
| `.venv/bin/python -W error::DeprecationWarning -m unittest discover -s backend/tests -v` | 186 passed |
| `.venv/bin/python -m pip check` | Passed |
| Isolated installed-environment Python audit using `pip_audit --path /workspace/sap-lens/.venv/lib/python3.12/site-packages --cache-dir /workspace/.pip-audit-cache --progress-spinner off` | No known vulnerabilities |
| `npm --prefix frontend audit --omit=dev` | Zero production vulnerabilities |
| `PLAYWRIGHT_EXECUTABLE_PATH=/usr/bin/chromium PATH=/workspace/sap-lens/.venv/bin:$PATH npm --prefix frontend run test:browser -- --reporter=line` | 55 passed, 1.9 minutes |
| Documentation/asset reference checks after documentation updates | Passed |

The five new browser cases cover forward/back traversal across boundaries,
ascending/descending filtering, first/last controls, the original page/focus/scroll,
direct investigations and refresh/removal, including an obsolete last page.
Six new backend tests check every supported sort, tie-breaks, evidence/status/
classification filters, normalization, missing anchors and protected/bounded input.
New global-position screenshots were inspected in light and dark themes. Existing
UI/combobox/theme regressions also passed. Validation logs/screenshots are outside
Git. The final source diff was compared with the validated snapshot before commit.

Full npm audit retains seven pre-existing development advisories (five high,
two moderate); manifests and locks are unchanged. Native Windows build, EXE smoke,
interactive WebView2, actual native dialogs and real UNC reads remain **pending**.
The documented build-only approval path and target-PC checklist are the remaining
gates; this record does not declare the candidate ready for publication.

## Investigation and import refinement — 2026-10-22

Baseline: `work` at `167f9186d1718b048f696181135b5f5654bf2e52`, clean.
This is a local frontend refinement. Backend contracts, role matching, dates,
transaction calculations, configuration schema, dependencies, README branding,
module colors/icons and all Windows/release workflows are preserved.

Implemented:

- Move the three primary destinations into the header; retain view state and
  restore the saved page scroll position. Settings disables background navigation.
- Separate Role Catalogue and User Access import panels with accessible keyboard
  tabs, independent drafts and shared file/status styling. Automatic inspection
  retains manual mappings; errors cannot silently erase saved mapping choices.
- Keep source paths, preview validation and the last successful data load distinct.
  Explain unavailable native browsing and protected preset deletion.
- Reuse `DetailNavigation` for breadcrumbs and scoped Previous/Next boundaries;
  restore list focus/scroll when returning from details.
- Group release classification, assignment and display filters; make release
  identifiers clickable while retaining their separate copy action. Use correct
  user/record plurals and semantic evidence badges.
- Separate account summary/evidence and use one assignment status selector without
  changing validity interpretation. Keep large transaction lists expandable.
- Improve secondary typography and let comparison sections share document scroll
  rather than independently capped columns. The role-card plus still adds to
  comparison, so replacing it with a detail icon would misrepresent its action.
- Add a portal-based `Combobox` without dependencies. User-group filters accept
  typed values; mapping selectors only commit real options. Shared search/check/
  disclosure icons, ARIA listbox/combobox semantics, keyboard selection, outside
  click, cancellation and viewport positioning replace every native datalist.
  Existing module buttons, icon search dialog and small static selects are retained.

Shared components: `Combobox`, `DetailNavigation`, `EvidenceBadge`, `SourceStatus`,
`RoleIdentifier` (optional identifier navigation), and directional `Pagination`.
No parallel theme system is introduced; all surfaces use existing semantic tokens.

Regression coverage adds navbar location/state, detail boundaries, unified status,
source independence, automatic detection/retry, long synthetic UNC paths and
combobox keyboard/mouse/empty-state/viewport behavior, async option scrolling and selected-tab hover contrast. Existing import, evidence,
copy and configuration assertions are retained and adapted to intentional controls.
Visual tests capture all nine requested views, mapping popups and release-group
popup in both themes at 1280 and 800 pixels. Before images use the beta-2 frontend
extracted for static serving only, with synthetic data and isolated settings; no
EXE is executed or built. Screenshots/logs remain outside version control.

Original limitation (superseded by the subsequent global-navigation refinement):
detail Previous/Next was scoped to a result page;
loaded per-source paths are not exposed by the current API; actual UNC access,
WebView2 rendering and packaged Windows behavior still require authorized native
validation. No push, workflow dispatch or release publication belongs to this task.

### Local validation of this refinement

All checks below were executed against the final source before the local commit.
The browser suite uses system Chromium and synthetic fixtures, one worker and no
retries; **50 tests passed (1.7 minutes)**. No existing test was removed.

| Command/check | Result |
| --- | --- |
| `git diff --check` | Passed |
| `.venv/bin/python scripts/ci.py lint` | Passed (workflow schemas/expressions/actionlint) |
| `.venv/bin/python scripts/check-workflows.py` | Passed |
| PowerShell 7 `-NoProfile -File scripts/check-powershell.ps1` | Passed on Linux |
| `npm --prefix frontend ci --cache /workspace/.npm-cache` | Passed |
| `node scripts/sync-lucide-catalog.mjs --check` | Passed |
| `npm --prefix frontend run check:types` | Passed |
| `npm --prefix frontend run build` | Passed |
| `.venv/bin/python -W error::DeprecationWarning -m unittest discover -s backend/tests -v` | 180 passed; repository/privacy, settings/migrations, CSV, matching, archive and release guards included |
| `.venv/bin/python -m pip check` | Passed |
| Installed-environment Python audit via isolated `pip_audit --path /workspace/sap-lens/.venv/lib/python3.12/site-packages --cache-dir /workspace/.pip-audit-cache --progress-spinner off` | No known vulnerabilities |
| `npm --prefix frontend audit --omit=dev` | Zero vulnerabilities |
| `PLAYWRIGHT_EXECUTABLE_PATH=/usr/bin/chromium PATH=/workspace/sap-lens/.venv/bin:$PATH npm --prefix frontend run test:browser -- --reporter=line` | 50 passed |
| Documentation/asset link checks after documentation updates | Passed |

Full npm auditing retains seven development advisories (five high, two moderate).
No dependency manifest or lockfile changed. Native Windows EXE packaging, actual
UNC reads and interactive WebView2 QA were **not run**; passing Linux tests cannot
substitute for them. README, canonical assets, backend and workflows have no diff.
Before/after images and all twelve screenshot surfaces per theme/width are kept
outside Git in the local UI validation artifacts, including mapping popup views.

## Earlier classification refinement (historical)

> Historical implementation record. The later approved classification removal and two-source access architecture supersede the profile UI described here. See [current access investigation](../implementation/ACCESS_INVESTIGATION.md).


Baseline: local CI commit `3bb960d766828b6c208992a3ad4f724d8154c59b` on work.
The separate CI implementation is retained unchanged by this UI task. No push,
workflow dispatch, packaging/signing change or destructive settings migration.
The protected README and canonical application assets remain untouched.

## Findings and safe changes

| Issue | Root cause | Change |
| --- | --- | --- |
| Data-source warning width | Its own mx-5 layout bypassed the dashboard's max-width/padding container | Match the main max-w-screen-2xl container and responsive horizontal padding |
| Review data source opens the wrong section | AppLayout only toggled settingsOpen; mounted SettingsView retained its previous section | Explicit request counter selects Data Source & Import and focuses/scrolls the CSV path into view. Normal Settings opening keeps intentional section history |
| Colored navigation edge | Two CSS rules painted an inset 3px selection shadow | Remove both; retain subtle selected background/text and the complete keyboard focus outline. Neutral comparison-grid dividers are structural, not selection indicators |
| Too few area colors | Many registry entries shared dark colors; icon contrast fallback replaced them with the same text color; the 10% tint further hid differences | Curated, stable ID-based defaults for all 49 areas, restrained 18% tints and hue-preserving contrast adjustment to at least 3:1. Unknown Legacy area IDs use a deterministic ID hash, not registry order. Existing icon mappings and explicit saved colors remain unchanged |
| Disconnected filter checkbox | The checkbox occupied a generic grid cell with little explanation. Its value is already the same enabled flag used by status | One clickable settings row, clear label/help, keyboard focus treatment and a single existing boolean. Disabling hides the area as a filter choice, not its roles or transactions |
| Classification usability and misleading preview | Advanced profile creation was prominent. The single-role preview lacked CSV evidence and reasoning; dataset preview ignored multi-source conflicts | Saved-versus-draft method explanation, advanced profile creation behind disclosure, optional source-area evidence, loaded-role evidence, explicit rule/override/fallback/no-match explanations and an accurate read-only conflict preview |
| Inconsistent affected controls | Checkbox grouping and an unstructured test-result paragraph did not use the surrounding form/card layout | Reuse existing settings cards, status-list layout, radius, spacing, colors and focus tokens; no parallel styling system |

An additional related defect was found: the registry API returned only effective
saved appearance values, so resetting a custom color could preview that same
custom value until saving. Registry entries now expose canonical default name,
icon and color separately. The editor can preview a genuine reset; Cancel still
restores the saved override. This changes no configuration schema or saved value.

## Classification decision

**SIMPLIFY**, with full evidence, consumers, options A–D and a future migration
plan in [the architectural assessment](../implementation/CLASSIFICATION_ARCHITECTURE.md). SAP Modules
owns presentation/catalog/filter availability; classification owns role area and
optional business-domain assignment. A reliable CSV area column often makes
custom rules unnecessary, but the engine still normalizes aliases, handles
conflicts and supports distinct Legacy child labels and optional domains.

Actual synthetic imports show CSV FI on Z_DEMO_BUYER remains FI in Generic and
Legacy, while an explicit Custom rule changes it to MM/buying. LOCAL_FIN remains
a source label in Legacy, becomes UNCLASSIFIED in Generic and can map to FI in
Custom. Each profile retains five transactions, six assignments and six
relationships; comparison intersections remain identical. Do not infer that a
profile is redundant because its presentation was unclear.

No active profile, default profile selection, custom rule, fallback, override,
area identifier, CSV mapping, relationship or transaction semantics is changed.
The preview API gains optional test_source_module and additive explanation fields.
An existing loaded name uses its source evidence when no sample area is supplied.
It mirrors the loader's existing conflict policy; it never publishes a cache
generation or saves settings. The main production Classifier.classify and cache
construction algorithms are unchanged.

## Changed files

| Paths | Purpose |
| --- | --- |
| `backend/classification.py`, `backend/configuration_routes.py` | Read-only preview source context, conflict fidelity and explanation |
| `backend/module_registry.py` | Stable visual palette, discovered-ID colors and canonical editor defaults |
| `backend/tests/test_classification_review.py` | Real synthetic profile comparisons, preview isolation, persistence/export and color preservation |
| `frontend/src/components/Layout/AppLayout.tsx`, `frontend/src/components/Settings/SettingsView.tsx` | Explicit data-source navigation, warning layout and simpler method/preview controls |
| `frontend/src/components/Settings/ClassificationExample.tsx`, `frontend/src/api/configuration.ts` | Typed, human-readable preview including CSV replacement warnings |
| `frontend/src/components/Settings/ModuleEditor.tsx` | Cohesive filter availability and correct default-reset preview |
| `frontend/src/components/Modules/ModuleIcon.tsx`, `frontend/src/components/Modules/ModuleRegistry.tsx`, `frontend/src/lib/theme.ts` | Readable hue-preserving visuals and stable discovered-area defaults |
| `frontend/src/index.css` | Remove selection edge; use existing tokens for filter row/focus |
| `frontend/tests/navigation-classification.spec.ts`, `frontend/tests/enterprise.spec.ts`, `frontend/tests/role-visuals.spec.ts`, `frontend/tests/settings-refinement.spec.ts` | New regressions and existing assertions updated for the intentional labels, structured preview and default palette changes; no tests removed |
| `docs/archive/implementation/CLASSIFICATION_ARCHITECTURE.md`, `docs/archive/validation/UI_REFINEMENT.md`, `docs/architecture/DESKTOP.md`, `docs/development/CI.md` | Review, migration boundaries, implementation record, navigation and coverage wording that remains accurate as tests are added |

## Visual evidence and platform limits

The seven referenced screenshots were not available among the visible uploads.
Own before/after captures use the actual application with generic synthetic
settings, in light/dark mode at 1920×1080 and narrower 768×900 viewports. They
cover the warning, area list, filter editor and classification preview. Capture
files and validation logs stay outside Git under the cloud task's
`/workspace/sap-lens-dev/ui-refinement/` directory. They are not application assets
or Windows distribution inputs.

Browser reload checks frontend restart behavior; backend tests reload persisted
configuration independently. These are not equivalent to native Windows/WebView2
focus or a packaged EXE restart. Those remain pending an explicitly approved
Windows build/manual target-PC check. No supplied screenshot match, full WCAG
certification or native validation is claimed.

## Executed validation — 2026-10-21

The final complete run passed against unchanged source. Backend: 114 tests in
21.020 seconds, no skips; browser: 37 tests in 9.1 minutes, one worker and no
retries. This includes six new backend tests and seven new browser tests. An
earlier complete run found one obsolete enterprise-test text expectation; it
was replaced with stronger assertions for role, domain, SAP area and matched
rule in the structured result. The affected test and then the entire suite
were rerun successfully. No test was removed or disabled.

Commands executed from the repository root (Python commands used the prepared
`.venv`; audit tooling used its separate, existing audit environment):

```sh
git diff --check
python scripts/ci.py lint
python scripts/check-workflows.py
pwsh -NoProfile -File scripts/check-powershell.ps1
python scripts/write-windows-metadata.py
npm --prefix frontend ci
node scripts/sync-lucide-catalog.mjs --check
npm --prefix frontend run check:types
npm --prefix frontend run build
python -W error::DeprecationWarning -m unittest discover -s backend/tests -v
python -m pip check
python -m pip_audit --path .venv/lib/python3.12/site-packages --progress-spinner off
npm --prefix frontend audit --omit=dev
PLAYWRIGHT_EXECUTABLE_PATH=/usr/bin/chromium npm --prefix frontend run test:browser -- --reporter=line,github
```

All passed, including repository/privacy/link checks, configuration migration,
actual synthetic imports, package/ZIP verifier fixtures, workflow expression
linting and trigger/security contracts. PowerShell 7.6.7 parsing/static guards
and the existing timing/error-preservation checks ran on Linux with writable
XDG directories. The frozen implementation/test patch SHA-256 (documentation
excluded) is
`c99adb3248fe7577deb04306d6e811f41a367997a189a4551350eced2de16716`.

Python and production JavaScript audits found zero known vulnerabilities. The
full npm audit still reports seven existing development advisories (five high,
two moderate) in the Tailwind tooling chain; no dependency change belongs to
this UI task. Environmental read-only-home pip-cache and NO_COLOR/FORCE_COLOR
messages remain visible. No application deprecation was reported by the strict
backend run. The official artifact action's known upstream DEP0005 dependency
remains documented in DEPRECATIONS.md; no remote action ran in this task.

Twelve after-captures were produced with an owned temporary test server, then
the server was stopped. Visual inspection compared before/after module lists,
navigation and filter controls, and reviewed the aligned warning, classification
overview and narrow result in light/dark mode. No horizontal overflow or
overlapping result text was observed. Before editor captures show the lazy icon
catalog loading; after captures wait for it, so they are not identical catalog
loading-state comparisons. Screenshots are review evidence, not pixel-baseline
certification. Native Windows/WebView2 and packaged EXE validation remain pending.

Additional invariant checks compared the production Classifier AST and module
IDs/names/icons/categories/parents/aliases with the baseline: identical. CSV and
configuration/migration code, dependency manifests/lockfiles, workflows, Windows
build/smoke/package-verification scripts, README and canonical assets are
byte-for-byte unchanged by this UI task. No push, dispatch or release occurred.
