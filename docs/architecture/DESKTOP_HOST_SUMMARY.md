# Desktop host migration: executive summary

Proposed, pending approval ([ADR 0001](decisions/0001-dotnet-desktop-host.md)). Phase 1 was analysis only.

1. **Is a C# host technically justified?** Plausibly, for lifecycle and Windows integration, but not proven. The strongest evidence is structural:
   today everything runs in one frozen Python process, so process ownership, shutdown and diagnostics all depend on it. It is justified enough to
   prototype in isolation (Phase 2), not to adopt.
2. **What improves:** deterministic backend ownership (Job Object), native dialogs, tray, DPI and activation, host diagnostics independent of Python,
   an onedir backend (no per-launch extraction), a unit-testable C# library.
3. **What becomes more complex:** two executables and a per-file manifest, a new secret and process boundary, a new dependency and runtime servicing,
   and two Desktop variants during migration.
4. **Python that stays unchanged:** FastAPI app, routers, stores, SQLite, CSV, reviews, SoD, backups, the loopback and token boundary, the Server.
5. **What must be migrated:** window, WebView2, native dialogs, tray and startup entry, single instance, startup/recovery screen, backend supervision.
   Python needs two extractions: the startup sequence out of `desktop.run()` and the native-call validators out of `desktop.py`.
6. **Linux builds:** backend, frontend and C# library tests stay possible; the host may build from Linux (unverified); PyInstaller, Inno Setup,
   signing and all acceptance need Windows.
7. **Windows testing still needed:** everything about the host itself, the onedir backend, the installer variant, upgrade and rollback, AppLocker/WDAC,
   and diagnosis of the existing installer failure.
8. **Recommended next step:** approve or amend the ADR open questions Q1 to Q8, capture `setup.log` and WebView2 state from the retained workspace,
   then start Phase 2 as an isolated prototype with the Python Desktop untouched.

Documents: [current architecture](DESKTOP_HOST_CURRENT.md), [proposal](DESKTOP_HOST_DOTNET_PROPOSAL.md), [roadmap and tests](DESKTOP_HOST_MIGRATION_ROADMAP.md),
[risk matrix](DESKTOP_HOST_RISK_MATRIX.md).
