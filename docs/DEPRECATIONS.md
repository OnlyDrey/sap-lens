# Deprecation maintenance

Baseline: branch `work`, commit
`733e5dadef9b92ad430824d012a6c5d491dbe43e`, successful Windows run
[39618620170](https://github.com/OnlyDrey/sap-lens/actions/runs/39618620170).

## Starlette TestClient transport

The baseline backend test log reports:

```text
StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
```

FastAPI 0.151.0 re-exports Starlette's TestClient. Installed Starlette 1.9.0
prefers `httpx2` and warns when falling back to `httpx`. SAP Lens tests already
use the supported TestClient API; the deprecated choice is the test dependency
in `backend/requirements-dev.txt`.

Replace `httpx==0.28.1` with `httpx2==2.16.0`, pinned and compatible with Python
3.12 and this Starlette version. Its transport is `httpcore2==2.16.0`; it also
requires `truststore`. Runtime/desktop/build requirement files, application code
and FastAPI/Starlette versions are unchanged. Test-only dependencies continue to
be installed in the existing build environment for the Windows backend tests;
no PyInstaller parameters, hooks, exclusions or package validation rules change.

For an existing development virtualenv, install the current requirements. The
obsolete `httpx`/`httpcore` distributions may remain installed; remove them only
after checking that no other tools in that environment need them. Fresh test
environments no longer request them. Separate audit tooling has its own
dependencies and does not need this migration.

In addition to the usual suite, run:

```sh
python -W error::DeprecationWarning -m unittest discover -s backend/tests -v
```

This makes deprecations fail validation rather than hiding them. No warning
filters or suppression are added to the application or CI.

## Official artifact download action: upstream warning retained

The baseline artifact download log reports:

```text
[DEP0005] DeprecationWarning: Buffer() is deprecated due to security and usability issues. Please use the Buffer.alloc(), Buffer.allocUnsafe(), or Buffer.from() methods instead.
```

As checked on 2026-10-21, the SHA-pinned official
[`actions/download-artifact` v8.0.2](https://github.com/actions/download-artifact/tree/9000827ccba6bdab643e8b6fd33ac0654aef8333)
is already the latest published release. Its lockfile resolves
`@actions/artifact` 6.3.1 to `unzip-stream` 0.3.4. The bundled `UnzipStream`
constructor uses `new Buffer('')`; the package also has other deprecated Buffer
allocations. Constructing its extractor under `node --trace-deprecation`, with
the package copied outside `node_modules` to reproduce the action's bundled
location, reproduces DEP0005 without SAP Lens code or network access at execution.

Retain the warning until an official action release fixes the bundled dependency.
Do not patch the downloaded action, suppress Node warnings, downgrade the action,
or replace its verified download/extraction implementation merely to silence it.
When a fixed official release is available, review its changes, pin its immutable
SHA, and rerun Windows artifact validation.

The existing workflow remains unchanged: upload `SAP-Lens-Windows-x64` with
14-day retention, download that exact artifact ID, reject ZIP digest mismatches,
then rerun package verification on the downloaded files against the original EXE
SHA-256. The expected two-file distribution and consolidated report are retained.
Signing stays disabled. Native Windows validation is required before claiming
that the changed test dependency has no effect on the packaged application.

## Local validation: 2026-10-21

Executed on Linux with Python 3.12.14 and Node 24.19.0. No application or test
source changed during the complete validation run.

| Check | Result |
| --- | --- |
| `python -m unittest discover -s backend/tests -v` | 84 passed, including CSV, settings/migrations, desktop lifecycle and package-verifier tests |
| Same suite with `python -W error::DeprecationWarning` | 84 passed; legacy `httpx`/`httpcore` removed from this dedicated development virtualenv |
| `npm ci`, `npm run check:types`, `npm run build` (in `frontend`) | Passed |
| `node scripts/sync-lucide-catalog.mjs --check` | Passed |
| `npm run test:browser` (in `frontend`) | 30 passed in 6.5 minutes; system Chromium, one worker, zero retries |
| `python -m pip check` | Passed |
| `python -m pip_audit --path /workspace/sap-lens/.venv/lib/python3.12/site-packages --progress-spinner off` (separate audit environment) | No known vulnerabilities |
| `npm audit --omit=dev` (in `frontend`) | No vulnerabilities |
| Full `npm audit` | Existing seven development advisories: five high, two moderate; no suppression or unrelated upgrades |
| `actionlint` | Passed |
| PowerShell 7.6.7 parser and existing AST/timing checks | Both scripts parsed; success/failure records and error preservation passed |
| `python scripts/write-windows-metadata.py` | Passed |
| `git diff --check`, documentation links and repository integrity/privacy tests | Passed |

README, canonical PNG/ICO, runtime requirement files, frontend lockfile,
workflows, packaging/smoke scripts and verification rules are unchanged.
The local shell also reports cache ownership and NO_COLOR/FORCE_COLOR warnings;
these are environment messages, not the two repository deprecations above.
PowerShell timing-error warnings are deliberately exercised by its negative tests.

Native Windows/WebView2 execution, the Windows-only dependency audit, packaged
EXE smoke tests and artifact round-trip were not rerun for this change. The
baseline Windows run passed, but is not validation of the new dependency. One
new manual Windows build is recommended after explicit approval. No push or
workflow dispatch was performed for this maintenance task.
