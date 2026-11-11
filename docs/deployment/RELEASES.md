# Product versions and releases

## Authoritative version and branch policy

`backend/resources/product-version.json` is the single product version source.
Frontend package.json and package-lock.json are generated mirrors; run
`node scripts/product-version.mjs --write` after intentionally advancing a development
cycle or promoting a stable version, and `node scripts/product-version.mjs` to check them.
Ordinary development pushes do not bump versions. Internal npm package names stay compatible.

Source checkouts use this version in the backend and About screen. Stale ignored build
metadata from another checkout commit is ignored only in local development; frozen packages
still require strict embedded identity. CI allocates one immutable build identity for the exact
source commit, stamps frontend manifest mirrors before building, and embeds that same identity
in frontend `product-version.json`, backend, PE resources, installers, archives and release
manifests. Local package overrides remain explicitly unofficial. All source/runtime resource
paths are included by the canonical Windows, native Linux and Docker packaging scripts.

- `work`: prerelease publication (Alpha/Beta/RC); never stable packages/publication.
- `main`: stable publication only after the product resource is a stable version.
- Feature branches: build-only prereleases; no official publication.

The stdlib planning job rejects invalid branch/type/base/sequence/collisions before expensive
jobs. It reads paginated tags and releases (including drafts), resolves `auto` once, and passes
the result to every package job. Both `beta-N` and `beta.N` occupy the same numeric sequence;
new deployment packages use dotted SemVer, while the legacy desktop workflow keeps its
existing hyphen style. Existing tags and releases are never renamed. Manual publication
numbers must equal the next available sequence. Publication rechecks the branch's exact
commit and all selected verified artifacts/checksums; partial success cannot publish.

## Stable promotion (manual, future operation)

1. Review/validate the chosen work commit and promote it through the existing PR process.
2. On the reviewed main promotion, change product metadata to the stable version and regenerate
   manifest mirrors; validate that main commit. No workflow automatically merges branches.
3. Dispatch the stable packaging workflow from that exact main commit. It must still be main's
   head when publishing; source drift requires a new validated build.
4. Required package/build/security validation and checksum roundtrips must succeed. The deployment
   publisher creates its owned tag only after assets are verified. The legacy desktop workflow
   retains its prebuild tag reservation, never publishing a failed/unvalidated build.
5. Publish only through the explicit manual publication input/protected environment. FULL
   regression remains a separate manual operation, not an automatic package prerequisite.

GitHub Releases is the release-history record. This development task creates no tag/release
and changes no main/default-branch or repository protection settings.

## Legacy desktop details (examples use an illustrative base)


