# Development & Testing

- [Development setup](DEVELOPMENT.md): prerequisites, virtualenv, browser dev and source-mode desktop.
- [Testing](TESTING.md): focused and full local checks, evidence and native limitations.
- [CI](CI.md): workflow ownership, validation, artifacts and explicit temporary skipping.
- [Implementation handoff](IMPLEMENTATION_HANDOFF.md): requirement coverage, validation results, limitations and next steps.
- [UI/UX gap audit](UI_UX_GAP_AUDIT.md): requirement-by-requirement verification of the consolidated refinement, remaining gaps and the data-aware-ux investigation.
- [Code quality review (R8)](CODE_REVIEW_R8.md): prioritized, evidence-based findings and next improvements.
- [Security review (R8)](SECURITY_REVIEW_R8.md): findings register with severity, evidence and status, controls verified, and what was not tested.
- [Validation tracker](../validation/README.md): the repository CSV of expected behavior per page, review status, defects and improvements, with the workbook generator.
- [Dependency maintenance](DEPENDENCY_MAINTENANCE.md): dated upstream/deprecation decisions, not a current audit result.

Build distributable packages using [Build](../deployment/BUILD.md); do not copy its
packaging pipeline into development instructions. Follow [AGENTS.md](../../AGENTS.md).
