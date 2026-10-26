# Frozen implementation — stabilization and delivery validation

> Historical evidence: applies to the source/phase recorded below, not later
> commits. Use the [current documentation index](../../README.md) for instructions.

## Scope and baseline

Branch: `work`. Remote baseline: `4918bcc3657a463c8df7b593066479fe06574e54`.

- UI/component consolidation: `246ef426a4a54f2b5d3dfbe1b4bc049fe1026ddc`.
- Frozen implementation checkpoint: `a1f3724` (`validation pending` in its commit title).
- Stabilization introduced no new features, dependencies, architectural changes or cosmetic refinements. The only implementation correction removed directory-only writes to the SAP assignment revision timestamp. Atomic directory binding remains intact. The existing browser test now checks revision preservation after both import and clear.

The delivery combines shared UI/navigation/tokens, compact Saved Filters, Component Library, User Comparison presentation, CSV source modes/durable generations, private refresh evidence, Employee Directory import/quality/dependencies and consolidated Diagnostics. See [component inventory](../../architecture/COMPONENTS.md), [navigation](../../architecture/NAVIGATION.md), [CSV lifecycle](../../data/IMPORT_AND_REFRESH.md) and [User Comparison](../../features/COMPARE_USERS.md).

## Validation results

Environment: Linux, Python 3.12.14, Node 24.19.0, system Chromium 154. Synthetic data only.

| Check | Executed result |
|---|---|
| Four previously failing/new browser cases | 4 passed, 7.1 seconds |
| One complete browser suite | 217 passed, 1 failed, 6.2 minutes |
| Corrected directory import/clear case | 1 passed, 3.6 seconds; original assertions retained and clear-revision assertion added |
| Existing complete backend suite | 325 passed, 17.230 seconds, before the isolated directory timestamp correction |
| Affected Employee Directory backend suite after correction | 28 passed, 1.349 seconds |
| Affected CSV lifecycle backend suite after correction | 22 passed, 0.785 seconds |
| TypeScript | Passed on the frozen frontend |
| Production frontend build | Passed; Vite 1.35 seconds on the frozen frontend |
| Focused visual capture/contracts after correction | 12 passed, 27.2 seconds |
| pip check | No broken requirements |
| Python audit | No known vulnerabilities in Linux-resolved dev/build/runtime inputs |
| JavaScript production audit | Zero vulnerabilities |
| Workflow checker/actionlint, portable PowerShell parsing/static guards, Lucide catalog | Passed; these inputs were unchanged during stabilization |
| Git diff whitespace/integrity review | Passed |

The comprehensive browser run is **not** represented as an uninterrupted 218/218 pass. Its single failure exposed directory-only publication advancing `data_revision` even though SAP assignments were unchanged. The four-line timestamp removal fixed that contract while keeping directory generations atomic. The affected browser case and both relevant backend suites then passed. No second complete browser suite was run, following the explicit stabilization instruction. No known test failure remains unresolved.

The four initial targeted cases covered source-availability wording, refresh-notification reuse, Saved Filters Escape/focus behavior and authenticated native change-export routing. All passed without further corrections during stabilization.

## Commands and evidence

Browser commands used the prepared virtualenv on PATH and `PLAYWRIGHT_EXECUTABLE_PATH=/usr/bin/chromium`:

```sh
npm --prefix frontend run test:browser -- tests/live-filters-polish.spec.ts tests/loading-consolidation.spec.ts tests/investigation-tools.spec.ts tests/csv-lifecycle.spec.ts -g 'data status badges retain availability distinction|failed refresh retains data through navigation|comparison metrics filter results|change CSV export uses the authenticated native'
npm --prefix frontend run test:browser
npm --prefix frontend run test:browser -- tests/employee-directory.spec.ts -g 'directory import and clear preserve independent catalogue filters'
.venv/bin/python -W error::DeprecationWarning -m unittest discover -s backend/tests -p test_employee_directory.py -v
.venv/bin/python -W error::DeprecationWarning -m unittest discover -s backend/tests -p test_csv_lifecycle.py -v
npm --prefix frontend run test:browser -- tests/design-system.spec.ts tests/csv-lifecycle.spec.ts -g 'lifecycle visual|canonical component visual contracts' --output /workspace/sap-lens-dev/stabilization-visual
```

