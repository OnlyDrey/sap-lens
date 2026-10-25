# Investigation tools — implementation and validation

## Baseline and architecture

Baseline: clean `work` at `40b5f39f7227d2432b07bde52564444076d10366`, equal to fetched `origin/work`. No reset, rebase, discarded work, dependency changes or new primary navigation. README branding, role comparison implementation, SAP processing semantics, Windows distribution parameters and workflows are preserved.

Discovery and exact field/relationship limitations: [Access Insights feasibility](ACCESS_INSIGHTS_FEASIBILITY.md). User guidance: [User Comparison](USER_COMPARISON.md), [Data Health](DATA_HEALTH.md), [Saved Filters](SAVED_FILTERS.md). Spec-only future work: [Authorization Risk Analysis](AUTHORIZATION_RISK_ANALYSIS_CONCEPT.md).

| Feature | Existing | Added | Improved | Deferred |
| --- | --- | --- | --- | --- |
| Access Insights | Dashboard + Account Review cover account findings | Evidence inventory and feasibility specification | Source coverage and lifecycle drilldowns in existing settings | Dedicated Insights module; unvalidated high-count risk flags |
| User Comparison | Existing user/role/T-code relationships | Two-user interval-aware role and transaction evidence, selectors, filters, history, pagination, local CSV | Reuses existing identity and catalogue matching rules | Effective authorization and usage analysis |
| Account Review | Decisions, reviewer/date/rationale, persistence, stale filter, license-group policy, export, user links | Outdated count/action; original reviewed evidence fingerprint in CSV | Shared saved investigations and clearer stale filter wording | Bulk approval; unvalidated mandatory reason taxonomy |
| Data Health | Import validation, source diagnostics, directory quality/matching | Shared source/coverage overview, severity and paginated record drilldown | Reuses directory report; snapshot/date-aware aggregate cache | Reconstructing rejected rows or absent independent release-policy references |
| Role Comparison | Two-to-five-role structural and T-code comparison | None | Preserved unchanged | No rebuild |
| Saved Filters | Page-local controls | Shared CRUD and atomic private persistence for five views | Compatibility warnings, explicit updates, optimistic conflict handling | Cloud synchronization; saving result datasets |
| Authorization Risk Analysis | Role-derived coverage evidence only | Future concept specification | Explicit evidence/SoD boundary | All runtime risk analysis, scores and navigation |

## Correctness and privacy decisions

- Comparison uses exact normalized assigned roles and distinct intervals; default currently-valid assignments. Account status remains separate. T-code evidence requires a confident catalogue match. Role rows and per-side interval evidence have independent bounded pagination.
- One comparison cache serves the current pair/publication/day/validity. Health aggregates cache one publication/day. Neither persists results. Application-scoped refresh invalidates browser queries.
- Saved filters contain only allowlisted bounded scalar/list controls, not datasets or selected comparison identities. Private `saved-filters.json` uses the existing per-user directory and atomic writer, optimistic modification checks, duplicate-name rules, size/count limits and existing origin/session protections. It is Git-ignored and outside canonical packaging inputs.
- Schema compatibility preserves unknown definitions; rename does not downgrade a future schema. Loading unsupported fields/options warns rather than crashing or silently rewriting stored data.
- Comparison CSV uses the existing spreadsheet formula neutralization and authenticated desktop save bridge, bounded UTF-8 bytes and source-generation/date checks across all pages. Browser tests exercise the bridge contract; they do not invoke the actual Windows save dialog.
- No risk scores, SAP writes, inferred usage/license savings, credentials, source data uploads or new dependencies.

## Validation

Available checks executed on Linux with Python 3.12.14, Node 24.19.0 and Chromium 154.0.8037.57:

| Command / check | Actual outcome |
| --- | --- |
| `npm --cache /workspace/.npm-cache --prefix frontend ci` | Passed; 143 packages installed from unchanged lockfile |
| `npm --prefix frontend run check:types` | Passed |
| `npm --prefix frontend run build` | Passed; production assets generated, Vite 1.28 seconds |
| `python -W error::DeprecationWarning -m unittest discover -s backend/tests -v` in prepared virtualenv | 301 passed, zero skips, 18.140 seconds; includes 20 added backend tests and existing synthetic Windows verifier/privacy tests |
| Full `npm --prefix frontend run test:browser` with prepared Python PATH and `/usr/bin/chromium` | 195 passed, zero retries, 5.7 minutes; all 175 pre-existing browser cases plus 20 new cases |
| Focused `npm --prefix frontend run test:browser -- investigation-tools.spec.ts` | 20 passed in 34.9 seconds; includes cancellation and alternate identity search regressions |
| `python -m pip check` | Passed; no broken requirements |
| `python -m pip_audit -r backend/requirements-dev.txt -r backend/requirements-build.txt --cache-dir /workspace/.pip-audit-cache` | No known vulnerabilities in Linux-resolved dependencies |
| `npm --cache /workspace/.npm-cache --prefix frontend audit --omit=dev` | Zero production vulnerabilities |
| Full npm audit | Three moderate development-chain entries; retained and disclosed |
| `python scripts/check-workflows.py` and actionlint | Passed; triggers, permissions, concurrency, graph, expressions and artifact contracts retained |
| Portable PowerShell `-NoProfile -File scripts/check-powershell.ps1` | Syntax/static checks passed; not native Windows execution |
| `node scripts/sync-lucide-catalog.mjs --check` | Passed; 1,447 existing identifiers retained |
| `git diff --check` | Passed |
| Local documentation target existence | Passed |

