# SAP Lens – Claude Code

@AGENTS.md

## Project documentation

- Build system: `docs/BUILD.md`
- Current build implementation status and acceptance checklist: `docs/BUILD-HANDOVER.md`

## Working rules

Follow the shared instructions in AGENTS.md; they are authoritative and are not repeated here.

- Before implementation, inspect `git status` and safely fast-forward `work` from `origin/work`.
- Preserve local changes and existing functionality.
- Use targeted validation during development. Do not run full regression without explicit authorization.
- Commit and push completed phases to `origin/work`.
- Never force-push, modify `main`, dispatch workflows or publish releases without authorization.
