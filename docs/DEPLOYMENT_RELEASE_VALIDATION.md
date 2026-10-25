# Deployment channels and publication — Phase 2

Phase 1 was committed separately as `b2d4347` after 233 browser and 346 backend
tests passed. No deployment workflow was modified before that gate.

## Implementation

The manual-only `Build Deployment Packages` workflow retains its four independent
platform jobs and once-per-run shared validation. It adds explicit Alpha/Beta/RC/
Stable selection, a prerelease sequence and `publish_release=false` by default.
`version` remains a base version. Exact artifact stems/package formats remain
Windows Desktop x64 ZIP, Windows Service x64 ZIP, Linux Docker amd64 tar.gz and
Linux Native x64 tar.gz, now with the full requested SemVer version.

`backend/version.py` adds strict schema-2 deployment identities. Schema-1 legacy
Windows beta-N/build/local behavior remains unchanged. Both schemas pass the same
source/run/numeric PE/resource parser validation. This changes generated build
metadata, not user settings or data migrations. A candidate tag field is not a
remote reservation. The existing Windows release workflow is untouched. Its default packaging path
still uses legacy reservation checks. The deployment orchestrator explicitly
selects a new canonical packager admission switch that verifies the sealed
same-run deployment receipt; this avoids regenerating/rejecting its channel
identity through the legacy release allocator. Package and smoke stages remain
the existing implementations.

`deployment-package.py` resolves the candidate before validation and checks tag/
release availability only when publication was requested. `check-deployment-download.py`
exports its verified filename/digest. An isolated write-scoped publisher receives
same-run artifact IDs only after successful selected jobs; it refuses partial,
missing, mismatched or stale context and verifies the collected hashes again.
Only that job can create a draft/tag/release. No registry login/push was added.

`deployment-release.py` stages draft assets, verifies uploaded asset state/size/
SHA-256, then creates a uniquely owned annotated tag and publishes. Rollback may
remove only the known owned draft/tag. Published/foreign/uncertain state is
preserved; a lost publish response is reconciled once, without publication retry.
GitHub API calls are not atomic: unreadable cleanup state requires manual
reconciliation. No absolute network-failure rollback guarantee is claimed.

## Validation

Offline tests cover all channels and PE numeric/string metadata, legacy identity
compatibility, malformed input/tampering, build-only no-network behavior, manual
same-commit/run/attempt admission, all/individual target eligibility, partial
failure/cancellation/skipping, exact asset collection, checksum/source manifest,
permissions/trigger/dependency mutations, tag/release rejection, uploaded digest
failure, owned rollback, foreign-tag preservation and lost/uncertain responses.
All GitHub publication tests use an in-memory API model. They create no actual
tags/releases or remote calls.

Final command counts are recorded below after the frozen backend/static pass.
No additional comprehensive browser run is needed for packaging-only changes;
Phase 1's 233-case result remains the frontend baseline. Native Windows packaging,
SCM/reboot/recovery/UNC, live GitHub artifact handling/publication and target-host
acceptance remain pending. No Actions minutes were consumed.

## Following additions

The local cross-platform build interface is the next phase. Installation/upgrades
follow only after that phase's available validation passes. Neither addition
replaces this workflow's same-run validation or the canonical platform verifiers.

### Final local results

- Deployment-focused suite: **29 passed** (0.163 seconds).
- Full backend with deprecations as errors and portable PowerShell available:
  **365 passed, zero skipped**, 17.622 seconds.
- Workflow contract checker and SHA-pinned actionlint syntax/schema/expression/
  shell validation: passed.
- PowerShell parser/static guards, changed-document links and `git diff --check`:
  passed. Legacy `build-windows.yml` has no diff.
- Phase 1 production build/types and 233-case browser result remain valid; no
  frontend source changed in Phase 2. Production audits passed in Phase 1.
- GitHub publication, tag rollback against the live API, native Windows package
  builds and workflow execution were **not performed**. Tests used mock API state
  and synthetic archive/resource fixtures; these do not establish native success.

No pushes, tags, releases, registry writes or workflow dispatches occurred.
