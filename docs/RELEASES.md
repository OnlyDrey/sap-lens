# Manual Windows builds and releases

The existing **Build Windows Application** workflow has three explicit manual
modes. Fast Validation still runs on every push/PR; Full Validation still runs
only for PRs targeting main. Tags and releases do not trigger another Windows
build. No new workflow, runtime dependency or signing mechanism is introduced.

## Inputs and version authority

Select Actions → Build Windows Application → Run workflow, then the source branch.
The selected branch must contain this workflow and its publication script; merge
the reviewed implementation into main before using stable mode. GitHub's Actions
form may display the default branch's workflow inputs until that definition is
updated through the normal review process.

| Input | Behavior |
| --- | --- |
| release_mode: build | Default. Tests, audits, builds, smoke-tests and verifies the normal Actions artifact; no tag or release |
| release_mode: beta | Builds/verifies first, then publishes a numbered testing prerelease; work is supported |
| release_mode: stable | Builds/verifies first, then publishes a stable release; main only |
| version | Required base MAJOR.MINOR.PATCH, without v, whitespace, leading zeros, suffixes or metadata |
| benchmark_packaging / cold_cache | Existing optional booleans, both default false; behavior unchanged |

`backend/version.py` remains authoritative for the **application/EXE version**
(currently 1.2.0). It is not automatically changed by publication.

- **Beta:** explicitly select the desired release target, which may differ from
  the internal application version. The first planned SAP Lens beta uses branch
  work, release_mode beta and version **0.1.0**. With no matching existing
  reservation it produces **v0.1.0-beta-1**, title **SAP Lens v0.1.0-beta-1**,
  and **SAP-Lens-Windows-x64-v0.1.0-beta-1.zip**. The next betas are beta-2,
  beta-3, etc.; changing the target to 0.2.0 starts its own beta-1 sequence.
- **Stable:** the requested version must equal the authoritative application
  version and publication must originate from main. Each component must fit the
  Windows PE 0–65535 range. A different stable version requires a separately
  reviewed source version change; CI never makes version-bump commits.
- **Build:** the existing version match/PE-range checks are unchanged. The form's
  default 1.2.0 is a convenience for build/stable, **not the planned beta target**.
  Explicitly replace it with 0.1.0 when selecting beta. Never substitute the
  application's version for an explicitly selected beta target.

The EXE still internally reports **1.2.0** for the planned 0.1.0 beta. Its identity,
PE metadata and bytes are not rewritten. The independently selected full beta
label appears in the GitHub title, tag, notes and asset names. Notes and the
publication summary also state the actual application/EXE version so the two
cannot be confused. There is no claim that this EXE reports 0.1.0-beta-1, no new
application version constant, and no application UI redesign.

## Version allocation and progression

Beta tags are exactly `vMAJOR.MINOR.PATCH-beta-N`. After the complete Windows job
succeeds, the publication job reads all paginated repository tags and releases,
including drafts. For the exact base version it takes the greatest positive
integer suffix and adds one, starting at 1. Gaps are preserved. Other versions,
leading-zero suffixes and malformed names are ignored. Reserved tags and drafts
also occupy numbers. Sequence numbers are compared numerically, including large
counters.

Stable tags are exactly `vMAJOR.MINOR.PATCH`. Stable requires refs/heads/main,
version equality with the source, no existing tag/release of that name, and a
version greater than all existing stable-version tags/releases. Comparison is
numeric, not lexicographic (1.10.0 is greater than 1.9.0). The source branch must
still point at the exact built commit at publication time; branch movement fails
closed and requires a fresh build. Build mode and beta also require a branch,
not a tag ref.

The repository-wide workflow concurrency group remains
`sap-lens-windows-distribution`, cancel-in-progress false. It covers build and
publication together. GitHub may replace an older pending run when additional
runs queue; it does not cancel the running release. An atomic create-only Git ref
request protects against external publishers racing allocation. A collision
stops; no force update, deletion or automatic collision retry is performed.
Other administrators can still mutate GitHub state outside this workflow; the
publisher rechecks its tag and draft identity before publishing, but GitHub does
not provide a transaction locking all external actors.

