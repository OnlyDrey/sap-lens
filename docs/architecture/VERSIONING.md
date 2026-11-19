# Versioning and release identity (SAP Lens .NET, 2.x)

SAP Lens (the .NET Server and Desktop) has its own product version, independent of SAP Lens v1. Decision of 2026-11-16: the .NET implementation is the
next major version of the product in pre-release, so it uses its own `2.0.0-alpha.N` line instead of sharing v1's version or keeping the
former placeholder `0.0.0-experiment`.

**Name (2026-11-17):** the product is branded **SAP Lens** everywhere a person sees it (assembly product, `--version`, window title, installers,
OpenAPI title); the version alone says it is the 2.x line. Executables: `SapLens.exe` (Desktop), `SapLens.Api.exe` (Server); installers
`SAP-Lens-<version>-Setup.exe` and `SAP-Lens-Server-<version>-Setup.exe`; service `SapLens`. Identifiers that existing data or installations depend on
keep their earlier value: the backup archive's manifest product and key-derivation label (`SAP Lens 2 ...`), the `SapLens2` service until it is
migrated ([WINDOWS_DEPLOYMENT.md](../deployment/WINDOWS_DEPLOYMENT.md#migrating-saplens2-to-saplens)), the `SAP Lens 2 Prototype` Desktop folder when it exists,
and the `SAPLENS2_DEPLOY_CONFIG` variable (still read). The full list is the naming register below.

## Naming register

Canonical names: product and display name **SAP Lens**; environment variables `SAP_LENS_*` (Server) and `SAPLENS_*_CONFIG` (operator scripts);
Windows service `SapLens`; installation `C:\sap-lens`; service data `C:\ProgramData\SapLens`. There is no second naming scheme and no permanent alias.

**Environment variables renamed (2026-11-18, configuration contract):** the Server's `SAP_LENS_V2_*` variables are now `SAP_LENS_*` (for example
`SAP_LENS_DATA_DIR`, `SAP_LENS_NETWORK`, `SAP_LENS_BACKUP_KEY_FILE`). The old names are not read. A Server that still finds a `SAP_LENS_V2_*`
variable refuses to start (exit code 3) and names each replacement, so a renamed setting is never silently ignored. SAP Lens 1 used some of the
same `SAP_LENS_*` names (`SAP_LENS_DATA_DIR`, `SAP_LENS_PORT`, `SAP_LENS_BACKUP_KEY_FILE`): on a host that still has SAP Lens 1 variables set at
machine level, remove or scope them before starting the .NET Server, because it now reads them. The test launcher's `SAPLENS2_TEST_CONFIG` is
now `SAPLENS_TEST_CONFIG` (its earlier `C:\saplens2` defaults are gone; pass `-ConfigFile` for an old file).

Identifiers that keep a `2` or `V2`, each with its reason and the condition for removal:

| Identifier | Where | Class | Why it stays | Removal condition |
| --- | --- | --- | --- | --- |
| `sap-lens-v2.sqlite3` database file, `sap-lens-v2-<kind>-<time>.sqlite3` database backups | `DatabaseOptions`, `DatabaseMaintenance`, backup archive entry | Persisted | Every existing data directory and archive holds this name; renaming needs a migration step of its own | A schema migration that renames the file with rollback, plus archive import of both names |
| Archive manifest product `SAP Lens 2` | `ApplicationBackups.ManifestProduct` | Persisted (format id) | Every existing `.slbak` declares it; restore validates it | A new archive format version that accepts both |
| HKDF label `SAP Lens 2 portable archive v3` | `BackupCrypto` | Persisted (crypto) | Changing it makes every existing encrypted archive undecryptable | Never for SLBAK3; a future format uses its own label |
| Service `SapLens2`, account `NT SERVICE\SapLens2`, Inno Setup fallback `Result[1] := 'SapLens2'` | Deployment module, migration, Server installer | Migration-only | Detects and migrates hosts installed before the rename; never created for a new installation | All supported hosts migrated (`MigrateService`) and owner confirmation |
| `SAPLENS2_DEPLOY_CONFIG`, `C:\saplens2\deploy.local.json` | Deployment module lookup | Migration-only | The existing Windows host's operator configuration | Same as the service |
| `Deploy-SapLens2.ps1`, `SAPLENS2-RESULT`, `experiments/dotnet-backend` project lookup | `deploy-windows.sh` | Historical | Deploying or rolling back to a commit from before the rename runs that commit's own script | When rollback to pre-rename commits is no longer supported |
| `SAP Lens 2 Prototype` folder, `Local\SapLens2Prototype` mutex | `DesktopLocation`, Desktop installer | Migration-only | Existing Desktop data from prototype builds is kept and used in place | When no prototype data folder remains in use |
| `%ProgramData%\SapLens2`, `SAP Lens 2 Prototype` in the test launcher's protected paths | `start-server-test.ps1` | Safety guard | A test run must never write into an earlier production or Desktop location | With the service and Desktop entries above |
| Manifest product `SAP Lens 2`, `desktop/SapLens2Prototype.exe` (accepted, never written) | `verify-release.ps1` | Historical | The migration preflight verifies the release an existing service runs; releases built before the rename carry these values | When no supported host runs a release built before the rename |
| `SAP_LENS_V2_BACKUP_KEY_FILE` (detection only) | `SapLens.Migration.ps1` | Migration-only | Finds the backup key of a host configured before the rename | With the service |

Product-facing text, code comments, test names and documentation examples use only the canonical names; `scripts/check-structure.py` and the
startup guard keep the old environment prefix from returning.

## Three different things

| Concept | Example | Source | Changes |
| --- | --- | --- | --- |
| Product version | `2.0.0-alpha.1` | `backend/product-version.json` (only source) | Only by an explicit, approved edit; never by a build |
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

## Active frontend and build metadata

`backend/product-version.json` also controls the React package and lockfile root
versions. `node scripts/product-version.mjs` checks them; `--write` explicitly
synchronizes mirrors without changing the source. Vite emits `product-version.json`
with that version and the source commit. CI refuses a mismatched GitHub commit.
Release manifests record the same UI source version. Historical v1 version metadata was
archived with SAP Lens 1 and is never consulted by an active build.
