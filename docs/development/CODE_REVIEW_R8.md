# Code quality review (R8)

Scope: backend, frontend, shared components and the desktop and server integration at commit `53f292e` plus the R8 changes.
Method: static scans (AST import and function-length analysis of `backend/`, export reference analysis of `frontend/src`, dependency usage
checks), reading of the security and lifecycle paths, and the existing test suites. No performance measurements were taken. Findings are split
into **confirmed** (evidence in the repository) and **suspected** (plausible, not measured). Nothing here is a refactoring request for style alone.

Priority = impact and likelihood. Effort = rough size of the fix.

## Confirmed findings

| ID | Priority | Effort | Finding and evidence | Status |
|---|---|---|---|---|
| CQ-01 | Low | XS | Four unused imports: `ClassVar` in `sod_import.py`, `Path` in `employee_directory.py` and `windows_tray.py`, `context_key` in `routers/sod_governance.py` (AST scan). | Resolved |
| CQ-02 | Low | XS | Dead exports: `fetchRolesByTcode` (`frontend/src/api/client.ts`) and the `QueueItem` type (`frontend/src/api/sod.ts`) are referenced nowhere. | Resolved |
| CQ-03 | Low | S | Duplicated business logic: the refresh-changes CSV export had its own `safe()` neutraliser, weaker than the shared `spreadsheet_cell` (see security finding SEC-01). One function is now used by every CSV writer. | Resolved |
| CQ-04 | Medium | S | Documented but unused shared components: `MetricTile`, `FilterTile`, `EvidenceBadge`, `AccountEvidence`, `SourceStatusSummary` have no consumer. `MetricTile` also carries its own tone rule (`tone && value > 0`) that bypasses `lib/kpiTone.ts`. Removing them also means editing `docs/architecture/COMPONENTS.md`. | Open: needs an owner decision (remove, or migrate to `kpiTone`) |
| CQ-05 | Medium | M | Complexity hotspots (functions of 150 lines or more): `csv_lifecycle.load` (234), `main.create_app` (201, includes the inline security middleware), `desktop.run` (170), `configuration_routes.configuration_router` (167), `windows_tray._run` (166), `user_access.build_users` (156). Behaviour is covered by tests; the size makes changes riskier. | Open: extract behind the existing tests when next touched |
| CQ-06 | Low | M | Very large components: `SettingsView.tsx` (1157 lines), `UserComparison.tsx` (720), `AccountReview.tsx` (673), `ReleaseRoles.tsx` (642). | Open |
| CQ-07 | Low | S | The toolchain has no Python linter or type checker and no ESLint; CI runs unit and browser tests and `tsc`. Unused imports were found only by an ad-hoc scan. | Open: recommendation below |
| CQ-08 | Informational | none | `lxml` and `charset-normalizer` in `backend/requirements.txt` have no direct import; they are required by `python-docx` and `reportlab` and are pinned on purpose. | Accepted |
| CQ-09 | Informational | none | Matrix "All users" is not virtualized and is capped at 5000 users per page (documented in the SoD guide). | Accepted |

## Suspected risks (not measured)

| ID | Priority | Suspicion | How to confirm |
|---|---|---|---|
| CQ-S1 | Medium | The SoD matrix, Explorer and queue endpoints rebuild the scoped user model on every request; with tens of thousands of users each page change could be slow. | Benchmark with a synthetic 10k-user dataset and profile `scope.scoped`. A per-generation cache keyed by filters is the likely fix. |
| CQ-S2 | Low | Several screens keep large result sets in TanStack Query for each distinct filter combination, which can retain memory in long sessions. | Heap snapshot after a long browsing session. |

## Error handling and API contract observations

- Unhandled exceptions are answered with one generic JSON message in both desktop and server mode; details stay in logs without paths (checked by `test_security_surface`).
- Content problems in CSV files are reported as structured validation results or 400 responses with authored messages; no raw exception text was found in responses during this review.
- No broad `except` that silently passes was found in `backend/` (AST scan). The frontend uses empty catch blocks only around optional browser storage.

## Missing test coverage worth adding

- Frontend unit tests (all current frontend tests are Playwright browser tests).
- A load test for CQ-S1.
- Windows service, WebView2, UNC and systemd acceptance (not executable on the Linux CI host; see the security review).

## Recommended next improvements

1. Add `ruff` (unused imports, simple bugs) to `validate.yml`; low effort, immediate value (CQ-07).
2. Decide on CQ-04 and remove or migrate the unused shared components.
3. Benchmark CQ-S1 before any caching work.
4. Split `create_app` so the security middleware is a separate, unit-testable module (CQ-05).