The preceding backend/type/build evidence remains applicable: subsequent source changes affected only the two directory publication handlers and their browser assertion. No frontend implementation, dependencies, workflow or packaging inputs changed after their passing checks.

Local logs are retained outside Git under `/workspace/sap-lens-dev/design-system-qa/`: `stabilization-targeted.log`, `stabilization-browser-full.log`, `stabilization-directory-revision.log`, `stabilization-employee-backend.log`, `stabilization-lifecycle-backend.log`, `stabilization-visual.log`, plus the preceding `lifecycle-backend-native.log`, `lifecycle-types-finalized.log` and `lifecycle-build-finalized.log`. Initial `npm ci` installed 143 packages with unchanged lockfiles; dependency installation was not repeated during frozen stabilization.

## Visual QA

Reviewed actual captures in light and dark at 375, 800 and 1280 pixels. Coverage includes navbar/secondary navigation, paired comparison panels, Saved Filters, Component Library, feature dependencies, directory preview, Diagnostics, success/unchanged/error banners and change/error dialogs. Checked input alignment, focus indicators, portal bounds, readable statuses, responsive wrapping and contained table scrolling. No cosmetic changes were made during stabilization.

The persistent capture set is `/workspace/sap-lens-dev/stabilization-visual/`, outside Git. The visual contracts are geometry/interaction checks and reviewed screenshots; they are not native Windows or cross-platform pixel goldens.

## Final diff review and boundaries

Reviewed the consolidated diff and the isolated correction. No files were deleted. Protected README branding, canonical assets, dependency manifests/lockfiles, workflow triggers, application versioning, Windows packaging parameters and signing configuration are unchanged. Local snapshots, imported CSVs, logs and QA images are not committed. Existing SAP account/assignment semantics, matching rules, transaction evidence and saved-filter storage remain in place.

Source snapshots and private report files remain local. Diagnostic exports exclude personal records and source paths. Native change export reuses authenticated, bounded, explicit CSV save dialogs; browser downloads remain disabled in desktop mode.

## Known limitations and manual Windows readiness

Ready for manual Windows testing. Native Windows/WebView2, actual save dialogs, real UNC access and a newly packaged EXE have **not** been tested. Linux lifecycle tests include fresh-process persistence and mocked native-bridge guards; these do not establish native desktop compatibility. No Windows packaging or remote workflow was started.

Manual checks should cover static snapshot restart with the original CSV unavailable, dynamic replacement and recovery on a UNC share, manager navigation, keyboard/popover behavior and native UTF-8 change-report saving/cancellation. Windows-only dependency resolution/auditing was not executed on a Windows interpreter.

Full npm audit retains three existing moderate development-chain advisories: `postcss-selector-parser`, `postcss-nested`, `tailwindcss`. Production JavaScript auditing is clean. No dependency versions were changed or advisories suppressed. The test runner's NO_COLOR/FORCE_COLOR environment warning and npm update notice are informational.

## Git delivery policy

The user explicitly approved delivery with native Windows validation pending. Push is to `origin/work` only, without force, merging into main, tag/release creation or workflow dispatch. The standing `[skip ci]` instruction remains applicable; remote CI is separate from the local results above. The final delivery message records the final commit and verified remote SHA.

## Reviewed changed-file inventory

