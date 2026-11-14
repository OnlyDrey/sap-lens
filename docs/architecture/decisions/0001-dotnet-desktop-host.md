# ADR 0001: Native .NET Desktop host with WebView2

**Status: Proposed – pending approval.** Not approved. Nothing is implemented. Date of analysis: 2026-11-14, repository at `dc52746`.

## Problem statement

The Windows Desktop application is a single Python process that hosts the backend in a thread and its window through pywebview, packaged as a
PyInstaller one-file EXE. Window, tray, single instance, dialogs, packaging and diagnostics are all expressed through Python and `ctypes`.
Recurrent Windows issues (file locking, one-file extraction, diagnostics that depend on a frozen process) are concentrated in that layer. The question
is whether a native host improves maintainability, lifecycle management and Windows integration without weakening any security boundary.

## Existing architecture

See [current architecture](../DESKTOP_HOST_CURRENT.md): in-process backend, 19-method JS bridge, capability token, loopback boundary in Python,
one-file EXE, Inno Setup installer with isolated acceptance, separate Server distribution.

## Options evaluated

1. **Keep Python/pywebview** and improve it (status quo plus fixes).
2. **WinForms (minimal shell) + WebView2, backend as a child process** (recommended for Phase 2 to prove).
3. WPF + WebView2 (rejected: more weight and WebView2 airspace limits for no UI gain).
4. Rewrite backend pieces in C# (rejected: no compelling reason; business logic stays Python).
5. Electron or Tauri (not evaluated in depth: adds a second runtime and a larger redesign than the stated goal).

## Recommended direction

Prototype option 2 in isolation (roadmap Phase 2) and decide at the Phase 2 gate. Host: WinForms shell with logic in a class library, current .NET LTS,
self-contained. Backend: unchanged FastAPI app behind a new headless entry, PyInstaller onedir. Frontend: unchanged through a
`window.pywebview.api` compatibility shim. Validators stay in Python.

## Alternatives rejected or deferred

- WPF: rejected. Framework-dependent host and single-file host: deferred (see proposal section 6). Nuitka and an embedded Python runtime: deferred.
- Replacing the validators with C# copies: deferred pending Q3; the recommended design avoids duplicating them.
- Making the host the default: deferred to Phase 6.

## Tradeoffs

Gains: deterministic process ownership (Job Object), a real native shell (tray, dialogs, DPI, activation), host-side diagnostics independent of the
frozen Python process, an onedir backend that avoids per-launch extraction, and a testable C# library.
Costs: two executables and a per-file manifest, a process and secret boundary that does not exist today, a new dependency (WebView2 SDK) and runtime
servicing, extraction work in `desktop.py`, and two Desktop variants to maintain during migration. It does **not** by itself fix the installer failure,
signing, SmartScreen, AppLocker or WDAC.

## Assumptions (unverified)

- The current .NET LTS and its support window suit the project; the SDK is not installed here and support dates were not checked online.
- WinForms projects build for Windows from Linux with Windows targeting enabled.
- The exact WebView2 in-private profile API exists in the pinned SDK version.
- Inno Setup exit code 1 means "Setup failed to initialize" for the pinned version.
- Onedir reduces AppLocker/antivirus friction compared with one-file.

## Open questions

1. **Q1** Target framework and support baseline (approve .NET LTS version and minimum Windows build).
2. **Q2** Self-contained versus framework-dependent host (recommended self-contained).
3. **Q3** Validators: Python validate endpoint (recommended) or C# re-implementation.
4. **Q4** Signing: is a code-signing certificate available for the host, the backend and the installer, and what do the target enterprises enforce?
5. **Q5** Is a new NuGet dependency acceptable under the dependency policy, and how is it audited and pinned (offline restore)?
6. **Q6** Desktop backend shutdown protocol: stdin close only, or also an authenticated shutdown call.
7. **Q7** Cause of the `first isolated installation` failure: needs `setup.log` and WebView2 state from the retained Windows workspace before Phase 5.
8. **Q8** Should the shim keep the `pywebview` name, and for how long?

## Consequences if approved

Phase 2 begins as an isolated prototype; no production packaging, CI or product version changes. If rejected or if the Phase 2 gate fails, the new
directory and the extracted startup function are removed and the Python Desktop remains the product.
