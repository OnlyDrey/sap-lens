# Versioning and release identity (SAP Lens .NET, 2.x)

SAP Lens 2 (the .NET Server and Desktop) has its own product version, independent of SAP Lens v1. Decision of 2026-11-16: SAP Lens 2 is the
next major version of the product in pre-release, so it uses its own `2.0.0-alpha.N` line instead of sharing v1's version or keeping the
former placeholder `0.0.0-experiment`.

**Name (2026-11-17):** the product is branded **SAP Lens** everywhere a person sees it (assembly product, `--version`, window title, installers,
OpenAPI title); the version alone says it is the 2.x line. Executables: `SapLens.exe` (Desktop), `SapLens.Api.exe` (Server); installers
`SAP-Lens-<version>-Setup.exe` and `SAP-Lens-Server-<version>-Setup.exe`; service `SapLens`. Identifiers that existing data or installations depend on
keep their earlier value: the backup archive's manifest product and key-derivation label (`SAP Lens 2 ...`), the `SapLens2` service until it is
migrated ([WINDOWS_DEPLOYMENT.md](../deployment/WINDOWS_DEPLOYMENT.md#migrating-saplens2-to-saplens)), the `SAP Lens 2 Prototype` Desktop folder when it exists,
and the `SAPLENS2_DEPLOY_CONFIG` variable (still read).

## Three different things

| Concept | Example | Source | Changes |
| --- | --- | --- | --- |
| Product version | `2.0.0-alpha.1` | `experiments/dotnet-backend/product-version.json` (only source) | Only by an explicit, approved edit; never by a build |
| Channel | `alpha` (then `beta`, `rc`, stable) | The pre-release label of the product version | With the product version |
| Build identity | commit `2e24a23…`, build time `2026-11-16T18:12:48Z`, SHA-256 per file | The release scripts (`-p:SourceRevisionId`, `build-manifest.json`) | Every build |

Format: `MAJOR.MINOR.PATCH` or `MAJOR.MINOR.PATCH-alpha.N|-beta.N|-rc.N` (each number 0 to 99999, N from 1). Anything else stops the build.
The Windows file version follows the v1 contract: `MAJOR.MINOR.PATCH.N` with the pre-release number N, and 0 for a stable release
(`2.0.0-alpha.1` → `2.0.0.1`).

## Where it appears

| Place | Value |
| --- | --- |
| Assemblies (Server, Desktop and all libraries; `Directory.Build.props`) | `AssemblyInformationalVersion` `2.0.0-alpha.1+<commit>`, `FileVersion` `2.0.0.1`, `AssemblyVersion` `2.0.0.0`, product `SAP Lens` |
| `SapLens.Api --version` | `SAP Lens server 2.0.0-alpha.1`, then channel, commit (or "not recorded (local build)"), file version and runtime |
| `GET /api/version`, `/api/application-info`, `/api/diagnostics` | `version` = product version; application-info also `channel`, `file_version`, `source_sha` |
| `GET /product-version.json` | The .NET host's identity (`product`, `version`, `base_version`, `channel`, `file_version`, `source_sha`). The file the React build emits carries v1's identity and is not served by the .NET host |
| Desktop log | `Desktop starting (SAP Lens 2.0.0-alpha.1, commit …, file version 2.0.0.1, …)` |
| Release folder | `SAP-Lens-2.0.0-alpha.1-<UTC time>-<commit>-win-x64` |
| `build-manifest.json` | `product`, `version`, `channel`, `file_version`, `ui_source_version` (v1's version the embedded UI was built with, recorded only), `source_sha`, `source_dirty`, build time |

## SAP Lens v1 is unchanged

v1 keeps `backend/resources/product-version.json` (`1.0.0-beta.2` at this time), its CI-generated build identity
(`backend/build/build-version.json`) and the mirror in `frontend/package.json` (`scripts/product-version.mjs`). The React sources are shared, so the
UI bundle is built with v1's version; the .NET host reports its own version wherever the UI asks the backend (`/api/version`,
`/api/application-info`). Changing v1's version follows v1's release process, not this document.

## Release policy

- A build never changes the product version. Local and release builds differ only in build identity.
- To move to the next pre-release (`2.0.0-alpha.2`) or channel (`2.0.0-beta.1`), edit `product-version.json` in a commit of its own, with approval,
  before building the release that carries it.
- Releases are built locally (`scripts/build-release.ps1` or `.sh`); no workflow is triggered. Verify a release with `verify-release.ps1`, which
  also checks that the folder name and file version follow from the manifest's version.

## Tests

`VersioningTests` (the file is the only source, assemblies and file version follow it, `--version` content, every HTTP identity equal, v1
independence and v1's own mirror, release scripts read the file and check `<version>+<commit>` in every executable); Pester `Release verification`
(folder name, file version and version format); the release scripts refuse an invalid version and executables without `<version>+<commit>`.
