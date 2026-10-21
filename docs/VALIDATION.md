# Desktop validation records

## Repository maintenance validation

The cleanup baseline at `735cc30` passed 59 backend tests, 11 browser tests and the production frontend build. Cleanup passes 65 backend/integrity tests (including relative links, asset references and requirement layers), 11 browser tests, types/build, pip check and workflow lint. The production bundle remains approximately 334 kB / 99 kB gzip. See [cleanup audit](REPOSITORY_CLEANUP.md) for removals, dependency/feed scope, historical privacy and outstanding debt. Actual Windows tests/build, package-contents/checksum verification, GUI lifecycle smoke and artifact upload passed in [manual run 39469463871](https://github.com/OnlyDrey/sap-lens/actions/runs/39469463871) for implementation `70a696e`. Automatic EXE triggers remain disabled. Local cloud artifact re-download was blocked; the exact executable was verified on the Windows runner before upload.

## Desktop UX and theme colors 1.2

On 2026-10-20, the Linux workspace passed 59 backend/API/lifecycle tests, production frontend compilation, and 11 Chromium integration tests for full-window settings, themes and recovery. The current JavaScript bundle is approximately 333 kB / 99 kB gzip. Backend tests include real owned HTTP listeners with mocked native GUI boundaries. Light/dark screenshots cover 1280×720, 1366×768 and 1920×1080; visual review confirms stable sidebar/content scrolling and fully visible action bars, including after a header notification. A stricter viewport-bounds regression check passed after correcting that notification-height case. Tests use synthetic data and include wide-logo containment.

The 1.2 launcher subsequently passed actual automated Windows GUI/lifecycle validation in [cleanup run 39469463871](https://github.com/OnlyDrey/sap-lens/actions/runs/39469463871). This supersedes the original Linux-only limitation; manual target-PC interactions and policies remain unverified. EXE packaging remains manual-only, per user preference; automatic CI runs validation without building. See [workspace/theme behavior and test scope](UX_AND_THEMES.md) and the [Windows checklist](DESKTOP.md).

## Prior Windows Desktop 1.1 validation record


Local checks ran in the Linux cloud workspace on 2026-10-20 with all prior uncommitted work preserved. A verified pre-change archive and Git bundle are outside the checkout in `/workspace/sap-lens-backups/windows-desktop-1.0-before`.

| Check | Local result / scope |
| --- | --- |
| Backend/API/desktop lifecycle regression suite | 50 tests passed; actual embedded HTTP server with mocked native boundaries |
| Production frontend build | Passed TypeScript and Vite build |
| Production-browser integration | Four Chromium/Playwright tests cover initial configuration/security, organization/logo/theme portability, custom mappings and CSV area evidence and pagination/comparison |
| Repeatability | Frozen frontend reinstall/build and reusable setup script verified |
| Dependencies | pip check passed; production npm audit zero; full npm audit seven Tailwind development-chain advisories; Python audit zero across 24 Linux-resolved desktop packages |
| Repository hygiene | README branding/navigation preserved; original logo unchanged; no settings, exports, tokens or generated build outputs staged |
| Workflow lint | actionlint 1.7.7 passed (verified official release checksum) |
| Windows metadata | Metadata generated from backend/version.py; multi-resolution ICO converted from the existing logo |

The lifecycle tests cover first-run behavior, repeated launch/close, listener release, unrelated occupied-port fallback without contact, missing service readiness, GUI failure cleanup, duplicate-instance activation control flow, registry/mutex wrappers, missing runtime handling, stalled initial load shutdown, exact CORS/capability enforcement and native-picker selection/cancel/authorization. Windows boundaries are mocked here; this does **not** verify native WebView2 or Win32 behavior.

## Reproduce locally

Activate `.venv` and install `backend/requirements-dev.txt` and (for desktop imports) `backend/requirements-desktop.txt`.

```sh
python -m unittest discover -s backend/tests -v
python -m pip check
cd frontend
npm ci
npm run build
npx playwright install chromium
npm run test:browser
npm audit --omit=dev
```

In the prepared Linux cloud machine, the browser check uses `PLAYWRIGHT_EXECUTABLE_PATH=/usr/bin/chromium npm run test:browser` instead of downloading another browser. This override is a local test convenience only. Browser tests create isolated temporary user settings and use clearly labeled synthetic fixture data. Their static test capability is confined to `scripts/serve-browser-tests.py`; the real launcher always generates a random capability.

## Windows workflow and manual acceptance

The Windows packaging workflow is manual-only; choose the desired branch when dispatching it in Actions. Fast Validation on every push/PR runs backend/repository tests and frontend type checks. Full Validation runs comprehensive checks, including production assets and browser tests, only on PRs targeting main. Neither produces an EXE. See [CI architecture](CI_ARCHITECTURE.md). Consult the actual manual Windows run result before treating an EXE as validated. Local YAML checks or Git push success are not Windows-build success. The workflow checks native GUI EXE metadata/resources, a PATH without development tools, managed-instance readiness, API protection, duplicate launch, repeated close/reopen and an unrelated occupied preferred port. It audits installed Windows dependencies before packaging.

The enterprise implementation at `fc18a2e1c5bad27f889bfc8cfcfd458c8240b2b4` passed the actual Windows workflow on 2026-10-20: [run 39426241519](https://github.com/OnlyDrey/sap-lens/actions/runs/39426241519). Build/tests, installed Windows dependency audit, packaged EXE lifecycle smoke, checksum generation and downloadable artifact upload passed. This establishes automated Windows packaging/runtime smoke validation, not the manual target-PC acceptance below. Later documentation-only commits retain the same application code.

Remaining manual acceptance: actual native file picker and cancel, Win32 focus/taskbar icon behavior, a clean Windows PC without build tools, absent WebView2, permitted UNC shares/non-ASCII paths, slow-share shutdown, upgrades preserving settings, and organizational signing/SmartScreen policies. See [DESKTOP.md](DESKTOP.md).

## Enterprise configuration coverage

The backend suite adds schema-3 persistence/revision checks, migration backups, invalid/future-file recovery, failed-write retention, redacted/private portability, image decoding and missing-logo fallback, registry aliases/overrides, legacy-rule archival without execution, exact/wildcard assignment matching, release parsing and matrix counts, mapped encodings/delimiters, nine-field provenance, alternate descriptions and cancellation preventing stale publication. Browser tests use invented data and stub native bridge boundaries; they do not prove real Windows dialogs work.

Current-tree public assets are limited to SAP Lens defaults and theme initialization. The README branding/navigation prefix is byte-for-byte unchanged. A reachable-history review checked 90 unique text blobs for obvious credential/private-key literals and identified historical organization logo binaries. This is a bounded audit, not a guarantee of complete secret detection; see PRIVACY.md. A pre-change verified Git bundle remains outside the checkout.

GitHub Actions inspection became available after the initial network restriction; the enterprise Windows run link is above. SAP Help search became accessible over verified HTTPS: matching documentation titles support 42 area names (linked in MODULES.md). Remaining names and release-specific component hierarchy need further verification; unrelated search hits were rejected. Browser rendering encountered the cloud certificate boundary.
