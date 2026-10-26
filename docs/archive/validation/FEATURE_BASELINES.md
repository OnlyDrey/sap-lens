# Feature validation baselines

Historical synthetic validation, not certification of later commits. Current instructions live in [Features](../../features/README.md).

## Role Presentation

## Validation

Regression coverage is in `frontend/tests/consolidated-role-ui.spec.ts`, alongside
the existing access/export/browser tests. It covers header parsing and unchanged
backend classification, fallback text, collapsed/multiple/exact/custom-code search,
row highlighting, expansion restoration, role changes, missing evidence, All roles,
match-code presentation, export, shared toolbar layout and both themes at 800 and
1280 pixels. Existing lock tests now require a pill background while retaining
icon, label, alignment and unknown-state assertions.

From the repository root, with the prepared Python environment active:

```powershell
python -W error::DeprecationWarning -m unittest discover -s backend/tests -v
python -m pip check
python scripts/check-workflows.py
pwsh -NoProfile -File scripts/check-powershell.ps1
node scripts/sync-lucide-catalog.mjs --check
cd frontend
npm ci
npm run check:types
npm run build
npm run test:browser
npm audit --omit=dev
```

Run the project's Python dependency audit and actionlint as documented in the CI
architecture as well. Browser and mocked native-save tests are not native Windows
WebView2, UNC-path or packaged-EXE validation. This frontend task does not alter or
run the Windows packaging pipeline.

### Local results (2026-10-23)

- Backend suite with deprecations treated as errors: **214 passed**, no skips.
- Full browser suite: **95 passed**. The eight consolidated regression cases also
  passed separately after strengthening the active five-control toolbar check.
- npm clean installation, TypeScript checking and production frontend build: passed.
- pip consistency, workflow contracts, actionlint, PowerShell parser/static guards,
  Lucide catalogue verification and Git whitespace checks: passed.
- Python requirements audit and production npm audit: no known vulnerabilities.
  Full npm audit retains seven existing development-only tooling advisories
  (five high, two moderate); dependencies and lockfiles were not changed.
- Light/dark screenshots were inspected at 800/1280 pixels for the toolbar,
  catalogue match cells, metadata headers, search highlighting and lock pills.
- Native Windows/WebView2, UNC paths and a packaged executable were not tested.
  No Windows package, GitHub workflow, release or remote push was performed.

Changed files:

| Responsibility | Files |
|---|---|
| User views and toolbar | `frontend/src/components/Access/UserAccess.tsx` |
| Shared metadata | `frontend/src/components/Shared/RoleMetadata.tsx`, `frontend/src/components/Modules/ModuleRegistry.tsx` |
| Sidebar search and provenance | `frontend/src/components/RoleDetail/RoleDetailPanel.tsx` |
| Presentation tokens/layout | `frontend/src/index.css` |
| Browser regression coverage | `frontend/tests/consolidated-role-ui.spec.ts`, `frontend/tests/access-investigation.spec.ts`, `frontend/tests/user-role-export.spec.ts` |
| Documentation | `docs/features/ROLE_LOOKUP.md`, `docs/archive/implementation/ACCESS_INVESTIGATION.md` |

See [Live transaction filters and evidence presentation](../../features/FILTERS.md) for the
current shared chip interaction, Norwegian date display and active evidence summary.

## Employee Directory

## Local implementation validation (2026-10-23)

The Employee Directory implementation was completed on `work` before starting
subsequent role-filter refinements. The Linux baseline passed 236 backend tests
(with deprecations treated as errors), TypeScript checking and the production
build, followed by all 113 browser tests. Python runtime/development/desktop/build requirement audits found no known
vulnerabilities, and the JavaScript production audit found none. Seven unchanged
JavaScript development-tool advisories remain (five high, two moderate).

Workflow contracts, actionlint, PowerShell syntax/static guards, repository
integrity/privacy and the 1,447-entry Lucide catalog check passed. Synthetic
light/dark Features and Data Sources screenshots were reviewed at 800 and 1280
pixels. Native Windows packaging, WebView2, UNC access and the actual file picker
remain pending; no remote builds or workflow dispatches were performed.
