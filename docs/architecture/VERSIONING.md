# Versioning and release identity (AuthLens .NET, 2.x)

AuthLens (the .NET Server and Desktop) has its own product version, independent of SAP Lens v1. Decision of 2026-11-16: the .NET implementation is the
next major version of the product in pre-release, so it uses its own `2.0.0-alpha.N` line instead of sharing v1's version or keeping the
former placeholder `0.0.0-experiment`.

**Name (2026-11-19): AuthLens.** The product, previously named SAP Lens, is **AuthLens** everywhere a person sees it (assembly product,
`--version`, window title, installers, OpenAPI title, reports and export file names). The product version stays `2.0.0-alpha.1`; the repository
keeps its name `sap-lens`. Executables: `AuthLens.Api.exe` (Server), `AuthLens.exe` (Desktop); installers `AuthLens-<version>-Setup.exe` and
`AuthLens-Server-<version>-Setup.exe` (new AppIds: they install beside SAP Lens, never over it); release folders `AuthLens-<version>-<UTC>-<commit>-<platform>`.
Implemented; Linux and Windows automated results and remaining native acceptance gates are tracked separately ([release status](../migration/RELEASE_STATUS.md)).

## Naming register

**Canonical identities:** product and display name AuthLens; Windows service `AuthLens` (account `NT SERVICE\AuthLens`); installation root
`C:\ProgramData\AuthLens` ([layout](../deployment/WINDOWS_DEPLOYMENT.md#installation-layout)); database `authlens.sqlite3`; Desktop folder
`%LOCALAPPDATA%\AuthLens` (mutex `Local\AuthLensDesktop`); .NET projects and namespaces `AuthLens.*`; PowerShell module `AuthLens.Deploy`
(functions `*-AL*`); configuration `AUTHLENS_*` environment variables, `AUTHLENS_DEPLOY_CONFIG`, `AUTHLENS_TEST_CONFIG`, `AUTHLENS_BACKUP_PASSPHRASE`.

**Configuration contract:** the server reads only `AUTHLENS_*`. `SAP_LENS_*` (SAP Lens and SAP Lens 1) and `SAP_LENS_V2_*` (earlier .NET builds)
are never read and do not stop the server: it prints a warning naming each with its AuthLens name, because AuthLens may run beside SAP Lens during
acceptance. Deployment configuration is read only from `-ConfigFile`, `AUTHLENS_DEPLOY_CONFIG` or `C:\ProgramData\AuthLens\config\deploy.json`.

**No adoption of earlier installations:** AuthLens never detects, adopts, stops or changes a SAP Lens service (`sap-lens`, `SapLens`, `SapLens2`),
data directory or Desktop folder. Their data comes to AuthLens through a backup restore ([migration](../deployment/WINDOWS_DEPLOYMENT.md#migrating-from-sap-lens))
or the explicit `--adopt-legacy-database` conversion of one data directory.

Identifiers that keep an earlier name on purpose:

| Identifier | Where | Class | Why it stays | Removal condition |
| --- | --- | --- | --- | --- |
| Archive entry `sap-lens-v2.sqlite3`, manifest products `SAP Lens 2` and `SAP Lens` (accepted, never written) | `ApplicationBackups` | Compatibility (input) | SAP Lens backups carry them; they restore to `authlens.sqlite3` | When no SAP Lens backup needs restoring |
| Database file `sap-lens-v2.sqlite3` (recognised, never opened implicitly) | `DatabaseOptions.RefuseUnadoptedLegacy`, `--adopt-legacy-database` | Compatibility (input) | A SAP Lens data directory is refused rather than hidden behind a new empty database | Same |
| HKDF labels `SAP Lens 2 portable archive v3` and `SAP Lens portable archive v2` | `BackupCrypto` | Persisted (crypto) | Changing them makes every existing encrypted archive undecryptable | Never for these formats; a future format uses its own label |
| `SAP Lens configuration` export format (accepted, never written) | `V1Configuration` import | Compatibility (input) | Configuration exports made by SAP Lens | When no such export needs importing |
| `X-SAP-Lens-*` HTTP headers, `sap-lens-session`/`sap-lens-csrf` cookies, `sap-lens-*` browser storage keys and in-page events | API, frontend | API contract | The token header is used by API clients; renaming the rest gains nothing and signs users out or drops remembered settings | A versioned API change |
| `saplens_session`/`__Host-saplens_session` server session cookies | `Security.cs` | API contract | Renaming signs every user out | A deliberate breaking release |
| `"app": "sap-lens"` in the refresh status, other v1 API field values | v1-compatible API | API contract | The frontend and v1 clients read the v1 contract | With the v1 API |
| Product, folder and manifest names `SAP Lens`, `SAP-Lens-*`, `SAP-Lens-2-*` (accepted, never written) | `verify-release.ps1` | Compatibility (input) | Verifying releases built before the rename | When no such release is verified |
| `SAP_LENS_V1_BACKEND` | `backend/tools` | Historical | Points the reference generators at a SAP Lens 1 checkout | With the v1 reference tools |
| Branding filenames | Assets | Visual identity | Generic sources in `assets/branding/`; original images unchanged; no legacy filename compatibility needed | See [branding ownership](DESIGN_SYSTEM.md#branding-source-assets) |
| `.gitignore` patterns `*.sap-lens.json`, `SAP-Lens-diagnostics*.json` (beside the AuthLens ones) | `.gitignore` | Safety guard | Exports made by SAP Lens must stay out of Git too | Never |
| Earlier products' folders and service names in the test launcher's protected paths | `start-server-test.ps1` | Safety guard | A test run must never write into any production or Desktop location | Never |

Removed with the rename (2026-11-19): the `SapLens2` to `sap-lens` service migration and its configuration planner, detection of earlier
service names, `SAPLENS_DEPLOY_CONFIG`/`SAPLENS2_DEPLOY_CONFIG` and the `C:\sap-lens`/`C:\saplens2` configuration lookups, deployment of
commits that predate AuthLens, the prototype Desktop folder fallback, and the `SAP_LENS_V2_*` startup refusal.

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
| Assemblies (Server, Desktop and all libraries; `Directory.Build.props`) | `AssemblyInformationalVersion` `2.0.0-alpha.1+<commit>`, `FileVersion` `2.0.0.1`, `AssemblyVersion` `2.0.0.0`, product `AuthLens` |
| `AuthLens.Api --version` | `AuthLens server 2.0.0-alpha.1`, then channel, commit (or "not recorded (local build)"), file version and runtime |
| `GET /api/version`, `/api/application-info`, `/api/diagnostics` | `version` = product version; application-info also `channel`, `file_version`, `source_sha` |
| `GET /product-version.json` | The .NET host's identity (`product`, `version`, `base_version`, `channel`, `file_version`, `source_sha`). The React build emits the same canonical product/version and commit; the host serves its runtime identity at this path |
| Desktop log | `Desktop starting (AuthLens 2.0.0-alpha.1, commit …, file version 2.0.0.1, …)` |
| Release folder | `AuthLens-2.0.0-alpha.1-<UTC time>-<commit>-win-x64` |
| `build-manifest.json` | `product`, `version`, `channel`, `file_version`, `ui_source_version` (the canonical product version used by the embedded UI), `source_sha`, `source_dirty`, build time |

## Historical SAP Lens versions

SAP Lens 1 and its version resources are archived outside this repository. Active frontend builds use `backend/product-version.json`, not an archived v1 resource. Historical backup product labels, cryptographic identifiers and schema migration IDs remain unchanged for compatibility; they do not control the current product version.

## Release policy

- A build never changes the product version. Local and release builds differ only in build identity.
- To move to the next pre-release (`2.0.0-alpha.2`) or channel (`2.0.0-beta.1`), edit `product-version.json` in a commit of its own, with approval,
  before building the release that carries it.
- Releases are built locally (`scripts/build-release.ps1` or `.sh`); no workflow is triggered. Verify a release with `verify-release.ps1`, which
  also checks that the folder name and file version follow from the manifest's version.

## Tests

`VersioningTests` (the file is the only source, assemblies and file version follow it, `--version` content, every HTTP identity equal, canonical frontend mirrors and historical-data independence, release scripts read the file and check `<version>+<commit>` in every executable); Pester `Release verification`
(folder name, file version and version format); the release scripts refuse an invalid version and executables without `<version>+<commit>`.

## Active frontend and build metadata

`backend/product-version.json` also controls the React package and lockfile root
versions. `node scripts/product-version.mjs` checks them; `--write` explicitly
synchronizes mirrors without changing the source. Vite emits `product-version.json`
with that version and the source commit. CI refuses a mismatched GitHub commit.
Release manifests record the same UI source version. Historical v1 version metadata was
archived with SAP Lens 1 and is never consulted by an active build.