For multi-platform Alpha/Beta/RC/Stable channels and optional publication, use
[Build — manual workflow](../BUILD.md#manual-build). This document describes the
separate legacy Windows Application workflow; its beta-hyphen allocation rules
do not apply to deployment packaging. GitHub Releases is the release-history record.

The manually dispatched **Build Windows Application** workflow owns the packaged
version. Fast Validation still runs on every push/PR; Full Validation still runs
only for PRs targeting main. Neither tags nor releases start another Windows build.
No signing, SAP processing or user-configuration behavior changes.

## Legacy desktop inputs and resolved identity

Choose a source branch, release_mode (build by default, beta or stable), and a
strict MAJOR.MINOR.PATCH base version without v, leading zeros or suffixes. An empty base input derives the product resource. Existing benchmark_packaging and cold_cache inputs remain
false by default and retain their behavior. The selected branch must contain
this reviewed workflow and scripts; stable requires merging them into main.
GitHub's dispatch form may still reflect the default branch's older definition
until it is updated through normal review.

| Mode | Base input | Resolved application/ProductVersion | Tag |
| --- | --- | --- | --- |
| build, run 123, attempt 1 | 0.1.0 | 0.1.0-dev.123 | none |
| build, run 123, attempt 2 | 0.1.0 | 0.1.0-dev.123.2 | none |
| beta, first sequence | 0.1.0 | 0.1.0-beta-1 | v0.1.0-beta-1 |
| beta, next sequence | 0.1.0 | 0.1.0-beta-2 | v0.1.0-beta-2 |
| stable | 0.1.0 | 0.1.0 | v0.1.0 |

Run number and attempt give build-only runs distinct full versions within this
workflow. Beta takes the highest valid positive matching beta suffix plus one,
starting at 1. Gaps remain; unrelated bases and malformed suffixes are ignored.
Reserved tags and draft releases also occupy numbers. Changing base to 0.2.0
starts its own beta-1 sequence. Stable requires main and a version greater than
all existing stable tags/releases; the selected source product resource must have the same base. Stable metadata must be promoted on main before publishing.
All base components must fit Windows' 0–65535 numeric range.

Historical beta reservations remain occupied even after failed builds. Inspect
actual remote tags/releases before dispatch; never reuse a reserved number blindly.

## One generated metadata source

The workflow creates ignored `backend/build/build-version.json`; tracked source
files are never rewritten and no version-bump commit is made. Its strict schema
contains only the base/full versions, numeric FileVersion, channel/mode, source
SHA, run ID/number/attempt and derived tag. No secrets, paths, runner configuration,
user names or SAP data enter it. Unexpected fields or inconsistent identities fail.

`backend/version.py` supplies shared validation and reads this file in a source
build. PyInstaller includes it once as `build-version.json` at the resource root.
In the frozen application it is required and loaded from sys._MEIPASS. Missing,
invalid or oversized packaged metadata fails closed; runtime CI variables are
neither needed nor read. The version remains available offline after EXE replacement.

With no generated identity, source development uses the authoritative product
version from `backend/resources/product-version.json`. Frontend manifests mirror
that resource; they are not independent version sources. The unified build CLI
passes the resolved version to canonical compilers. Portable local artifacts use
`<requested-version>+local.<source-SHA-prefix>` without a fabricated CI run;
CI keeps its existing resolved same-run identity. See the [build guide](../BUILD.md).

The existing health/OpenAPI version and authenticated `/api/version` use this
same runtime value. The existing footer shows SAP Lens v<version>, with a
Development build label for build/local modes. No settings page is added. The
version API returns only application name, full version and mode, preserving
loopback/session/origin/no-store protections.

## Allocation, jobs and permissions

All jobs remain in the existing repository-wide
sap-lens-windows-distribution concurrency group, cancel-in-progress false.

1. **Reserve Release Version** runs only for beta/stable. It checks inputs,
   branch, source commit, progression and first-attempt policy, reads paginated
   tags/releases, resolves the full identity and atomically creates a new
   lightweight tag at the source SHA. It returns that fixed metadata as a job
   output. It has contents:write, without actions:write or extra secrets.
2. **Windows Build & Verification** retains contents:read/actions:read. It may
   start only after successful reservation, or after the deliberately skipped
   reservation in build mode. It writes the allocated identity (or resolves a
   build-only identity), freezes it in an expected-value environment record, and
   runs every existing install/build/audit/test/package/verification/smoke stage.
   Package preparation and verification reject metadata changed after resolution.
3. **Publish Verified Windows Release** retains contents:write/actions:read,
   runs only after a successful release-mode Windows job, and consumes the exact
   metadata and artifact ID/digest from that job. It verifies run/artifact
   provenance and all mandatory build conclusions. **It does not allocate a beta
   number, create another tag or rename/rebuild the already packaged EXE.**

Only allocation/publication jobs receive write permission. The build runner never
receives a write token. Official actions remain SHA-pinned and checkout credentials
are not persisted. No privileged PR execution or automatic publishing is added.
Additional allocation-job startup is intentional to keep packaging read-only;
no updated runner performance measurements are claimed.

Workflow concurrency serializes this implementation's runs. GitHub may replace
an older pending run when more runs queue, but does not cancel an active build.
Atomic create-only ref reservation handles external publishers racing the list
operation: collision stops the run, without overwrite or automatic reallocation.
If a higher beta appears after our reservation, our reserved version stays fixed.
Before publication, its tag must still point at the source commit; the branch
must not have advanced, and no release of that tag may already exist. Stable
progression is checked again excluding its own reserved tag. External administrator
changes cannot be transactionally locked by this workflow; state is rechecked.

## Environments and approval

Allocation and publication reference sap-lens-stable for stable and sap-lens-beta
for beta. Administrators must configure stable's required reviewers, self-review/
bypass restrictions where supported, and main-only deployment branches before
relying on approval enforcement. Both privileged jobs can require approval;
GitHub may request a second approval at publication after the build.

Deployment publication of Stable / Production is also refused in code unless the workflow runs on `main` (checked by the plan job, so
no runner is spent, and again before publishing); the other channels may be published from any branch.

The workflow only references environments; it does not configure settings.
A missing/unprotected environment can be created by GitHub without review rules.
The name alone therefore does not enforce approval. Main-only/version rules are
still enforced by code. Repository rules/token policies can independently block
tag or release writes. No repository settings are changed by this implementation.

## PE resources and consistency checks

`packaging/write-windows-metadata.py` uses the generated identity for ProductVersion and
numeric resources; ProductName/FileDescription are SAP Lens. For 0.1.0-beta-1,
ProductVersion is 0.1.0-beta-1 and FileVersion is 0.1.0.1; stable is 0.1.0 / 0.1.0.0.
Fixed numeric product/file versions both use the same four-number tuple.

Windows PE has four 16-bit components, so beta sequence N must be 1–65535; overflow
fails **before reserving a tag** and requires a new reviewed base version.
Development builds use the upper half of the fourth component, derived from run
number/attempt modulo the available range. Numeric development versions can
repeat over long histories or overlap very large beta sequences. The full
ProductVersion/API/UI version remains the authoritative distinct identity;
Windows numeric fields cannot encode an unbounded run history. Stable's zero
fourth component is separate from beta/dev revisions.

Package verification compares embedded JSON with the frozen workflow identity,
PE ProductVersion/FileVersion and the complete production frontend, checks that
the runtime version module is included, and preserves every existing privacy,
icon, manifest, x64/GUI, nested archive and secret guard. The native smoke test
also compares /health's runtime version and both Windows version strings with
the expected identity, alongside first launch/restart/port conflict/shutdown.

## Artifacts, publication and recovery

The normal Actions artifact remains SAP-Lens-Windows-x64, containing only EXE and
its EXE checksum, compression level zero and 14-day retention. Its downloaded raw
ZIP digest, exact two-file membership and EXE/package contents are still verified
on Windows. Generated build metadata is inside the EXE, not a third ZIP member.

Publication downloads/rechecks that exact artifact, uses the **already reserved**
tag, and creates a new draft release for the same SHA/full version. It uploads:

- SAP-Lens-Windows-x64-v0.1.0-beta-1.zip
- SAP-Lens-Windows-x64-v0.1.0-beta-1.zip.sha256

Stable uses its stable tag. Each release ZIP contains exactly SAP-Lens.exe and
SAP-Lens.exe.sha256. Ordering, timestamps, permissions and ZIP storage mode are
fixed for reproducible identical inputs. EXE bytes are not changed/recompressed.
Both uploaded release assets are downloaded again and compared byte for byte
before draft:false is set. Beta uses prerelease:true; stable uses false. Titles,
notes, ZIP names, embedded version and UI/API all use the same resolved version.
Notes include source SHA, UTC date, platform, hashes, workflow link and a valid
previous-release comparison where available, without copying internal commit text.
The normal GitHub artifact ZIP hash and deterministic release ZIP hash cover
different archives and must not be interchanged.

A failed build may now leave its **early reserved tag**, but never publishes a
release. Failed publication can leave the reservation/draft. No automatic tag,
release or asset deletion/replacement is performed. A new beta run skips reserved
numbers. Stable refuses an occupied target until an administrator resolves it
under repository policy. Release-mode reruns (attempt >1), including failed-job
reruns, are refused; build-only reruns get a distinct dev version. Do not manually
retag/relabel a built EXE to recover. A failed/interrupted final API request can
leave publication unconfirmed: inspect GitHub state before any recovery action.
Timeouts during reservation can likewise leave a tag without confirmed outputs.

Signing remains disabled. Checksums are not Authenticode signatures, and publishing
an unsigned release does not guarantee corporate policies, SmartScreen or Defender
will allow downloading or executing it. See [signing](CODE_SIGNING.md),
[deployment validation status](README.md#validation-status) and [CI architecture](../development/CI.md).


## Final artifact location

Local deployment builders, trusted remote retrieval and guarded CI publication
collect final packages under root `dist/<version>-<commit12>/`. The existing public
package names and release assets are unchanged. `release-manifest.json` is local
collection evidence with platform/version/full source SHA and SHA-256 per artifact;
the existing public release manifest remains the publication contract. CI
`dist/deployment` and `dist/publication` directories are staging locations.
Legacy Windows publication now defaults to the same version/commit directory,
while retaining an explicit output override. Existing releases/tags are untouched.
See [build outputs and checksum verification](../BUILD.md#outputs-and-versioning).
