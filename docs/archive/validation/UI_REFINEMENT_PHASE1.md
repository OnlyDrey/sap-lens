# UI refinement: implementation and validation

> Historical evidence: applies to the source/phase recorded below, not later
> commits. Use the [current documentation index](../../README.md) for instructions.

## Baseline and boundaries

Work started on clean `work` at `0e70f2f9bcb2e00d8c520af774c840171ff220fb`.
The existing React/TypeScript, Lucide, token, routing, import and persistence
architecture remains canonical. No dependency or stored configuration schema changed.
The protected README block and desktop packaging are unchanged.

The change is predominantly presentation. Two additive API responses supply evidence
needed by the UI: bounded user-import sample rows (20, excluding email/name), and
bounded directory matching candidates (25) with source and matching explanations.
Neither response alters the live dataset, matching algorithm or persisted diagnostic
report. Snapshot record identifiers are not physical CSV line numbers.

## Acceptance mapping

| # | Requirement | Implementation / evidence |
|---|---|---|
| 1 | Consolidate the reported issues | Shared patterns below; platform limitations explicitly retained |
| 2 | Consistent three-source import layouts | `SourceFileField`, existing numbered `ImportSection`; Employee Directory retains its documented fixed schema |
| 3 | Human-readable mapping and technical keys | `MappingField`: label, SAP key, required marker and mapping state |
| 4 | Readable, bounded preview | `ImportPreview`: metrics, warning disclosure, internally scrolling table, expandable full values; directory retains its paginated preview |
| 5 | Source modes/status | Common source tabs/mode placement retained; `SourceHealthSummary` distinguishes saved path, loaded data, snapshot, validation and preview |
| 6 | Settings scrolling | Flexible workspace width and height, bounded scrolling, fixed action footer, no hidden offscreen field columns |
| 7 | Actionable Diagnostics | Compact semantic health cards and reusable source evidence; existing recovery actions and technical disclosures retained |
| 8 | Dashboard hierarchy/navigation | Overview, Access & risk review, Data & system health; source health secondary; actual coverage numerator/denominator |
| 9 | Consistent search | Shared `SearchInput` for role search, transactions and module search; icon padding owned centrally |
| 10 | Role Details | Back above identity, balanced Previous/position/Next, striped single-role list; existing relationships retained |
| 11 | Saved Filters dropdown | Shared searchable `Combobox`, human names rather than internal IDs; CRUD/schema storage unchanged |
| 12 | Account Review | Grouped account/findings/progress metrics, common filter/results wrappers, preserved review calculations |
| 13 | Compare users | Common filters/results/search; existing paired identity panels and interactive summary/evidence retained |
| 14 | Release filters | Existing classification/assignment groups retained; sort direction remains beside sort control; responsive layout |
| 15 | Matrix readability | Stronger cell counts, aligned headings, bounded table scrolling |
| 16 | Date filter layout | Shared anchored portal, no parent-grid expansion; nested calendar ownership; staged Apply/Clear/Cancel |
| 17 | Review actions | Shared wrapping action row for Save and Cancel |
| 18 | Matching explanations | Secondary disclosure with exact matching method, SAP/source identifiers, bounded candidate records, unknown-state explanation and Data Sources recovery |
| 19 | Component Library | Before About in stable Settings routes; real import/status/filter/date components with isolated demo state |
| 20 | Capitalization | Sentence-case button labels, no CSS auto-capitalization of evidence states |
| 21 | Desktop connection | Implementation traced; supported browser QA procedure below; native lifecycle not claimed |
| 22 | SAP/import safety | No authorization, date, matching, deduplication, classification, replacement or persistence semantics changed |
| 23 | Automated regression | Backend evidence/privacy tests; custom filter selection, nested dismissal, staged dates, import geometry and preview-state tests |
| 24 | Visual contracts | Actual screenshots plus geometry/overflow/focus assertions, not pixel-golden claims |
| 25 | Themes | Both themes, 375/800/1280 px |
| 26 | Existing behavior | Full browser/backend results recorded below; native Windows acceptance separately pending |

## Shared component ownership

- `Settings/ImportControls.tsx`: source field, mapping field, bounded preview.
- `Settings/SourceStatus.tsx`: loaded/preview/source/snapshot evidence.
- `Shared/InvestigationPatterns.tsx`: health cards, filter groups and results toolbar.
- `Shared/Popover.tsx`: anchored, nonmodal, viewport-bounded portal and nested ownership.
- `Shared/Combobox.tsx` and `NorwegianDateInput.tsx`: nested portals participate in
  outside/focus handling; Escape dismisses the inner control before its parent.
- `Shared/AssignmentDateFilters.tsx`: same date model and comparisons; draft changes
  (including Clear) commit only through Apply. Cancel/outside/Escape preserve applied values.
