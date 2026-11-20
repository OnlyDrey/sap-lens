# Desktop host migration roadmap and test strategy

Status: **plan, not approved.** Phase 1 (this analysis) is documentation only. Each phase ends at a stop/go gate. The Python Desktop build and the
Windows Server distribution stay shippable throughout; the .NET host is added beside them and becomes the default only at Phase 6.
Complexity: S (days), M (1 to 3 weeks), L (more). Windows-only checks are reported NOT EXECUTED until run on Windows.

## Phase 2: minimal host prototype (isolated)

- **Scope:** new project outside production packaging (`desktop-host/` with a library and a thin WinForms shell). Starts the existing backend through a
  new headless entry `backend/desktop_backend.py` (extracted from `desktop.run()`), opens the React UI in WebView2, health check, graceful stop.
  No dialogs, tray or installer. Python Desktop untouched.
- **Files:** new `desktop-host/**`, new `backend/desktop_backend.py` and a shared startup function; `desktop.py` calls the shared function, behaviour unchanged.
- **Depends on:** decisions Q1, Q2, Q5 (ADR). SDK and target framework verified.
- **Risks:** startup sequence extraction changes the Python path (H); capability handoff over stdin (M); the WebView2 profile API (L).
- **Tests:** Python: existing `test_desktop.py` unchanged and green; new tests for the shared startup function and the headless entry. C# unit tests for the
  supervisor with a fake process. Windows manual: start, health, close, kill host leaves no backend.
- **Acceptance:** UI loads from `127.0.0.1` in WebView2; wrong capability is refused; closing the host stops the backend; killing the host removes the
  backend (Job Object); no change to any existing test result.
- **Rollback:** delete the new directory and entry; the shared function is a pure refactor revertible by one commit.
- **Complexity:** M. **Gate:** prototype demonstrated on Windows plus unchanged Python Desktop smoke (4/4).

## Phase 3: native capability migration

- **Scope:** `window.pywebview.api` compatibility shim (19 methods), native dialogs, validation endpoint or C# validators (Q3), single instance with the same
  mutex, tray and startup entry, startup/recovery screen, WebView2 policy (navigation, downloads, new windows, DevTools), host log.
- **Files:** `desktop-host/**`, extracted `backend/native_policy.py` (validators moved out of `desktop.py`; `desktop.py` imports them, tests unchanged),
  optional authenticated validate route.
- **Depends on:** Phase 2 gate.
- **Risks:** validator drift between the old and new path (H), tray and session-end behaviour (M), accessibility of the startup screen (L).
- **Tests:** the existing native-call tests run unchanged against `native_policy`; the same fixtures drive a C# contract test; navigation and
  unauthorized-call tests; duplicate-launch and old/new mutual-exclusion native tests; the frontend specs run unchanged (they never see the host).
- **Acceptance:** every one of the 19 methods has a passing test in both stacks where applicable; unauthorized calls open no dialog; foreign origin
  navigation blocked; second launch activates the first window.
- **Rollback:** the shim and policy module are additive; disable the host project. **Complexity:** L. **Gate:** security checklist complete, reviewed.

## Phase 4: packaging integration (isolated variant)

- **Scope:** Desktop backend as PyInstaller onedir; self-contained host; folder layout and per-file manifest; isolated installer variant with its own
  output name and AppId acceptance; the Python one-file EXE and its installer remain.
- **Files:** `scripts/build_system/windows/*` (new target, existing ones unchanged), `deploy/windows/desktop-installer-dotnet.iss` (new), packaging verifiers (new
  checks, old unchanged), manifest schema extension.
- **Depends on:** Phase 3 gate.
- **Risks:** manifest/identity binding across two executables (H), installer payload change (H), build time and size (M), AV and policy on onedir (M).
- **Tests:** `test_windows_package`-style tests for the new manifest; layout tests runnable on Linux; Windows-only: build, verifier, smoke of the host.
- **Acceptance:** dist directory shows both Desktop variants side by side with separate artifact-bound manifests; the old variant verifies exactly as before.
- **Rollback:** remove the new target; nothing else references it. **Complexity:** L. **Gate:** both variants build and verify on Windows.

## Phase 5: native acceptance

- **Scope:** fresh and configured install, upgrade from the Python Desktop install to the host variant and back, backend lifecycle (crash, port collision,
  duplicate launch), shutdown and cleanup, AppLocker/WDAC behaviour on a policy-enforced VM, security boundaries, Server distribution unchanged.
- **Tests:** an isolated-AppId installer acceptance for the variant (same method as `test-desktop-installer.ps1`), smoke scenarios adapted to the host,
  upgrade and rollback scripts, evidence retention. The **existing installer failure must be diagnosed first** (current architecture, section 6).
- **Acceptance:** all checks pass on Windows with retained evidence; production data and registry untouched; no regression of Server acceptance.
- **Rollback:** reinstall the Python Desktop package (data is compatible because storage is unchanged). **Complexity:** L. **Gate:** acceptance receipt.

## Phase 6: controlled migration

- **Scope:** compare old and new (functional parity, startup time, memory, reliability), decide the default, ship both for one release if needed.
- **Acceptance:** parity checklist, measured startup and shutdown, no open High risk. **Rollback:** the Python Desktop package stays available until
  the decision is confirmed. **Complexity:** M. **Gate:** explicit approval.

## Test coverage matrix

| Existing area | Tests | Reusable unchanged | Needs adaptation | New |
|---|---|---|---|---|
| Backend API, auth, SQLite, SoD, exports | most of `backend/tests` | all | none | none |
| Frontend specs (including `startup-recovery`, `session-recovery`) | `frontend/tests` | all (shim keeps `window.pywebview.api`) | none | spec asserting the shim contract |
| Desktop startup, readiness, ports, retry | `test_desktop.py` (51), `test_windows_ports.py` | readiness, port and health tests apply to the backend entry | tests that construct `webview` mocks | headless-entry tests |
| Native dialogs and validators | `test_desktop.py` native tests | validators after extraction | calls through `NativeDialogs` | C# contract tests with the same fixtures |
| Single instance | `windows_test_instance.py`, smoke script | mutex name tests | window-activation test | host duplicate-launch native test |
| Tray and startup entry | `test_windows_tray.py` (19) | policy logic if kept in Python | reimplemented in C# | C# unit and native tests |
| Packaging, identity, checksums | `test_windows_package.py`, `test_local_build.py`, `test_desktop_installer.py` | Server and old Desktop paths | multi-file manifest | manifest, layout, per-file hash tests |
| Installer acceptance | `test-desktop-installer.ps1` | isolation and cleanup logic | payload and executable names | variant acceptance, upgrade and rollback |
| Server and Service Manager | `test_server*`, `test_windows_ports.py` | all | none | a check that the Server ZIP is byte-identical in content |
| WebView2 policy | none today | n/a | n/a | navigation, download, new-window, DevTools tests (closes a gap) |

Always required: backend readiness and process ownership, graceful and forced shutdown, crash recovery, port collision, duplicate launches, WebView2
initialization failure, navigation restrictions, unauthorized native operations, data persistence and migration safety, installer isolation and
cleanup, Desktop and Server artifact integrity.

Linux-compatible: backend, frontend, C# library tests, manifest and layout tests. Windows-only: host UI, Job Object, tray, mutex, registry, installer,
smoke, AppLocker/WDAC.
