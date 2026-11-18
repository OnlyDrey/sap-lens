# Phase 1 decision: SAP Lens 2.0 on C# / ASP.NET Core

Date: 2026-11-15. Branch `experiment/dotnet-backend`, based on `origin/work` `d7a39fb`. Tags as in [README](README.md).

## Recommendation: CONDITIONAL GO

A C# / ASP.NET Core backend on SQLite is **technically viable** for SAP Lens and meets the corporate C# preference without weakening data
integrity, security or operations on the evidence gathered. It is **not yet a GO** because the decisive Windows evidence (Desktop and
Server actually running) does not exist, one requested Role Lookup capability (suffix handling) is not ported, memory use is higher than
v1, and the migration of the v1 audit trail is designed but not rehearsed. Proceed to a Phase 2 that closes exactly those gaps (below)
before committing to a product rewrite. This is an architecture decision, not authorization to rewrite.

## Decision criteria

| GO criterion | Status | Evidence |
| --- | --- | --- |
| Representative functionality without unacceptable complexity | **Met** | Import, catalogue, users, Role Lookup, User Access, Compare Users, SoD, reviews, jobs, backups, API, Desktop shell in about 3.5 k lines of C# and 47 tests [M][T] |
| Equivalence for all defined critical scenarios | **Met for the ported scope**; suffix handling not ported | 68/68 small, 68/68 large, byte-identical SoD identities over 281 k findings; negative control detects injected changes [M] |
| Reliable SQLite in Desktop and Server | **Met on Linux**, Windows unverified | WAL, BEGIN IMMEDIATE, multi-process writers and workers, fenced leases, triggers, hash chain, online backup, migration backup, newer-schema refusal [T]; 0 errors under load during a large import [M] |
| Viable Desktop packaging | **Launched on Windows 11, UI fix not yet verified there** | Windows 11 VM: build, 47/47 tests, publish, launch, WebView2 and loopback API worked; `GET /` was 404 (missing UI assets) [W]. Fixed: UI embedded, readiness-gated navigation, publish acceptance tests; Windows re-run pending [M][T][U] |
| Viable Windows and Linux Server | **Linux met**, Windows built only | Linux: startup, readiness, load, graceful and crash shutdown [M] |
| No mandatory Python runtime for the core | **Met** | Server and Desktop builds contain no Python [M] |
| Acceptable performance | **Met, with a memory caveat** | Per operation 1.4x to 4.6x faster; service throughput 8x, P50 31 ms vs 2.65 s; restart 5 s vs 9.8 s; memory 1.4x to 1.8x v1 [M] |
| Safe migration strategy | **Designed, not executed** | Import-based migration with verification gate and protected backups; retention and re-review rules implemented [C][T] |

## Update: production UI on .NET (Phase 1 of the full migration)

The production React UI from `origin/work` is now built into and served by the .NET host (Desktop and Server), with a v1 compatibility layer
for the boot sequence and Role Lookup and explicit 501 answers elsewhere; inventory and plan in [FEATURE_PARITY.md](FEATURE_PARITY.md), details
in [UI_INTEGRATION.md](../architecture/UI_INTEGRATION.md). Verified on Linux in Chromium; not yet on Windows.

## Measured performance (Linux, large synthetic set)

| | Python v1 | .NET |
| --- | ---: | ---: |
| Catalogue build (97 k rows) | 4.5 s | 1.0 s |
| SoD analysis (64,664 findings) | 8.9 s | 6.4 s |
| 15 users, steady: throughput / P50 / P95 | 5.2 rps / 2,650 ms / 5,524 ms | 42.8 rps / 31 ms / 1,411 ms |
| Same during a 101 k row import | 4.0 rps / 2,638 ms / 6,347 ms | 48.1 rps / 17 ms / 1,340 ms |
| Restart with data to first answer | 9.8 s | 5.0 s |
| Memory with data loaded (after restart) | 571 MB | 810 MB |

Details and the separation of language versus architecture effects: [PERFORMANCE_BENCHMARK.md](PERFORMANCE_BENCHMARK.md).

## Compatibility

- Domain: equivalent on every scenario in [FUNCTIONAL_EQUIVALENCE.md](FUNCTIONAL_EQUIVALENCE.md). Known theoretical differences (non-ASCII
  upper-casing, astral ordering) do not occur in SAP identifiers but need a guard.
- API: **not compatible** with the v1 frontend; the prototype exposes `/api/v1`. A v1 compatibility facade is the recommended path.
- Data: **not compatible in place**; v1's system of record is JSON stores. Migration is an import with verification.