## Permission and approval boundaries

The Windows build job retains contents:read/actions:read, the complete existing
canonical PowerShell stages, SHA-pinned actions, caches, benchmarks, smoke tests,
artifact roundtrip and consolidated build report. It does not receive write
credentials. A dependent **Publish Verified Windows Release** job runs only for
beta/stable after the successful Windows job. Only that job gets contents:write
and actions:read. GH_TOKEN is exported only to the publication script; the other
steps in that privileged job are trusted, SHA-pinned official actions. Checkouts
do not persist credentials. No repository secrets or third-party action is needed.

The publisher independently reads this run's first-attempt manual event, source
SHA, artifact origin/digest and mandatory Windows step conclusions. It refuses
missing/skipped/failed checks. It downloads only that job's exact artifact ID as
a raw ZIP with digest mismatch set to error, then checks it again before any write.
PR events and ordinary pushes cannot enter this workflow.

Stable publication references the **sap-lens-stable** GitHub Environment; beta
references **sap-lens-beta**. Stable publishing requires an appropriately protected sap-lens-stable
Environment as an operational prerequisite. Administrators must configure it
before use: required reviewers, prevent self-review where supported, disallow
bypassing protection rules, and selected deployment branches allowing only main.
Optionally protect beta too. Repository plan/policy may affect available rules.
The workflow references these environments but does not configure their settings.
A missing/unprotected environment may be created without approval requirements
by GitHub. **Referencing the name alone does not enforce human approval.** The
main-only and version rules are still enforced in code. Administrators must verify
the actual Environment rules before relying on stable approval protection.

## Publication and assets

After successful build and artifact checks, publication:

1. Chooses a tag and prepares/verifies release assets without executing the EXE.
2. Atomically creates that new lightweight tag at the exact built commit.
3. Creates a **draft** release for that tag/commit, with the correct prerelease flag.
4. Uploads two assets without clobbering existing files.
5. Downloads both uploaded assets again and compares their exact bytes and sizes.
6. Rechecks its draft and reserved tag, then publishes with draft:false.

Beta ends with prerelease:true and does not replace GitHub's latest stable release.
Stable ends with prerelease:false and becomes latest. Titles are `SAP Lens <tag>`.
Notes include release type, UTC build date, full source SHA, Windows platform,
unsigned status, workflow link and EXE/ZIP hashes. Where a previous published
version is known, notes link to its comparison with the source SHA. Commit message
text is not copied into notes, avoiding accidental disclosure of internal details.

For the first planned beta, release assets are:

- `SAP-Lens-Windows-x64-v0.1.0-beta-1.zip`
- `SAP-Lens-Windows-x64-v0.1.0-beta-1.zip.sha256`

Stable uses `v1.2.0` instead. The release ZIP contains exactly `SAP-Lens.exe` and
`SAP-Lens.exe.sha256`. Member order, timestamps, permissions and ZIP storage mode
are fixed, making it deterministic for identical verified inputs. The EXE is
copied without modification or recompression. Both inner EXE and outer ZIP hashes
are verified. No CSVs, user settings, branding overrides, logs or development
files are added. The Windows job still checks PE/resources/privacy and full
frontend/archive contents before and after its normal Actions upload.

The normal Actions artifact remains SAP-Lens-Windows-x64 with 14-day retention.
Its GitHub-generated ZIP hash is distinct from the named deterministic release
ZIP hash; they must not be interchanged. Release publication has its own summary
in addition to the unchanged Windows build report.

To verify a downloaded release in PowerShell:

```powershell
$zip = 'SAP-Lens-Windows-x64-v0.1.0-beta-1.zip'
$expected = ((Get-Content "$zip.sha256" -Raw).Trim() -split '  ', 2)[0]
if ((Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
    throw 'ZIP checksum mismatch'
}
Expand-Archive $zip -DestinationPath '.\SAP-Lens-verified'
$expectedExe = ((Get-Content '.\SAP-Lens-verified\SAP-Lens.exe.sha256' -Raw).Trim() -split '  ', 2)[0]
if ((Get-FileHash '.\SAP-Lens-verified\SAP-Lens.exe' -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedExe) {
    throw 'EXE checksum mismatch'
}
```

