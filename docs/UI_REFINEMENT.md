# UI refinement records

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

Limitations: detail Previous/Next is intentionally scoped to a result page;
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

> Historical implementation record. The later approved classification removal and two-source access architecture supersede the profile UI described here. See [current access investigation](ACCESS_INVESTIGATION.md).


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
plan in [the architectural assessment](CLASSIFICATION_ARCHITECTURE.md). SAP Modules
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
| `docs/CLASSIFICATION_ARCHITECTURE.md`, `docs/UI_REFINEMENT.md`, `docs/DESKTOP.md`, `docs/CI_ARCHITECTURE.md` | Review, migration boundaries, implementation record, navigation and coverage wording that remains accurate as tests are added |

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