The prepared backend PATH includes the existing virtualenv and portable PowerShell; writable XDG cache/config/data paths are used for portable PowerShell. Browser commands set `PLAYWRIGHT_EXECUTABLE_PATH=/usr/bin/chromium`. No remote workflow dispatch or Windows build was run. The finished commit uses `[skip ci]` under the standing explicit instruction until further notice; GitHub Actions status is reported separately from local validation.

The first npm reinstall attempt used an unwritable home cache. Re-running with the workspace cache succeeded without changing any manifest or lockfile. An initial backend invocation without portable PowerShell skipped two platform-tooling checks; the final prepared run executes all 301 without skips. Initial focused browser failures identified exact-label selectors and an incorrectly scoped test assertion; fixes and fresh runs replaced those results.

Visual artifacts: the browser suite captures `comparison.png`, `data-health.png` and `data-health-findings.png` in light/dark themes at 375, 800 and 1280 pixels. Theme is set through persisted application configuration and asserted before capture. Comparison tables retain keyboard-scrollable bounded overflow; saved-select chevrons align with their inputs. Settings captures use the actual viewport and scroll to coverage, rather than recording hidden page whitespace. Twelve comparison/coverage screenshots were manually inspected across both themes and all three widths. Desktop identity columns, tablet wrapping, mobile table scrolling, input alignment, theme contrast and focus styling were reviewed. Eighteen new screenshots are retained under `/workspace/sap-lens-dev/investigation-tools-qa/`; screenshots remain outside Git.

## Platform limitations

Linux tests and Chromium screenshots do not establish native Windows/WebView2 behavior, actual UNC access, native save-dialog operation, packaged EXE startup or Windows-only dependency audit coverage. No EXE was built. Existing synthetic PE/archive/resource/package-integrity checks remain part of backend validation; these are distinct from inspecting a newly built executable. Large-export safety is regression-tested through bounded synthetic pagination; no production-scale timing claim is made.

Known dependency advisories remain visible: full npm audit reports three moderate development-chain entries (`postcss-selector-parser`, `postcss-nested`, `tailwindcss`); production npm audit is clean. No broad upgrades or suppressions were introduced. The Node test harness emits its existing NO_COLOR/FORCE_COLOR environment warning; this is not an application failure.

## Changed files

31 files changed. No dependencies, lockfiles, versioning, branding or workflow files changed.

- `.gitignore`
- `backend/main.py`
- `backend/routers/account_review.py`
- `backend/routers/data_health.py`
- `backend/routers/saved_filters.py`
- `backend/routers/user_comparison.py`
- `backend/saved_filters.py`
- `backend/tests/test_account_review.py`
- `backend/tests/test_investigation_tools.py`
- `backend/tests/test_repository_privacy.py`
- `docs/ACCESS_INSIGHTS_FEASIBILITY.md`
- `docs/ACCESS_INVESTIGATION.md`
- `docs/ACCOUNT_REVIEW.md`
- `docs/AUTHORIZATION_RISK_ANALYSIS_CONCEPT.md`
- `docs/CONFIGURATION.md`
- `docs/DATA_HEALTH.md`
- `docs/INVESTIGATION_TOOLS_VALIDATION.md`
- `docs/SAVED_FILTERS.md`
- `docs/USER_COMPARISON.md`
- `frontend/src/components/Access/AccountReview.tsx`
- `frontend/src/components/Access/ReleaseRoles.tsx`
- `frontend/src/components/Access/UserAccess.tsx`
- `frontend/src/components/Access/UserComparison.tsx`
- `frontend/src/components/RoleList/RoleList.tsx`
- `frontend/src/components/Settings/DataHealth.tsx`
- `frontend/src/components/Settings/SettingsView.tsx`
- `frontend/src/components/Shared/Combobox.tsx`
- `frontend/src/components/Shared/SavedFilters.tsx`
- `frontend/src/hooks/useViewHistory.tsx`
- `frontend/src/index.css`
- `frontend/tests/investigation-tools.spec.ts`
