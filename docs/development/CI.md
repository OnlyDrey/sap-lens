# Local validation and GitHub Actions (SAP Lens)

The sole active workflow is `.github/workflows/validate.yml`, triggered **only by
push to main**. No experiment/work/PR, dispatch, schedule, downstream workflow or
production deployment trigger exists. Jobs have read-only repository permissions,
pinned actions, bounded timeouts and no publish credential. No workflow was run
while implementing this migration.

Jobs:

- Frontend: reproducible `npm ci`, version and repository contracts, unit tests,
  typecheck/lint/build, icon consistency, documentation, tracked-secret scan and
  production npm audit. The built UI is uploaded once for backend/browser jobs.
- Backend: .NET 10 restore/build and non-publish tests on Linux and Windows;
  NuGet advisory audit, active PowerShell syntax and Pester deployment tests.
- Browser: .NET fixture, one worker, focused UI/host smoke plus shared Component
  Library. Failure traces are preserved. The rest of the browser suite remains
  available locally; specs that still configure source files through a settings save (a SAP Lens 1 contract the .NET
  host refuses) are migration gaps of the harness and are not claimed as passing ([development](README.md#browser-tests)).
- Docker: build the optional Linux image with the exact source SHA. No push or
  container deployment. The Docker frontend stage builds from the same lockfile.

SAP Lens 1's workflow definitions were archived with it outside this repository; only `validate.yml` exists. Existing v1 release tags/assets
are unchanged. No replacement release publisher is enabled: stable promotion,
validated exact-commit artifacts and release approval remain required before any
future publication. Installer/deployment scripts still validate manifests and
checksums locally.

Local equivalents, from the repository root:

```bash
python3 -m pip install -r scripts/requirements-checks.txt
python3 scripts/check-workflows.py
python3 scripts/check-structure.py
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
node --test scripts/tests/*.test.mjs
node scripts/product-version.mjs
node scripts/sync-lucide-catalog.mjs --check
python3 scripts/check-docs.py
python3 scripts/check-secrets.py
```

.NET/frontend/browser commands and progressive scope are in
[development](README.md). `scripts/check-dependencies.py` fails on advisory findings
or malformed audit output; an unavailable advisory service is not a clean audit.
Python is required only for repository checks and optional historical reference
generators, never to start the active application or its default browser host.
