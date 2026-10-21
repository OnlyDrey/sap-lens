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