Checksums detect byte changes; they are not an Authenticode signature. Signing
remains disabled. Publishing a GitHub Release does not guarantee that corporate
security policies, SmartScreen or Defender permit downloading/running an unsigned
EXE. See [code-signing limitations](WINDOWS_CODE_SIGNING.md).

## Reruns and partial failure recovery

Release-mode workflow reruns (run_attempt greater than 1, including failed-job
reruns) are refused. Build-only reruns are allowed. No published release is ever
updated, reused or silently replaced. For a fresh release attempt, start a new
manual workflow after inspecting the previous run and GitHub state.

A failed build performs no publication. Failure after reservation may leave a tag
and/or draft; failed uploads and failed asset verification leave the draft
unpublished. No automatic deletion, asset replacement or rollback occurs. If the
final publication request is interrupted, GitHub may have published successfully
without a response: inspect its actual state before taking any recovery action.
A timeout during reservation/creation can similarly leave unconfirmed remote
state. The summary lists the allocated tag and any confirmed draft/reservation.

Administrators must review orphaned reservations/drafts manually. Do not simply
publish an incomplete draft. Verify both assets/checksums and provenance first,
or abandon it and start a fresh build. Beta chooses the next available number;
stable refuses any existing target tag/release until an administrator resolves
it under repository policy. This implementation does not delete anything to make
a retry succeed.

## Local verification and remaining boundaries

`backend/tests/test_release_automation.py` uses a fake GitHub client and synthetic
PE/ZIP files. It tests numbering, strict versions/branch rules, stable progression,
races, reruns, build gates, malformed/missing artifacts/checksums, flags, names,
deterministic ZIPs and partial-upload/tampering failure boundaries. No test
creates real Git tags/releases, executes a Windows EXE or makes publication calls.
Workflow contracts preserve trigger, permission, concurrency and artifact rules;
actionlint validates YAML, expressions and job dependencies. Existing PowerShell
scripts are parsed without running the Windows build.

Live GitHub publication, actual Environment review enforcement, draft asset
upload/download authorization and a new native Windows build remain untested in
this task. Existing successful Windows runs validate the preceding version only.
Review this local implementation before authorizing any remote operation.

## Initial automation validation — 2026-10-22

This record describes b1db380 before the beta-version correction. The revised
policy above supersedes its original all-modes version-equality restriction.

Implementation began on work at 98f45db7f4b7db88bf5c44044e1fc9276d4d7600,
with a clean working tree and no divergence from the freshly fetched origin/work.
No existing local work was discarded. Only the Windows workflow, release helper,
workflow contracts/tests and release documentation change.

The final Linux run passed **157 backend tests** (14.770 seconds), including
24 release tests and 13 workflow-contract tests, with deprecations treated as
errors. All **41 browser tests** passed. Existing tests were retained. Full
validation compared the implementation diff before/after execution byte for byte.
No application UI changed, so no new UI visual design review was needed; existing
browser screenshot/theme/layout regressions ran unchanged.

Executed from the repository root, using the prepared Python 3.12 virtualenv,
Node 24, system Chromium and prepared PowerShell 7 tooling:

```sh
git diff --check
.venv/bin/python scripts/ci.py lint
.venv/bin/python scripts/check-workflows.py
# Prepared PowerShell executable; no Windows build execution:
pwsh -NoProfile -File scripts/check-powershell.ps1
npm --prefix frontend ci
node scripts/sync-lucide-catalog.mjs --check
npm --prefix frontend run check:types
npm --prefix frontend run build
.venv/bin/python -W error::DeprecationWarning -m unittest discover -s backend/tests -v
.venv/bin/python -m pip check
# Separate audit-tool virtualenv, inspecting the application virtualenv:
python -m pip_audit --path /workspace/sap-lens/.venv/lib/python3.12/site-packages --progress-spinner off
npm --prefix frontend audit --omit=dev
PLAYWRIGHT_EXECUTABLE_PATH=/usr/bin/chromium PATH="$PWD/.venv/bin:$PATH" npm --prefix frontend run test:browser
npm --prefix frontend audit --json
```

