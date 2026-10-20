# Repository cleanup audit — 2026-10-20

## Initial state and preservation

Branch `work`, clean tree, no uncommitted/unpushed work. Initial HEAD and fetched remote: `735cc30172bf4a568668929ce84c2a7ed6ab6d98`. A Git bundle was saved outside the checkout before changes. Ignored virtual environments, installed packages, generated output and local user data are preserved, not deleted as cleanup.

Executed baseline: 59 backend/API/CSV/classification/configuration/desktop tests, frozen frontend install, production build (333.72 kB JavaScript / 98.92 kB gzip), and 11 Chromium integration tests passed. Native GUI boundaries are mocked on Linux. Two workflows exist: lightweight automatic validation and manual-only Windows packaging. No release workflow exists or is needed.

## Reference-backed inventory

| Path / group | Purpose / evidence | Decision | Reason / risk |
| --- | --- | --- | --- |
| `backend/desktop.py`, instance/runtime/startup modules | PyInstaller entry, ownership/mutex/WebView2 tests | KEEP | Single supported production startup; security critical |
| `backend/main.py`, routers, cache, import, classification, models | Desktop app factory, developer Uvicorn and tests | KEEP | Active SAP analysis; semantics unchanged |
| Config/migration, branding, portable settings, theme, diagnostics | Settings client, native bridge and tests | KEEP | Persisted users and old schemas must remain supported |
| `backend/database.py` | Self-described unused placeholder, no imports | REMOVE | No SQL implementation to preserve; history retains placeholder |
| Cache summary/time accessor wrappers | Definitions only, no callers | REMOVE | Active readers use snapshots; retain used detail/module accessors |
| `RoleList/ModuleFilter.tsx` | Export has no caller; actual filters live in RoleList | REMOVE | Abandoned alternative, not the active module filter |
| Frontend old settings API helpers | No callers; complete configuration client owns UI | REMOVE | Backend endpoints retained for tests/native-smoke compatibility |
| Identity-only role-name helper | Returns its argument unchanged | CONSOLIDATE | Inline without altering role names |
| Unused Python imports | AST load-name check plus reference search | REMOVE | No runtime behavior change |
| `frontend/.env.example` | Unused VITE_API_URL at old port 8000 | REMOVE | Client uses same-origin requests, Vite has a maintained proxy |
| `backend/.env.example` | BootstrapSettings consumes listed settings | KEEP | Optional bootstrap/config-dir overrides still work |
| `build.bat` | Thin forwarder; Actions calls PowerShell directly | REMOVE | Document direct canonical build command |
| `run.bat` | Chooses old built EXE or pythonw source mode | REMOVE | Replace ambiguous selection with explicit documented entry point |
| `scripts/build-windows.ps1` | Used by Windows workflow and local developers | MODERNIZE | One canonical install/test/package implementation |
| Windows smoke, metadata, package verifier and browser-server scripts | Workflow/Playwright references | KEEP | Native validation and fixture server are active tooling |
| Python requirement layers | Runtime/native/test/build consumers | MODERNIZE | PyInstaller belongs in build-only requirements |
| Four unused Radix primitives and class-variance-authority | No imports; only Radix ScrollArea is used | REMOVE | Update manifest/lockfile together |
| React, Query, Lucide, clsx, tailwind-merge, ScrollArea | Direct runtime imports | KEEP | Active application behavior |
| Vite, TypeScript, Tailwind/PostCSS, concurrently, Playwright | Build/dev/test configuration | KEEP / REVIEW | Retain supported majors; report unresolved dev-only advisories |
| Legacy Tailwind color aliases | No utility references; semantic tokens replaced them | REMOVE | No active style depends on aliases |
| `assets/sap-lens.png`, `.ico` | README, canonical product artwork, native packaging | KEEP | Protected canonical assets |
| `frontend/public` header/favicon PNGs | Active URLs; 256px/64px derivatives, different hashes | KEEP | Sized deployment assets, not duplicate full-size artwork |
| `.github/workflows` | Automatic validation / manual packaging | MODERNIZE | Maintained Node-24 action runtimes, immutable SHAs, read-only permissions |
| Git/TS/Vite/PostCSS/Playwright configuration | Active tools and privacy guards | KEEP / MODERNIZE | Ignore compiler/diagnostic exports; keep real source fixtures |
| README and specialized docs | Linked API/config/import/classification references | MODERNIZE | Reuse hierarchy; replace obsolete launcher instructions |
| Backend compatibility endpoints and migrations | Existing tests, consumers and old user settings | KEEP | New UI does not make compatibility obsolete |
| Historical organization assets | Reachable historical blobs; earlier privacy audit | REVIEW | Current tree removal does not erase past exposure; no rewrite |

