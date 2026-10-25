# Downloadable deployment packages

Runtime support, an automated packaging test, and native acceptance are different
claims. The scripts/workflow below implement packaging; a downloadable Actions
artifact exists **only after an approved run succeeds**. No run is started by these
documents. See [actual validation](PACKAGING_VALIDATION.md).

## Manual build

Open Actions → **Build Deployment Packages** → Run workflow, select the intended
branch (normally `work`), then choose:

- `Windows Desktop`
- `Windows Server Service`
- `Linux Docker`
- `Linux Native/systemd`
- `All`

Supply base `version`, such as `0.1.0`, a `release_channel`, and a positive
`prerelease_number` for prereleases. Publication is controlled separately by
`publish_release`, **false by default**. All selected artifacts embed the same
resolved version, source commit and workflow run/attempt.

| Channel | Example |
| --- | --- |
| Alpha | `0.1.0-alpha.1` |
| Beta | `0.1.0-beta.1` |
| Release Candidate (RC) | `0.1.0-rc.1` |
| Stable / Production | `0.1.0` |

Base components and prerelease numbers are limited to 65535 for Windows PE
compatibility. Leading zeros, suffixes in the base, invalid channels and malformed
numbers are rejected. Stable ignores a valid supplied sequence; leaving it blank
is supported. There is no automatic sequence allocation: deliberately choose an
unused version when publishing. Legacy desktop `beta-N` tags are not moved or
reused by this SemVer scheme.

With `publish_release=false`, only Actions artifacts are created: **no tag or
GitHub Release**, even for a Stable version. An embedded version/tag name is
candidate metadata, not proof of publication. No binary signing or registry push
is enabled. Existing **Build Windows Application** retains its independent,
legacy desktop build/beta/stable release behavior unchanged.

With `publish_release=true`, every selected platform must finish its native
packaging and artifact roundtrip successfully. Only then can the isolated,
write-scoped publisher collect those exact same-run artifact IDs, verify their
names/checksums against successful job outputs, stage a draft, verify every
uploaded release asset's server-side SHA-256, create an owned annotated version
tag and publish. Alpha/Beta/RC are prereleases; Stable is a normal/latest release.
All selected packages, checksum sidecars and a source/digest manifest are attached.
A failed/skipped/cancelled selected platform prevents publication. Build-only runs
still upload successful independent platform packages when a sibling fails.

### Examples after workflow registration

For test packages: select `All`, base `0.1.0`, `Beta`, sequence `1`, and leave
**Publish release unchecked**. Download each successful job's Actions artifact.

For a Beta release: select the desired targets, base `0.1.0`, `Beta`, an unused
sequence (for example `2`), and explicitly check **Publish release**.

For Stable: select the desired targets (normally `All`), base `0.1.0`,
`Stable / Production`, and explicitly check **Publish release**. Existing
`sap-lens-stable` environment protection applies; prereleases use `sap-lens-beta`.
No repository/environment settings are modified by these source changes.

The CLI equivalent for a build-only run, **after the workflow is registered**:

```bash
gh workflow run build-deployments.yml --repo OnlyDrey/sap-lens --ref work \
  -f platform=All -f version=0.1.0 -f release_channel=Beta \
  -f prerelease_number=1 -f publish_release=false
```

Do not run publication commands without approval. Actions artifacts have the
configured retention period and an outer GitHub ZIP wrapper; release assets are
the actual deployment archives/sidecars and remain attached until explicitly
removed. This implementation does not publish anything during local development.

### Failure and concurrency safety

A read-only preflight rejects existing tags/releases before shared validation;
the publisher checks again after all packages pass. Existing refs/releases are
never overwritten, adopted or force-updated. Draft assets are uploaded before
tag creation. Publication is serialized independently across branches. A normal
failure removes only this invocation's draft and its provably owned annotated
tag; foreign tags and published releases are never removed. A lost successful
publish response is reconciled once without retrying publication.