Workflow/actionlint, trigger/permission/job-graph contracts, PowerShell syntax and
static checks, dependency consistency, production build and repository link/input
integrity all passed. Python and production JavaScript audits found no known
vulnerabilities. Full npm audit retained seven development-only advisories (five
high, two moderate); none were suppressed. Environment-only cache ownership,
NO_COLOR/FORCE_COLOR and npm update notices remain visible. No dependencies or
lockfiles changed.

README branding, canonical assets, backend version/runtime, frontend source,
Fast/Full workflows and canonical Windows build/smoke/package-verification scripts
were compared with the baseline and remain unchanged. Native Windows validation,
real GitHub release API transport/permissions and protected Environment enforcement
remain pending. No push, GitHub Actions execution, real Git tag/release or Windows
EXE build was performed by this task. Review locally before remote execution.

## Final beta-target review — 2026-10-22

Review baseline: work at b1db380bbe4d4b63842366aaf6cd8b205534d6a0 with a clean
working tree. Application version was confirmed as 1.2.0. Beta target equality
was corrected: explicit 0.1.0 is accepted without changing the source version,
PE metadata or executable bytes. Build/stable equality and stable main-only rules
are unchanged. Release notes and publication summaries now distinguish the
release label from the internal application/EXE version.

The first planned tag/title are v0.1.0-beta-1 / SAP Lens v0.1.0-beta-1. Read-only
remote inspection returned zero matching 0.1.0 beta tag refs and zero visible
matching releases. Allocation still rechecks all occupied identities at actual
publication time; no version number is reserved by this local review.

The review confirmed contents:read/actions:read for building, with contents:write
and actions:read only in the dependent manual publication job. These are the
permissions needed for tag/release writes and build/artifact metadata reads;
repository rules or organizational policy may still block actual publication.
No new permissions, secrets, triggers, automatic releases or environment settings
were introduced. Reading sap-lens-stable returned HTTP 404, so this review cannot
confirm an existing protected Environment. An administrator must verify/create
its approval and main-only deployment rules before stable use. No human approval
enforcement is claimed based solely on its workflow name.

The exact command suite recorded above was rerun against the corrected source:
**160 backend tests passed** (4.167 seconds), including **27 release tests**;
**41 browser tests passed** (1.1 minutes). actionlint, workflow trigger/permission/
concurrency/job-graph contracts, PowerShell parsing/static guards, clean npm
installation, TypeScript checks, production build, icon catalog, dependency
consistency, production audits and repository integrity all passed. Python and
production JavaScript audits found no known vulnerabilities. No dependencies
changed; existing development-only advisories remain outside the production
audit. Local pip-cache ownership and npm/terminal-environment notices remain
visible, without warning suppression.

New synthetic tests cover explicit 0.1.0 with internal 1.2.0, no matching tags,
beta-1 to beta-2, gaps through beta-3 to beta-4, other base versions, restart at
0.2.0-beta-1, unchanged old tags/releases, exact asset names, prerelease flags,
unchanged EXE/checksum bytes, and stable/build mismatch rejection. Existing tests
continue to cover failed builds, atomic reservation collisions, reruns, draft
staging, upload/download tampering and missing files/checksums. The ZIP contains
exactly the EXE and its manifest; the separately uploaded ZIP checksum covers the
unchanged verified download. All GitHub mutations in tests use a fake client.

The implementation diff was frozen for full validation and compared unchanged
at completion (SHA-256, excluding documentation):
`38ce0afb293448cc14b89936a6ccc1c27252113a0150abd7a41092fa0ad1eb03`.
README/assets, internal version/runtime/frontend, Fast/Full workflows and
canonical Windows build/smoke/package-verification scripts remain unchanged.
Native Windows validation and live publication permissions/transport remain
pending; no real Windows EXE, Git tag/release, workflow execution, push or
repository-setting change was made. Stop at local review until explicitly
approved otherwise.
