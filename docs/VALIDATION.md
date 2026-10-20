# Windows Desktop 1.0 validation record

Local checks ran in the Linux cloud workspace on 2026-10-20 with all prior uncommitted work preserved. A verified pre-change archive and Git bundle are outside the checkout in `/workspace/sap-lens-backups/windows-desktop-1.0-before`.

| Check | Local result / scope |
| --- | --- |
| Backend/API/desktop lifecycle regression suite | 21 tests passed; actual embedded HTTP server with mocked native boundaries |
| Production frontend build | Passed TypeScript and Vite build |
| Production-browser integration | Passed Chromium/Playwright: initial configuration, picker bridge contract, invalid-file feedback, current file, persistence/reload, refresh, session/origin rejection and no external requests |
| Repeatability | Frozen frontend reinstall/build and reusable setup script verified |
| Dependencies | pip check passed; production npm audit zero; full npm audit seven Tailwind development-chain advisories; Python audit zero across 22 Linux-resolved desktop packages |
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

The workflow is configured to build/test the pushed development branch `work`. A successful push triggers it; consult its actual run result before treating the EXE as validated. Local YAML checks or Git push success are not Windows-build success. The workflow checks native GUI EXE metadata/resources, a PATH without development tools, managed-instance readiness, API protection, duplicate launch, repeated close/reopen and an unrelated occupied preferred port. It audits installed Windows dependencies before packaging.

The actual Windows runner result and artifact link must be reported separately after observing the run. While GitHub API access is blocked, build status is unverified. No claim is made here that a Windows build has passed.

Remaining manual acceptance: actual native file picker and cancel, Win32 focus/taskbar icon behavior, a clean Windows PC without build tools, absent WebView2, permitted UNC shares/non-ASCII paths, slow-share shutdown, upgrades preserving settings, and organizational signing/SmartScreen policies. See [DESKTOP.md](DESKTOP.md).