GitHub does not offer a transaction spanning all release/tag calls. If remote
state cannot be read during recovery, cleanup stops and reports manual
reconciliation rather than guessing or deleting uncertain state. Inspect the
release, owned tag and run summary before a new dispatch. Do not blindly retry a
failed version or delete a pre-existing reservation. Mocks validate this policy;
live GitHub publication/rollback has not been exercised in this task.

GitHub requires a workflow-dispatch definition on the default branch before its
normal manual UI is available. Adding it only to `work` does not guarantee that
registration. Review/merge the approved workflow through the normal repository
process; no default-branch/settings change or merge is performed automatically.

Shared validation runs once per dispatch: backend/browser regressions, types,
production frontend, audits, workflow/PowerShell checks. Its frontend and identity
are sealed with hashes, source SHA, run/attempt and successful stage records.
Platform jobs accept only this same-run/attempt attestation. If GitHub reruns only
failed platform jobs under a new attempt, the prior attestation is deliberately
not accepted; an approved full rerun must regenerate shared validation. Each needs only shared
validation, so one platform failure cannot cancel or block another platform's
upload. A shared validation failure appropriately prevents all packaging.

## Outputs

Actions artifact names use the same stem as their inner archive:

| Platform | Inner deployment file |
| --- | --- |
| Windows Desktop | `SAP-Lens-Windows-Desktop-x64-<version>.zip` |
| Windows Service | `SAP-Lens-Windows-Service-x64-<version>.zip` |
| Linux Docker | `SAP-Lens-Linux-Docker-amd64-<version>.tar.gz` |
| Linux native/client | `SAP-Lens-Linux-Native-x64-<version>.tar.gz` |

Every artifact contains its archive plus `<archive>.sha256`, retained for 14 days.
GitHub wraps these files in another downloadable ZIP: extract that wrapper first.
The workflow downloads each upload again, checks its digest, inner checksum,
exact expected members and hashes. Desktop additionally uses its existing EXE/ZIP
verifiers; Service includes its PE/resource report and native SCM smoke result.

Server archives contain `package-manifest.json` with per-file hashes and build
identity. Windows Service includes pinned WinSW and its MIT license. Native
includes a hash-locked wheelhouse with dependency licenses; frontend production
license notices are included in compiled assets for all platforms. The repository
does not currently provide a separate top-level application license; do not infer
additional redistribution rights from third-party notices.

Only production application inputs and explicit deployment files are packaged.
CSV exports, snapshots, settings, secrets, test results, virtualenvs and Git history
are excluded. Target configuration is generated at install time; it must not be
prepopulated with an organization's data or access secrets.

## Local build equivalents

From a reviewed source checkout with production frontend already built:

```sh
.venv/bin/python scripts/deployment-package.py prepare --version 0.1.0
node scripts/frontend-licenses.mjs
.venv/bin/python scripts/deployment-package.py native
SAP_LENS_AUDIT_PYTHON=/path/to/audit-venv/bin/python \
  .venv/bin/python scripts/test-native-deployment.py --artifacts dist/deployment
```

Linux native packaging requires Linux x86-64/Python 3.12, network access to download
binary wheels, and runtime auditing tooling for its smoke test. Local Docker
packaging uses `scripts/package-docker.py` with Docker and `pip-audit` available;
`SAP_LENS_AUDIT_PYTHON` may point to an existing isolated audit interpreter. The
script builds, audits, smoke-tests and exports; it never pushes an image.

Local Windows Service retains the fresh local validation receipt workflow in
[Windows Server](DEPLOYMENT_WINDOWS_SERVER.md). CI's `-ValidatedCI` path requires
the same-run attestation; it is not an unchecked skip-validation option.

All local outputs live in Git-ignored `dist/deployment/` or `dist/server/`. Local
versions use the established `+local.<commit>` identity, not fabricated CI numbers.

Read [deployment/security](DEPLOYMENT.md) before exposing any server to a network.