## Remaining Python dependencies

None for the core. Candidates to keep isolated only if report output must stay identical: DOCX (python-docx) and PDF (ReportLab)
rendering. Recommended: re-implement with OpenXML and a PDF library and treat the frozen data model as the audit artifact. Python remains a
test-time dependency as the equivalence reference while v1 exists. See [DEPENDENCY_MAPPING.md](DEPENDENCY_MAPPING.md).

## Desktop and Server findings

- Windows 11 VM run (before the UI fix) [W]: Release build 0 warnings, 47/47 tests, Desktop and Server publish, Desktop launch, WebView2
  processes and loopback API (401 without token) all worked. The window showed 404: the build never produced the UI folder the host
  looked for. Fixed by embedding a `/api/v1` prototype UI in the assembly; see
  [DESKTOP_SERVER_DEPLOYMENT.md](../deployment/DESKTOP_SERVER_DEPLOYMENT.md#windows-finding-desktop-window-showed-no-page-get--404). Windows acceptance
  of the fixed build is still open.

- Same core for both; only host and security boundary differ. Loopback-only, per-run token injected by WebView2 so page script never sees
  it (fixes the v1 bootstrap finding F1 by design).
- Linux Server: verified end to end, including SIGTERM during an import (job handed back, resumed, completed once) and SIGKILL (recovered
  after lease expiry, completed once).
- **App Control is unchanged by the language.** .NET binaries are unsigned PE files like the PyInstaller and Go builds that were blocked.
  Signing and an IT publisher rule remain prerequisites for any Windows rollout.
- Native AOT is not viable with EF Core and WinForms; not needed for the measured startup times.

## Migration risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Audit trail moves from JSON stores to SQLite | High | Import with per-record hashes, chain anchored on v1 hashes, verification gate, v1 untouched until confirmation |
| Decisions orphaned by identity drift | High | SoD identities proven byte-identical; keep the equivalence suite as a permanent gate |
| v1 API surface (about 25 routers) to reproduce | High effort | Compatibility facade with replayed contract tests, router by router |
| Per-user identity, roles and approvals absent (trusted-LAN HTTPS exists with a shared token) | High (blocks production server use) | OIDC or Windows authentication with roles before use beyond a trusted test LAN |
| Memory 1.4x to 1.8x v1 | Medium (desktop laptops) | Interning, compact records, release staging early, workstation GC on Desktop |
| Report layout changes | Medium | Frozen model as evidence; one-time accepted layout change or isolated renderer |
| Windows behaviour unknown (service, WebView2, App Control) | High until measured | Phase 2 Windows acceptance runs |

## Remaining scope (not in the prototype)

Directory (employee) source, functional groups, position changes, Access Package and organizational suffix handling, username-list and
manager/band filters, exports, SoD governance, periods and frozen reports with DOCX/PDF, account review workflow and approval roles, server
accounts and sessions, encrypted portable backups and restore, scheduled refresh, branding, settings UI integration, the v1 API facade.

## Blockers for GO

1. Windows acceptance of the fixed Desktop build (checklist in DESKTOP_SERVER_DEPLOYMENT.md) and of the Server as a service.
2. Suffix handling (organizational suffix evidence and Access Package preview) not ported or equivalence-tested.
3. No rehearsed migration of v1 JSON stores.
4. No per-user identity for Server mode: trusted-LAN access now exists (HTTPS, fail-closed binding, shared token, sessions; not yet verified from another device), but accounts and roles do not.

## Conditions to convert to GO (Phase 2 exit criteria)

1. Windows: Server as a Windows service and Desktop on a managed machine, signed, pass start/stop/crash/reboot and App Control runs; same
   benchmark harness on Windows.
2. Port suffix handling and add it to the equivalence suite; all scenarios match on small and large sets.
3. Reduce loaded memory to at most 1.2x v1 on the large set, measured with the same harness.
4. Rehearse the migration importer on synthetic v1 stores with the verification gate passing and a demonstrated rollback.
5. Approve an identity design (OIDC or Windows authentication, roles) before network access is used beyond a trusted test LAN.

## Open questions for the owner

1. Must DOCX/PDF reports stay visually identical, or is the frozen data model the audit artifact?
2. Is Server mode expected to serve remote users in Phase 2, and which identity source (Windows integrated, Entra ID / OIDC, local
   accounts) is mandatory?
3. Who signs Windows binaries, and will IT provide a publisher rule for App Control?
4. Is a side-by-side v1/v2 period acceptable for users, and for how long?
5. What is the minimum desktop hardware (RAM) to plan memory targets against?
