# AuthLens – Claude Code

@AGENTS.md

## Project documentation

- Build and test (`backend/`): `docs/development/README.md`; deployment: `docs/deployment/README.md`
- Release status and open native checks: `docs/migration/RELEASE_STATUS.md`, `docs/deployment/WINDOWS_DEPLOYMENT.md#acceptance-checklist-windows-pending`
- SAP Lens 1 is archived outside the repository; its historical documentation is in `docs/archive/v1/`

## Working rules

Follow the shared instructions in AGENTS.md; they are authoritative and are not repeated here.

- Before implementation, inspect `git status` and safely fast-forward `experiment/dotnet-backend` from `origin/experiment/dotnet-backend`.
- Preserve local changes and existing functionality.
- Follow Progressive test validation (AGENTS.md): Level 1 direct tests after each change, Level 2 affected files, broad profiles only at checkpoints. Do not run full regression without explicit authorization.
- Commit and push completed phases to `origin/experiment/dotnet-backend`.
- Never force-push, modify `main`, dispatch workflows or publish releases without authorization. CI runs only on push to `main` (see AGENTS.md, GitHub Actions CI policy); pushes to `work` do not trigger it, so validate locally.
