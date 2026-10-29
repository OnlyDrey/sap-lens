# SoD — final regression and delivery validation (28 October 2026)

Dated evidence for Phases 10–11 of the SoD implementation. Results apply only to
the recorded source and environment, not to later commits or native platforms.
Current behavior: [SoD workflow](../../features/SOD.md) and
[SoD matrix reference](../../data/SOD_MATRIX.md).

**Source:** `origin/work` at `3c5ad40` (Phases 1–9) plus the Phase 10 and 11 commit
that carries this record. **Environment:** Linux x86-64 container, Python 3.12.3
virtualenv, Node 22.22.0, Chrome for Testing 153 (`PLAYWRIGHT_EXECUTABLE_PATH`
override; Playwright expects build 1248, host has 1243). Synthetic data only.

## Results

| Check | Result |
| --- | --- |
| Backend `unittest discover` (Python 3.12) | 574 tests OK, 3 skipped (PowerShell x2, PyInstaller) |
| `npm run check:types`, `npm run build` | Pass |
| Browser, first full run (373 tests) | 369 passed, 4 failed (stale pre-SoD assertions, below) |
| Browser, final full run on corrected code (375 tests) | 375 passed |
| `python -m pip check`; pip-audit (runtime, dev, desktop, build requirements) | Clean; no known vulnerabilities |
| `npm audit --omit=dev` and full `npm audit` | 0 vulnerabilities |
| `check-docs.py`, `check-workflows.py`, Lucide catalog `--check`, `git diff --check` | Pass |
| Real-process headless server smoke (`backend/server.py`, Basic auth) | 22/22 |
| Privacy scan of diagnostics, portable config, DOCX, PDF and four CSV exports | 10/10 |

The server smoke covered: 401 without or with wrong credentials, foreign Host and
Origin rejection, source selection confined to the source root, SoD import, period
freeze, valid PDF and DOCX, approved-status rejection for an open period, an
unchanged snapshot checksum after a source change and refresh, and period,
snapshot and byte-identical report restoration after process restart. The privacy
scan found no filesystem paths, shared secret or identities in diagnostics or
portable exports; DOCX author is the supplied "prepared by" value.

SoD-specific automated coverage that ran in the suites above: catalogue and import
lifecycle, deterministic analysis, review history and immutable evidence, period
approval gates and comparisons, report models, saved filters and settings
integration (12 backend modules, 6 browser specs including 375/800/1280/1600 px in
light and dark for catalogue, review, periods and reports).

## Defects found and corrected

1. **Main navigation clipped at 375 px** (introduced by the fifth item). Labels
   overlapped ("Role LookupUser Access"). Fixed in `components.css` (≤430 px: shared
   width, wrapping labels, 12 px type, safe centering); regression test added
   (`sod-integration.spec.ts`, 375 and 414 px) and shown to fail without the fix.
2. **Four stale assertions** written before SoD: five main navigation buttons, a
   fourth Data Health source tile, and the Settings tab order (SoD Risk
   Configuration follows SAP Modules). Product behavior was intended; tests updated.
3. **Documentation:** stale "reports are being implemented" text, "three sources"
   counts, missing SoD workflow guide and API table, and an untested synthetic SoD
   example (new parser test).

## Visual review

Inspected screenshots of Access Review, Review Periods, Reports and Risk Catalogue
in both themes at 375, 800, 1280 and 1600 px. After the navigation fix the strip fits
without overflow at 375 and 414 px; secondary tabs scroll horizontally by design.
Test fixtures contain one finding, so dense-table appearance is covered by
assertions and earlier screenshots rather than this review.

## Not executed (do not treat as passed)

- **Windows:** WebView2 desktop, installer, packaged EXE smoke, Windows Service/SCM,
  reboot/recovery, UNC paths, native Save dialog and native Word opening of DOCX.
- **Linux Docker:** the CLI exists but no daemon was available; image build and
  container lifecycle were not run.
- **Linux Native package:** `build.sh --platform linux-native` needs Node 24 or 25
  and a clean commit; the installer, real systemd boot/recovery and target OS
  (Ubuntu 22.04/24.04) acceptance were not run. The headless server smoke above is a
  substitute for runtime behavior only, not for packaging.
- **Tooling absent:** PowerShell (`check-powershell.ps1`, two skipped tests),
  actionlint and PyInstaller.
- **Node 22 host:** `npm ci`, types, build and tests ran outside the supported
  `>=24 <26` range; CI is the authority for that range.
- **Python 3.13:** two Linux lifecycle tests fail by design (the installer requires
  3.12); the recorded run used 3.12.
- No remote workflow was dispatched and no tag or release was created.

## Remaining limitations

Reviewer and approver names are self-reported; reports are not digitally signed.
Report and CSV limits are documented in the SoD reference. The DOCX package keeps
python-docx's generic template thumbnail (no personal data).
