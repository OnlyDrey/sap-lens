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

Supply base `version`, such as `0.1.0`. One immutable build identity is generated,
for example `0.1.0-dev.123`; all selected artifacts embed that version and the same
source commit. This workflow does **not** reserve release tags, publish GitHub
Releases, sign binaries, or push images. Existing **Build Windows Application**
remains the separate desktop build/beta/stable release workflow, unchanged.

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
