# Local build implementation validation

Historical implementation evidence, not a guarantee that a later checkout or
machine has passed validation. For current commands, see
[Local Windows builds](LOCAL_WINDOWS_BUILD.md).

## Implementation validation record (2026-10-22)

Baseline: clean `work` at `cc61f74bf7e45cd8160cbd9ed1ebfa6dc12a7ce6`.
Read-only logs for run `39801318105` confirmed 61 passed / five failed browser
cases, before packaging. This was a test failure, not evidence of exhausted
Actions credits. The bootstrap document already declared `<meta charset="utf-8">`.
The five fixtures used Python `print()` with redirected CP1252 stdout on Windows,
then decoded the bytes as UTF-8 in Node. An ellipsis became byte `85` and then the
replacement character U+FFFD **before** `route.fulfill()` received the HTML.
Reproducing the same redirected encoding on Linux produced the identical failure.
`contentType: 'text/html'` alone was not the root cause.

The shared fixture now writes explicit UTF-8 bytes with `sys.stdout.buffer`,
uses Python UTF-8 mode and declares UTF-8 in synthetic HTTP responses. All five
exact status assertions remain. The new regression forces CP1252 stdout even on
Linux, checks the exact rendered ellipsis, HTTP charset and `document.characterSet`,
and checks a subsequent status update. Production bootstrap branding is unchanged.

Executed on Linux (Python 3.12.14, Node 24.19.0, npm 11.9.0, PowerShell 7.6.7):

| Check | Command (repository root unless specified) | Result |
|---|---|---|
| Dependency installation | `npm --prefix frontend ci --no-audit --no-fund` | Passed |
| Lucide catalog | `node scripts/sync-lucide-catalog.mjs --check` | Passed |
| Types | `npm --prefix frontend run check:types` | Passed |
| Production frontend | `npm --prefix frontend run build` | Passed |
| Backend | `python -W error::DeprecationWarning -m unittest discover -s backend/tests -v` | 209 passed |
| Browser (system Chromium) | `PLAYWRIGHT_EXECUTABLE_PATH=/usr/bin/chromium npm --prefix frontend run test:browser -- --reporter=line` | 67 passed; original 66 retained |
| Workflow contracts | `python scripts/check-workflows.py` | Passed |
| Workflow schema/expressions | `python scripts/ci.py lint` | Passed |
| PowerShell syntax/static guards | `pwsh -NoProfile -File scripts/check-powershell.ps1` | All four scripts passed |
| Python consistency | `python -m pip check` | Passed |
| Installed Linux Python audit | Separate audit interpreter: `python -m pip_audit --path <build-venv-site-packages> --progress-spinner off` | No known vulnerabilities |
| Production JavaScript | `npm --prefix frontend audit --omit=dev` | Zero vulnerabilities |
| All JavaScript (informational) | `npm --prefix frontend audit --json` | Existing 7 development advisories: 5 high, 2 moderate |
| Whitespace/integrity | `git diff --check` | Passed |

Sixteen new backend tests cover deterministic local identities, metadata resources,
invalid versions, complete/stale/modified receipts, Unicode/space paths, source and
environment changes, strict ZIP roundtrip/reverification, export failure handling,
requirement-driven tool checks, checksum-verified Windows actionlint provisioning,
non-Windows rejection and invalid PowerShell modes. Archive/PE malformed-input,
privacy and checksum regression coverage remains in the existing suite.
Windows actionlint extraction is tested with a synthetic archive; the executable
is never run in that unit test. Export tests stub the native PE subprocess while
running the real ZIP verifier; they do not prove Windows packaging success.

Bootstrap screenshots were inspected in light/dark mode at 800/1280 pixels; the
status text renders intact. No dependency versions or workflow triggers changed.
The README and canonical branding assets are untouched. The development advisories
remain visible; resolving them requires a separate compatible dependency review.
No vulnerabilities were suppressed.

**Pending:** native Windows PowerShell 5.1/7 end-to-end execution, full Windows-only
Python dependency audit, actual EXE packaging/PE verification and smoke tests,
WebView2/file-picker/UNC testing. No Windows artifact was built on Linux. No push,
workflow dispatch, tag or release was performed for this task.
