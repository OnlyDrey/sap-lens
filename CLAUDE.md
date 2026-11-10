# SAP Lens – Claude Code

@AGENTS.md

## Project documentation

- Build system: `docs/BUILD.md`
- Platform acceptance status and open native checks: `docs/deployment/README.md#validation-status`

## Working rules

Follow the shared instructions in AGENTS.md; they are authoritative and are not repeated here.

- Before implementation, inspect `git status` and safely fast-forward `work` from `origin/work`.
- Preserve local changes and existing functionality.
- Follow Progressive test validation (AGENTS.md): Level 1 direct tests after each change, Level 2 affected files, broad profiles only at checkpoints. Do not run full regression without explicit authorization.
- Commit and push completed phases to `origin/work`.
- Never force-push, modify `main`, dispatch workflows or publish releases without authorization. CI runs only on push to `main` (see AGENTS.md, GitHub Actions CI policy); pushes to `work` do not trigger it, so validate locally.
