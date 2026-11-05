# Development & Testing

- [Development setup](DEVELOPMENT.md): prerequisites, virtualenv, browser dev and source-mode desktop.
- [Testing](TESTING.md): focused and full local checks, evidence and native limitations.
- [CI](CI.md): workflow ownership, validation, artifacts and explicit temporary skipping; [CI/CD architecture](../deployment/CI_CD.md): the three validation levels and the no-prerequisite policy.
- [Validation tracker](../validation/README.md): the repository CSV checklist (22 functional areas) with validation status, separate manual approval, findings and a future-improvements backlog, and the Excel workbook generator.
- [Dependency maintenance](DEPENDENCY_MAINTENANCE.md): dated upstream/deprecation decisions, not a current audit result.

Build distributable packages using [Build](../BUILD.md); do not copy its
packaging pipeline into development instructions. Follow [AGENTS.md](../../AGENTS.md).
- [Development progress](PROGRESS.md): phase status, commits, measurements and next actions for resuming work.