- Existing saved-filter persistence, review decisions, comparison calculations,
  localized calendar and source replacement logic remain authoritative.

## Evidence and timestamp rules

An import preview is not activation. A configured path does not prove loaded data.
A loaded durable snapshot does not prove that the original file is accessible.
Last import/dataset activation is not Global Refresh time. Diagnostics retains the
actual last successful refresh and source validation timestamps without inventing
per-source refresh times. Directory duplicates remain separate source evidence;
there is no silent override/deduplication.

Dashboard assignment totals include historical/technical records. Cards that open
the complete directory say so; they do not claim an unsupported exact filtered
assignment view. Release totals explicitly describe the default active view.
Role-derived T-code evidence still does not establish effective SAP authorization.

## Desktop connection investigation and browser QA

`backend/desktop.py:reserve_listener` binds IPv4 `127.0.0.1`, first trying 18743,
then an OS-assigned port if occupied. WebView2 uses ordinary local HTTP after a
readiness/instance check, with a per-launch capability passed by the launcher.
A guessed `localhost:18743` URL is neither an authoritative instance address nor
a supported way to acquire that capability. Host/origin/session checks are intentional.
Do not publish the capability or copy private runtime metadata into reports.

For browser visual QA, use the supported headless runtime with separate storage,
not a weakened desktop listener. After installing the documented runtime requirements
and building the frontend, run from the repository root (Linux example):

```bash
mkdir -p /tmp/sap-lens-ui-qa
SAP_LENS_DATA_DIR=/tmp/sap-lens-ui-qa \
SAP_LENS_SOURCE_DIR=/tmp/sap-lens-ui-qa/sources \
SAP_LENS_HOST=127.0.0.1 SAP_LENS_PORT=18746 \
SAP_LENS_PUBLIC_ORIGIN=http://127.0.0.1:18746 \
SAP_LENS_AUTH=local .venv/bin/python backend/server.py
```

Open `http://127.0.0.1:18746/`. This uses independent storage; it does not inspect
or mutate desktop data. For normal deployments see [Deployment](../../deployment/README.md).
The existing Retry connection refetches application data and does not reset saved
configuration. Synthetic browser and backend lifecycle tests cover recovery paths;
actual Windows startup/shutdown, native dialogs and UNC remain manual acceptance.

## Validation record

Execution results and limitations are finalized after the single complete browser
pass. Local logs and synthetic screenshots are retained outside Git under
`/workspace/sap-lens-dev/ui-refinement/`.

No workflow modifications belong to this phase. Phase 2 is gated on these results.

### Final executed results

- `npm --cache /workspace/.npm-cache --prefix frontend ci --no-audit --no-fund`: passed; lockfile unchanged.
- `npm --prefix frontend run check:types`: passed.
- `npm --prefix frontend run build`: passed (existing large-chunk advisory retained).
- Prepared Python 3.12, portable PowerShell on PATH:
  `python -W error::DeprecationWarning -m unittest discover -s backend/tests -v`:
  **346 passed, zero skipped**, 20.814 seconds.
- `python -m pip check`: passed.
- `pip_audit -r backend/requirements-dev.txt -r backend/requirements-build.txt --vulnerability-service pypi --progress-spinner off`:
  no known vulnerabilities in Linux-resolved dependencies; native Windows-only resolution remains pending.
- `npm --prefix frontend audit --omit=dev`: zero production advisories.
  Full npm audit retains three existing moderate development-chain advisories:
  postcss-nested, postcss-selector-parser and tailwindcss. No suppressions/upgrades.
- Portable `scripts/check-powershell.ps1`, actionlint, Lucide catalog verification,
  changed-document links and `git diff --check`: passed.
- Final frozen `npm --prefix frontend run test:browser` using the isolated synthetic
  test server and `/usr/bin/chromium`: **233 passed, 6.7 minutes**.

The earlier broad run had 214 passes / 17 failures (7.9 minutes): obsolete prose,
CSS-selector and disclosure expectations plus a missing breadcrumb landmark.
Assertions were updated to verify exact metric values and their labels, actual
custom controls and expanded source disclosures. The breadcrumb was restored;
visual review additionally corrected squeezed investigation-table columns.
Targeted stabilization verified these changes before the final frozen pass.
No test removal, relaxed matching, worker increase or warning suppression.

Actual captures reviewed include source forms, module search, comparison,
saved-filter popup, account review, matching conflicts, diagnostics and the
floating calendar. Light/dark screenshots cover 375, 800 and 1280 px; existing
wide-window checks include 1920 px. Reusable geometry/overflow/focus contracts
complement visual inspection; these are Chromium checks, not cross-browser pixel
goldens. Captures/logs are outside Git. No production employee records were used.

Native Windows/WebView2, packaged EXE/PE execution, native dialogs, real UNC,
Firefox and Safari remain untested. No Windows build or remote workflow was run.
