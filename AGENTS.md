# Repository guidance

- Preserve the README `<!-- LOGO -->` block, including the logo path, SAP Lens title, and SAP S/4HANA description, unless the user explicitly requests a change. Keep the navigation links immediately below the description in the centered paragraph.
- Each cloud task is isolated. Use the existing checkout; do not create a Git worktree unless requested.
- SAP role exports, local settings, logs, .env files and credentials must not be committed or included in release artifacts.
- The desktop server binds only to 127.0.0.1, preferring port 18743 and securely falling back to an OS-assigned port. Do not weaken local host/origin checks, expose the API to a LAN, or cache role data in a service worker.
- Validate backend changes with `python -m unittest discover -s backend/tests -v`, and frontend changes with `npm ci` and `npm run build` from `frontend`.
- Windows packaging and desktop lifecycle checks run in `.github/workflows/build-windows.yml`.
