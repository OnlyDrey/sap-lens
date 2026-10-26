# Testing and validation

Use a prepared environment from [Development](DEVELOPMENT.md), running commands
from the repository root. During changes, run affected regressions first; freeze
implementation before a comprehensive pass. Do not claim an unexecuted check passed.

## Local checks

```sh
python -m unittest discover -s backend/tests -v
python -m pip check
npm --prefix frontend ci
npm --prefix frontend run check:types
npm --prefix frontend run build
node frontend/node_modules/playwright/cli.js install chromium
npm --prefix frontend run test:browser
npm --prefix frontend audit --omit=dev
python scripts/check-docs.py
python scripts/check-workflows.py
pwsh -NoProfile -File scripts/check-powershell.ps1
node scripts/sync-lucide-catalog.mjs --check
git diff --check
```

On Linux install required Playwright system libraries through your approved
administrator process. A prepared host may set PLAYWRIGHT_EXECUTABLE_PATH to a
compatible Chromium; report that override. Do not increase workers without fixture
isolation or count targeted runs as an integrated full-suite pass.

[CI](CI.md) documents Python auditing/tool isolation and actionlint. Report production
and development advisories separately; do not suppress them. Packaging validation
uses the canonical [build entry points](../deployment/BUILD.md), attested frontend
inputs, exact archive checks and platform-specific smoke tests.

## Evidence and limits

Record source SHA, exact commands, failures/corrections, final results and execution
environment. Use synthetic fixtures only. Review both themes and responsive widths
for visual changes. Keep screenshots/traces outside tracked files because real
investigations may contain personal data.

Linux unit/browser tests and mocked native bridges do not prove Windows/WebView2,
SCM, installer, real systemd boot/recovery or UNC behavior. See the [validation
matrix](../deployment/README.md#validation-status) and [dated evidence](../archive/README.md).
Never dispatch expensive builds or publish artifacts without the required approval.
