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

## Risk-based selection during development

Run targeted checks while editing, Fast Validation at each phase boundary and Full
Validation once after the final phase, as defined in the validation policy of
[repository guidance](../../AGENTS.md). The local-check list above is the Full
Validation checklist, not a command block to repeat following every edit. Reinstall dependencies only when their inputs/environment
changed; rebuilding is necessary before browser tests of changed production code.

| Changed area | Targeted / Fast Validation primary coverage |
| --- | --- |
| UI component or filter | Affected browser cases, keyboard behavior, type checking |
| CSS, layout, theme | Affected browser cases and representative screenshots |
| Backend API | Corresponding API/module tests and consumers |
| CSV import | Validation, atomic replacement, failure preservation, persistence and dependent views |
| Authentication/access | Security boundary and affected integration tests |
| Shared infrastructure | Broader integration coverage; FULL when impact is uncertain |
| Documentation only | Documentation links and affected repository contracts |

Inspect imports/callers and fixtures before selecting tests. This table is guidance,
not an automatic filename-based exemption. If impact is unclear, broaden coverage.

Copyable targeted examples (repository root, prepared environment):

```sh
python -m unittest discover -s backend/tests -p 'test_csv_lifecycle.py' -v
python -m unittest discover -s backend/tests -p 'test_auto_import.py' -v
npm --prefix frontend run test:browser -- tests/refinement-27.spec.ts --grep 'anchored controls'
npm --prefix frontend run test:browser -- --list
```

Use the actual affected test names; `--list` verifies selection without running
browsers. Backend discovery with `-p` avoids importing unrelated test modules. Keep
per-test temporary directories, application state reset and subprocess lifecycles:
they provide isolation and restart coverage rather than redundant initialization.

### Execution review and measured baseline

The last completed UI/tray pass ran 305 browser tests in approximately 9.2 minutes
and 446 backend tests in 25.536 seconds. These are historical measurements before
automatic-import changes, not proof that current inputs pass. No speedup percentage
is claimed. The practical saving is avoiding repetitions of those unchanged suites.

Playwright already reuses its browser process and one production test server per
invocation, with isolated page contexts. The backend server and mutable configuration
are shared across tests; retain one worker and zero retries until fixtures isolate
that state. `reuseExistingServer: false` prevents accidentally testing stale assets
or a real user's server. No fixed `waitForTimeout` calls were found in the browser
suite during this review. Backend short polling waits cover asynchronous lifecycle
behavior; removing them or sharing mutable fixtures would reduce reliability.

For slow runs inspect Playwright duration output/traces and `scripts/ci.py` phase
timings. Capture only changed screens during development; reuse unchanged visual
artifacts and review both themes/responsive widths at final freeze.

CI already caches npm/pip downloads and validates once before independent deployment
package jobs reuse attested frontend assets. Fast and Full retain overlapping backend
checks for distinct push/PR gates; desktop release validation has its own trust path.
Do not remove those checks or reuse another workflow's results without exact source,
input and trust equivalence. No workflow triggers, permissions or worker counts were
changed by this review. See [CI architecture](CI.md).