This inventory covers tracked and hidden configuration and inspected ignored build/cache directories. No tracked virtual environment, node_modules, EXE, distribution directory, log or private runtime settings was found. No abandoned PWA/service-worker launcher exists in the current tree. The product derivatives are intentionally retained; their dimensions and hashes differ from the protected 1254px canonical PNG.

## Final validation and remaining debt

Local final checks passed: 65 backend/API/repository-integrity tests, 11 production Chromium tests, frozen frontend install, type check, production build, pip check, actionlint, relative documentation links, asset references, requirements includes and protected README prefix comparison. Production JavaScript is 333.69 kB / 98.90 kB gzip: essentially unchanged; unused packages were already excluded from the runtime bundle. Removed 24 lockfile package entries; no retained dependency versions changed.

Removed direct packages: `@radix-ui/react-checkbox`, `@radix-ui/react-dialog`, `@radix-ui/react-separator`, `@radix-ui/react-tabs`, `class-variance-authority`. PyInstaller 6.22.3 moved to build-only requirements; runtime/library pins are retained. A non-forced compatible audit fix found no safe automatic solution to the remaining Tailwind 3 chain.

Audits: production JavaScript zero known advisories; Python runtime/native/build/test union 27 Linux-resolved packages, zero known advisories. Full npm audit retains seven development-only affected packages (five high, two moderate), covering glob/pattern and PostCSS selector parsing used during builds. These are not shipped application dependencies or demonstrated remote SAP Lens vulnerabilities. Do not compile untrusted source/CSS. A reviewed Tailwind 4 migration is intentionally outside cleanup scope.

Privacy: 205 reachable text blobs were checked for obvious GitHub/AWS token and private-key signatures, with zero candidates; this is not complete secret detection. No current tracked settings, exports, executables or private runtime artifacts were found. Two unique historical nonproduct image blobs remain reachable. Historical naming-convention assumptions also remain in old code. See PRIVACY.md: owners must assess disclosure/removal separately; no Git history rewrite was performed. Audit details remain outside the checkout; sensitive values are not reproduced here.

Intentionally retained debt: Python transitive dependencies are not fully hash-locked; the currently working httpx TestClient dependency has a framework deprecation warning and needs a separate compatibility migration. Tailwind development advisories remain. The standard Vite preview utility is retained as developer tooling, not an end-user launcher. Capability checks, runtime ownership and configuration migrations are deliberately not refactored merely to reduce line count. Large active SettingsView/ComparisonView components are retained; splitting them warrants a dedicated change. No standalone frontend component-unit-test framework exists; the 11 production browser regressions exercise those interactions.

Automatic CI intentionally remains lightweight: the user's manual-build preference takes precedence over adding production builds to every commit. Full production/browser checks run locally and in the manual Windows workflow.

## GitHub verification

The code changes are delivered on `work` in logical commits. The updated automatic workflow and one manually dispatched Windows build will be checked after pushing. Windows packaging results and artifact integrity are reported separately; local YAML/source checks never establish native runtime success. Manual Explorer/GUI dialog/high-DPI, clean-PC and organizational signing checks remain required even after automated Windows smoke passes.
