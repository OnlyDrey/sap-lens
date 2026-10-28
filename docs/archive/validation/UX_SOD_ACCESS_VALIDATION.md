# UX, SoD, access management and scheduling validation (2026-10-28)

Eight phases delivered on `work` with Fast Validation per phase and one Full Validation at the end.
Facts below are from commands run in a Linux container; native Windows is not covered.

## Phases and commits

| Phase | Scope | Commit |
| --- | --- | --- |
| 1 | Navigation links, SAP user deep links, keyboard order, list rows, module icons in SoD | `c70e358` |
| 2 | Shared SoD Filters sidebar, option-backed filters, status tiles, scoped drawer | `b346503` |
| 3 | Dashboard-style SoD Overview, user group heatmap, Dashboard SoD summary | `57c2f45` |
| 4 | Add to cart and access package, users lacking roles, role entry layouts | `9750804` |
| 5 | Position change detection and priority review | `4532b46` |
| 6 | Scheduled refresh and Runtime & Scheduling | `d45a544` |
| 7 | Feature layout, module cleanup, source health, SoD hex colors, Secondary Color | `2e6f422` |
| 8 | Full Validation and fixes found by visual QA | final commit |

Fast Validation (backend repository tests, pip check, types) succeeded in CI for phases 1 to 7 after their pushes.

## Full Validation

- Backend: 716 tests passed (3 skipped), deprecations as errors.
- Browser: 462 tests in 48 spec files passed, run as three deterministic batches by sorted file name (160, 157, 145). A run that hit the background time limit was never counted; the batches replaced it.
- `npm ci`, `npm run check:types`, `npm run build`, `python -m pip check`, `pip-audit` (no known vulnerabilities), `npm audit --omit=dev` (0), `python scripts/check-docs.py`, `python scripts/check-workflows.py`, `node scripts/sync-lucide-catalog.mjs --check`, `git diff --check`: all passed.
- Visual QA: 80 captures (light and dark at 375, 800, 1280 and 1600 px) of the Dashboard, SoD Overview and Risk Matrix, Role Lookup, access package panel, Account Review queue and the Runtime, Appearance, Features and Health settings; none had horizontal page overflow. Review found three layout defects (SoD Overview sections, swatch tile styling, status tile tone), which were fixed and retested.

## Not validated here

Native Windows Desktop and WebView2 (tray, save dialogs, scheduled refresh while the tray hosts the app), Windows Service and SCM, installer, UNC paths, Docker image build and run, native Linux package install and systemd recovery. Deployment packages are produced only by the manually dispatched build workflows, which were not dispatched; no package artifacts were verified.