- `.gitignore`
- `backend/cache.py`
- `backend/config.py`
- `backend/config_models.py`
- `backend/configuration_routes.py`
- `backend/csv_import.py`
- `backend/csv_lifecycle.py`
- `backend/data_loader.py`
- `backend/desktop.py`
- `backend/diagnostics.py`
- `backend/employee_directory.py`
- `backend/employee_preview.py`
- `backend/main.py`
- `backend/portable_config.py`
- `backend/routers/account_review.py`
- `backend/routers/dashboard.py`
- `backend/routers/data_health.py`
- `backend/routers/data_sources.py`
- `backend/routers/employees.py`
- `backend/routers/saved_filters.py`
- `backend/routers/user_comparison.py`
- `backend/tests/test_application.py`
- `backend/tests/test_csv_lifecycle.py`
- `backend/tests/test_csv_profiles.py`
- `backend/tests/test_desktop.py`
- `backend/tests/test_employee_directory.py`
- `backend/tests/test_investigation_tools.py`
- `backend/tests/test_loading_publication.py`
- `backend/tests/test_repository_privacy.py`
- `backend/tests/test_user_access.py`
- `backend/user_access.py`
- `docs/architecture/SYSTEM.md`
- `docs/architecture/COMPONENTS.md`
- `docs/getting-started/CONFIGURATION.md`
- `docs/data/IMPORT_AND_REFRESH.md`
- `docs/data/DATA_HEALTH.md`
- `docs/architecture/DESIGN_SYSTEM.md`
- `docs/architecture/NAVIGATION.md`
- `docs/archive/validation/STABILIZATION_VALIDATION.md`
- `docs/archive/validation/UI_CONSOLIDATION_VALIDATION.md`
- `docs/features/COMPARE_USERS.md`
- `frontend/src/App.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/api/configuration.ts`
- `frontend/src/components/Access/AccountReview.tsx`
- `frontend/src/components/Access/ReleaseRoles.tsx`
- `frontend/src/components/Access/Shared.tsx`
- `frontend/src/components/Access/UserAccess.tsx`
- `frontend/src/components/Access/UserComparison.tsx`
- `frontend/src/components/Dashboard.tsx`
- `frontend/src/components/Layout/AppLayout.tsx`
- `frontend/src/components/RoleList/RoleList.tsx`
- `frontend/src/components/Settings/ComponentLibrary.tsx`
- `frontend/src/components/Settings/DataHealth.tsx`
- `frontend/src/components/Settings/Diagnostics.tsx`
- `frontend/src/components/Settings/DirectoryPreview.tsx`
- `frontend/src/components/Settings/EmployeeDirectory.tsx`
- `frontend/src/components/Settings/ImportPresets.tsx`
- `frontend/src/components/Settings/ModuleEditor.tsx`
- `frontend/src/components/Settings/SettingsView.tsx`
- `frontend/src/components/Settings/SourceMode.tsx`
- `frontend/src/components/Settings/ThemeEditor.tsx`
- `frontend/src/components/Shared/AccountStatus.tsx`
- `frontend/src/components/Shared/AssignmentDateFilters.tsx`
- `frontend/src/components/Shared/Button.tsx`
- `frontend/src/components/Shared/ClearFilterButton.tsx`
- `frontend/src/components/Shared/Combobox.tsx`
- `frontend/src/components/Shared/Controls.tsx`
- `frontend/src/components/Shared/Dialog.tsx`
- `frontend/src/components/Shared/FilterChip.tsx`
- `frontend/src/components/Shared/InvestigationNavigation.tsx`
- `frontend/src/components/Shared/Navigation.tsx`
- `frontend/src/components/Shared/Notification.tsx`
- `frontend/src/components/Shared/Popover.tsx`
- `frontend/src/components/Shared/Presentation.tsx`
- `frontend/src/components/Shared/RefreshReport.tsx`
- `frontend/src/components/Shared/SAPUserSelector.tsx`
- `frontend/src/components/Shared/SavedFilters.tsx`
- `frontend/src/components/Shared/TransactionFilter.tsx`
- `frontend/src/hooks/useViewHistory.tsx`
- `frontend/src/index.css`
- `frontend/src/main.tsx`
- `frontend/src/state/ApplicationData.tsx`
- `frontend/src/styles/components.css`
- `frontend/src/styles/tokens.css`
- `frontend/src/vite-env.d.ts`
- `frontend/tailwind.config.ts`
- `frontend/tests/access-investigation.spec.ts`
- `frontend/tests/account-review-refinement.spec.ts`
- `frontend/tests/consolidated-role-ui.spec.ts`
- `frontend/tests/csv-lifecycle.spec.ts`
- `frontend/tests/data-aware-ux.spec.ts`
- `frontend/tests/design-system.spec.ts`
- `frontend/tests/desktop.spec.ts`
- `frontend/tests/employee-directory.spec.ts`
- `frontend/tests/enterprise.spec.ts`
- `frontend/tests/global-navigation.spec.ts`
- `frontend/tests/investigation-filter-refinement.spec.ts`
- `frontend/tests/investigation-tools.spec.ts`
- `frontend/tests/investigation-ux.spec.ts`
- `frontend/tests/live-filters-polish.spec.ts`
- `frontend/tests/navigation-modules.spec.ts`
- `frontend/tests/settings-refinement.spec.ts`
- `frontend/tests/user-role-export.spec.ts`
