# Repository guidance

- Preserve the README `<!-- LOGO -->` block, including the logo path, SAP Lens title, and SAP S/4HANA description, unless the user explicitly requests a change. Keep the navigation links immediately below the description in the centered paragraph.
- Each cloud task is isolated. Use the existing checkout; do not create a Git worktree unless requested.
- SAP role exports, local settings, logs, .env files and credentials must not be committed or included in release artifacts.
- The desktop server binds only to 127.0.0.1, preferring port 18743 and securely falling back to an OS-assigned port. Do not weaken local host/origin checks, expose the API to a LAN, or cache role data in a service worker.
- Validate backend changes with `python -m unittest discover -s backend/tests -v`, and frontend changes with `npm ci` and `npm run build` from `frontend`.
- Windows packaging and desktop lifecycle checks run in `.github/workflows/build-windows.yml`.

## Mandatory pre-push validation

Complete the implementation locally before pushing. Do not push partial work or
start remote builds as an iterative debugging loop. Preserve existing local-only
commits. Run and record the exact commands and results before delivery:

1. Relevant fast checks, including `git diff --check` and workflow lint when changed.
2. `npm ci`, `npm run check:types`, and `npm run build` in `frontend`.
3. `python -m unittest discover -s backend/tests -v` in the prepared virtualenv,
   including repository integrity/privacy, configuration persistence and migration tests.
4. `python -m pip check`, applicable Python vulnerability auditing, and
   `npm audit --omit=dev`. Report development advisories separately; do not suppress findings.
5. `npm run test:browser` in `frontend`, plus regression tests for changed behavior.
   Inspect screenshots and meaningful screenshot comparisons for visual changes.
6. When packaging, Windows build behavior, desktop integration or release readiness
   is affected, run the canonical Windows build and packaged EXE smoke tests on
   Windows. Verify output assets, privacy boundaries and SHA-256 manifests.

A TypeScript build alone is insufficient. If a required check fails, investigate,
fix, rerun affected checks, then rerun the complete required suite. Never report a
check as passed unless it actually executed successfully. Record commands,
outcomes, visual review and platform limitations in the delivery report.

If Windows testing is unavailable, state that explicitly: Linux browser/unit tests
are not equivalent to Windows/WebView2 or packaged-EXE validation. Finish all
available local work and present a concrete reviewable result, then request
explicit approval before pushing with incomplete Windows validation. Do not claim
complete validation. Only push the finished version after required checks pass or
such an exception is explicitly approved. Verify the remote SHA after an authorized
push. Do not start a remote Windows build without explicit authorization.

After changing Lucide or its catalog, run `node scripts/sync-lucide-catalog.mjs --check`
following `npm ci`; regenerate with the same script without `--check` when needed.

## Architecture and documentation map

- Work on the existing development branch; preserve approved history and private
  data. Do not publish, push or dispatch workflows beyond explicit session authority.
- Shared business logic lives under `backend/`; `backend/desktop.py` owns the
  Windows WebView2 lifecycle and `backend/server.py` the headless single-worker
  runtime. Centralize hosting policy in `backend/deployment.py`. Do not duplicate
  CSV import, role matching, transaction evidence or account interpretation per OS.
- Server mode must use separate mutable storage, enforce its authentication and
  host/origin boundary, and keep browser uploads local to the configured server.
  Optional disabled/missing sources are not permission to erase valid snapshots.
- `build.sh`/`build.ps1` delegate local orchestration; canonical packaging remains
  in `scripts/`. Keep legacy desktop release behavior separate from deployment
  publication. No automatic tags/releases/registry pushes from local builds.
- Reuse frontend Shared components, semantic tokens and isolated Component Library
  previews. Navigation links, content tabs, filters and actions have distinct
  semantics; preserve keyboard focus and source evidence.
- Start at [documentation index](docs/README.md), [deployment](docs/DEPLOYMENT.md),
  [local builds](docs/LOCAL_DEPLOYMENT_BUILDS.md),
  [design system](docs/DESIGN_SYSTEM.md) and
  [component APIs](docs/COMPONENT_LIBRARY.md). Update the canonical guide and index
  when behavior/commands change, rather than copying procedures into new reports.
- README LOGO navigation links may be maintained when requested, retaining the
  product image/title/description and existing header structure. Do not substitute
  organization branding. Keep licensing and third-party notices intact.
- Run `python scripts/check-docs.py` for relative documentation/image/anchor links.
  GitHub Releases is the release-history mechanism; do not introduce CHANGELOG.md.
- Use synthetic/reserved-domain data only. Never auto-import examples into real
  settings, include examples/private data in packages, or infer effective SAP
  authorization/license entitlement from role/T-code mappings.
- Native Windows installer/SCM/WebView2, real systemd, reboot/recovery and UNC
  acceptance must be reported separately from Linux unit/browser/static checks.
  Preserve the mandatory validation and explicit pre-push approval rules above.
