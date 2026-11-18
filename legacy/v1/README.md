# SAP Lens 1 (legacy)

**Archived. Not the development target.** SAP Lens 2 (the .NET backend in [`backend/`](../../backend)) is the primary implementation; see the
[repository README](../../README.md). This folder keeps SAP Lens 1 for reference, data-format evidence and recovery. It receives no new features.
Installed SAP Lens 1 applications are not changed by anything in this repository's SAP Lens 2 tooling.

| Path | Content |
| --- | --- |
| `backend/` | Python 3.12 FastAPI backend and Windows desktop host (`desktop.py`), resources, `requirements*.txt`, unit and contract tests (`backend/tests`) |
| `scripts/` | v1 build system (`build.py`, `build.ps1`, `build_system/`), packaging, deployment packages, test runner (`run-tests.py`, `test-map.json`), browser-test server (`testing/serve-browser-tests.py`) and maintenance tools ([scripts](scripts/README.md)) |
| `deploy/` | v1 per-user installer (`windows/desktop-installer.iss`), WinSW service manager, Docker and systemd files |
| `Dockerfile`, `compose.yml`, `.dockerignore` | v1 container build |

Documentation: [docs/legacy/v1](../../docs/legacy/v1/README.md).

## What still runs from here

- The v1 runtime from source: `cd legacy/v1/backend && python -m uvicorn main:app --port 18744` (Python 3.12 with `requirements.txt`). It serves
  the shared `frontend/dist`. `npm run dev:backend` in `frontend/` uses it.
- The Playwright browser suite in `frontend/tests` starts this server through `scripts/testing/serve-browser-tests.py`.
- The .NET migration reference tools (`backend/tools/*_reference.py`) import this code to write comparison fixtures.

## What does not run in place

The v1 build, packaging and repository-contract tooling (`scripts/build.py`, `scripts/run-tests.py` profiles, `scripts/build_system`,
`deploy/`, the Docker build, and the tests in `backend/tests` that check repository layout, documentation paths or workflows) assumes the
pre-promotion layout, where these folders were at the repository root next to `frontend/`, `docs/` and `.github/`. They were archived unchanged.

To build, package or fully test SAP Lens 1, use a checkout of the last commit with that layout:

```bash
git worktree add ../sap-lens-v1 604f21e     # last commit before the promotion (v1 at the repository root)
```

The GitHub workflows in `.github/workflows` still describe the v1 pipeline with root-level paths; they run only on pushes to `main` and were not
changed (see [backend promotion](../../docs/migration/BACKEND_PROMOTION.md)).
