# SoD 2.0 — implementation and validation (28 October 2026)

Dated evidence for the SoD 2.0 redesign. Results apply only to the recorded source and
environment, not to later commits or native platforms. Current behavior:
[SoD guide](../../features/SOD.md), [SoD architecture](../../architecture/SOD.md),
[SoD matrix reference](../../data/SOD_MATRIX.md). Earlier baseline:
[SoD validation](SOD_VALIDATION.md).

**Environment:** Linux x86-64 container, Python 3.12.3 virtualenv, Node 22.22.0 (outside
the supported `>=24 <26` range), Chrome for Testing 153 via `PLAYWRIGHT_EXECUTABLE_PATH`
(Playwright expects build 1248, host has 1243). Synthetic data only.

## Results

| Check | Result |
| --- | --- |
| Backend `unittest discover` (Python 3.12) | 636 tests OK, 3 skipped (PowerShell ×2, PyInstaller) |
| `npm run check:types`, `npm run build` | Pass |
| Browser, complete suite (389 tests) | 389 passed |
| Browser, SoD and design-system specs re-run after final polish (66 tests) | 66 passed |
| `pip check`; pip-audit (runtime, dev, desktop, build); `npm audit` incl. dev | Clean; 0 vulnerabilities |
| `check-docs.py`, `check-workflows.py`, Lucide catalogue `--check`, `git diff --check` | Pass |
| Real-process headless server smoke (Basic auth, decisions, approval, exports, restart) | 20/20 |
| Visual review, both themes at 375, 800, 1280 and 1600 px | Reviewed; no overflow or clipping outstanding |

The server smoke covered 401 without credentials, activity, assignment and acceptance
decisions, separate approver enforcement, gated approval and freeze, valid PDF, DOCX and
remediation CSV, protection of an approved period from deletion, a source refresh that did
not change the frozen snapshot, and after a process restart identical snapshot checksum,
restored frozen decisions and a byte-identical approved report. Diagnostics, portable
configuration and report files held no decision text, filesystem path or shared secret.

## Defects found and corrected during implementation

1. Page overflow at 375 px: screen-reader text in empty matrix cells escaped the scroll
   region. The region is now its own containing block (guarded by the overflow assertion).
2. Keyboard navigation stalled in sparse matrices and, with column windowing, lost focus on
   Home/End. Both fixed and covered by tests.
3. Review history survives configuration reset by design, which leaked decisions between
   tests; the shared fixture now creates unique users per test.
4. The period delete card kept a separate copy of "Recorded by"; it now uses the dialog field.
5. Queue items for decisions whose evidence vanished offered an Open action with nothing to
   open; they now read "No longer detected" and have a Historical status filter.
6. Selecting a period that was archived elsewhere now falls back to current evidence.

## Requirement checklist

| # | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Preserve repository, no rewrite, work branch, no push or release | Done | Local commits on `work` after `5cca99c`; nothing pushed |
| 2 | Reuse existing SoD foundation; potential conflicts not verified authorization; risk catalogue stays in Settings | Done | Evidence module unchanged; catalogue only in Settings; wording tests |
| 3.1 | Overview with compact actionable KPIs, periods, changes, freshness | Done | `sod-governance.spec.ts` overview; `OverviewTests` |
| 3.2 | Risk Matrix (distinct totals, group aggregation, sticky/fixed headers, windowing, drilldown, no color-only status) | Done | `MatrixTests`, matrix, wide-matrix and keyboard specs |
| 3.3 | Activity Matrix with review state, role counts, review entry | Done | activity matrix spec and tests |
| 3.4 | Business matrices as Saved Filters (create, rename, apply, delete, clear) | Done | Saved filter spec; per-matrix isolation |
| 3.5 | Access Explorer: user risk, user activity, access list, lookup, traceability, CSV | Done | Explorer specs and export tests |
| 4.1 | Activity review: user + activity + context, four decisions, history, evidence version | Done | `DecisionTests` |
| 4.2 | Role assignment review, duplicate coverage, impact, approved-activity warning | Done | `ImpactTests`, panel spec |
| 4.3 | Calculation independent of decisions | Done | Approved activity still produces risk; simulation never mutates |
| 4.4 | Separate risk acceptance with approver, controls, expiry, reassessment | Done | acceptance tests; Outdated lifecycle |
| 4.5 | Reviewer/approver workflow, rejection reason, actor and timestamp, no identity claims | Done | `test_sod_periods_v2.py`, periods spec |
| 5 | Shared investigation workspace, work queue, batch review, no cross-user propagation | Done | queue and batch specs; explicit-item API |
| 6 | Role contribution, non-destructive what-if, several options, remediation tracking and verification | Done | `ImpactTests`, `RemediationTests`, remediation spec |
| 7 | Periods: improved lifecycle, comparisons, secure deletion (typed name, protection, archival, no orphans) | Done | `DeletionTests`, periods spec |
| 8.1 | Formal 13-part report, PDF/DOCX, sections, languages, signatures, technical appendix | Done | `FormalReportTests`, reports spec |
| 8.2 | Access remediation report (CSV, DOCX, PDF), handling groups | Done | `RemediationReportTests`, reports spec |
| 8.3 | Report integrity, frozen reproducibility | Done | reproducibility tests, restart smoke |
| 9 | Design system reuse, themes, responsive, keyboard, empty/error states, Component Library | Done | integration spec at 4 widths and 2 themes; library spec |
| 10 | Stable identities, explicit compatibility, no silent reinterpretation | Done | [architecture](../../architecture/SOD.md#migration-and-compatibility); legacy tests |
| 11 | Focused backend and browser tests for every listed area | Done | 69 new or rewritten governance, period and report backend tests; 12 governance browser tests plus rewritten analysis, integration, periods and reports specs |
| 12 | Phases with milestone reports | Done | Reported per phase |
| 13 | Docs, templates, validation report, checklist, limitations, Git state | Done | this record |

## Not executed or limited (do not treat as passed)

- **Windows:** WebView2 desktop, installer, packaged EXE, Windows Service/SCM, reboot,
  UNC paths, native Save dialog, and opening DOCX in desktop Word. The bridge contract is
  covered by mocked native tests only.
- **Linux Docker image and native packages / systemd:** not built or booted here; the
  headless server smoke covers runtime behavior only. See the
  [earlier validation](SOD_VALIDATION.md#not-executed-do-not-treat-as-passed).
- **Legacy period editor:** periods created before SoD 2.0 keep their legacy screen. Its API
  is covered by backend tests; the screen itself has no browser test because no public path
  creates a legacy period.
- **Tooling and platforms:** PowerShell, actionlint and PyInstaller were absent; Node 22
  and a Chromium override were used.

## Design decisions and remaining limitations

- The Activity Matrix and review population are the activities and assignments that
  contribute to a detected conflict; unrelated activity evidence is not listed.
- Role assignment decisions are recommended but do not block period approval; activity and
  risk acceptance decisions do. Reopening an approved period is not supported.
- Non-active assignment validity is read-only for review. Reviewer, approver and actor names
  are self-reported; reports are not digitally signed.
- "Changes since the previous refresh" starts at the first observation and compares only
  findings, not changed risk definitions (those remain in the refresh report).
- Matrices page 50 rows at a time, window columns above 48 and return at most 500 columns.
