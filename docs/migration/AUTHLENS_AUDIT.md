# AuthLens rename and consolidation audit (2026-11-20)

Record of the repository-wide audit and the rename from SAP Lens to AuthLens. Baseline: commit `814c88d` (before the rename). The canonical
rules that came out of it live in the [naming register](../architecture/VERSIONING.md#naming-register), the
[installation layout](../deployment/WINDOWS_DEPLOYMENT.md#installation-layout) and
[migrating from SAP Lens](../deployment/WINDOWS_DEPLOYMENT.md#migrating-from-sap-lens); this file is the audit trail, not a procedure.

The per-file inventory is [authlens-inventory.json](authlens-inventory.json): every tracked file at the baseline and now, with status
(unchanged, changed, renamed with its previous path, added, removed), the naming references before and after, and for each remaining
reference a classification and reason.

## 1. Scope and method

- **Inspected:** all 922 tracked files of the baseline (code, scripts, tests, installers, workflows, docs, fixtures, examples, assets). Each was
  searched for `SAP Lens`, `SapLens`, `sap-lens`, `SAP_LENS`, `saplens`; binaries were listed by name only.
- **Not a global replace:** names were changed per category (identifiers, product text, file names, environment variables, paths), each with
  exclusions for persisted, cryptographic, API-contract and historical identifiers. Every exclusion is listed in the naming register.
- **Result at the end of the work** (including the inventory file): 917 tracked files: 366 unchanged, 359 renamed, 181 changed in place,
  11 added; 16 removed. 237 files still contain an earlier name; all of them are classified below. Only `LICENSE.md` needs an owner decision.

## 2. Remaining earlier names by class

| Class | Files | Why they stay |
| --- | --- | --- |
| Compatibility | 57 | Read SAP Lens backups, configuration exports, release folders and manifests; refuse or adopt `sap-lens-v2.sqlite3`; leave earlier services and folders untouched; warn about `SAP_LENS_*`; keep browser storage keys, cookies and `X-SAP-Lens-*` headers |
| Historical | 54 | Dated migration records, ported SAP Lens 1 behaviour, deployment text that names earlier services in order to never touch them |
| Test | 51 | Assert the compatibility above, or rename v1 reference text through `ProductRename` |
| Documentation | 31 | Name the earlier product, the repository `sap-lens`, or the migration path |
| Tooling | 33 | `backend/tools` regenerate v1 fixtures from an external SAP Lens 1 checkout (`SAP_LENS_V1_BACKEND`) and set the `SAP_LENS_*` variables SAP Lens 1 reads |
| Fixture | 6 | Recorded v1 evidence; regenerated, never edited by hand |
| Asset | 4 | Logo and icon file names (`assets/sap-lens.ico`, `sap-lens.png`); the logo is unchanged by request |
| Owner decision | 1 | `LICENSE.md` names the product in legal text; AGENTS.md keeps licensing intact, so the owner changes it |

## 3. Implemented changes

| Commit | Change |
| --- | --- |
| `b76517d` | Projects, namespaces, solution and executables `AuthLens.*` (`AuthLens.Api.exe`, `AuthLens.exe`); deployment module and scripts `AuthLens.*`; installer scripts |
| `45b3875` | Product text AuthLens (UI, reports, OpenAPI, installers, `--version`); export file names `authlens-*`; `AUTHLENS_*` environment variables (old names warn); release folders `AuthLens-*`; new installer AppIds; `verify-release.ps1` still accepts earlier products |
| `44f6ea7` | Database `authlens.sqlite3`; a directory with only `sap-lens-v2.sqlite3` is refused; explicit `--adopt-legacy-database`; backups write `authlens.sqlite3`/product AuthLens and restore SAP Lens archives; offline `--restore --replace-all-data`; fresh installs skip the recovery backup |
| `d93035f` | One service `AuthLens`, one root `C:\ProgramData\AuthLens` with a private ACL created before staging; actions Install, Deploy, Restore; the `SapLens2` to `sap-lens` service migration, earlier-service detection and earlier configuration lookups removed; `AL` function prefix; Desktop folder `%LOCALAPPDATA%\AuthLens` with no earlier-folder fallback |
| `94858d1` | Documentation consolidated to the AuthLens model; `.gitignore` covers `*.authlens.json`, `AuthLens-diagnostics*.json` and `*.slbak` (synthetic fixtures excepted); test launcher identity file `authlens-test-server.json`; stale Windows-only junction test of the removed migration copy deleted; this audit |
| next commit | Expanded audit: SAP Lens 1 desktop bridge removed from the frontend; ad-hoc browser check scripts removed; v1 reference tools set `SAP_LENS_*` again (they drive SAP Lens 1, which reads those names); internal frontend identifiers renamed; script inventory and entry points below |

## 4. Cleanup report

Removed, each with its purpose established first:

| Removed | Purpose | Why it could go |
| --- | --- | --- |
| `SapLens.Migration.ps1` and `SapLens.Migration.Tests.ps1` | Moved the `SapLens2` service to `sap-lens` | Replaced by fresh install plus restore; never touching earlier services is now a rule |
| `SapLens.Configuration.ps1` | Derived a target configuration from a source one for that migration | Only used by the migration |
| `SapLens.Naming.Tests.ps1` | Asserted the `SapLens2`/`sap-lens` naming rules | Rules no longer exist; the AuthLens rules are tested in `AuthLens.Deploy.Tests.ps1` |
| Earlier-service detection, `SAPLENS_DEPLOY_CONFIG`/`SAPLENS2_DEPLOY_CONFIG`, `C:\sap-lens`/`C:\saplens2` lookups | Found an earlier installation automatically | Automatic adoption is forbidden |
| Prototype Desktop folder fallback, startup refusal of the earlier .NET variable prefix | Used `SAP Lens 2 Prototype` data; refused renamed variables | Earlier folders are now only reported; old variables warn |
| Junction test `keeps migration copying strict` | Covered the removed migration copy | Function removed; strict traversal is covered by the remaining junction tests |
| Frontend SAP Lens 1 desktop bridge (`window.pywebview`: native open/save dialogs, logo and CSV pickers, open-folder/open-logs buttons, `DesktopOptions` tray and sign-in settings, settings-ready handshake) and the specs that stubbed it | The SAP Lens 1 (pywebview) Desktop | The .NET Desktop never injects it, so every branch was unreachable and its controls were permanently disabled or hidden. Exports are browser downloads; sources use the browser picker or a server-visible path. Specs now exercise those real paths (downloads, path activation, logo preview) |
| `backend/tools/browser_check.js`, `refresh_report_check.js`, `import_preview_check.js`, `refresh_schedule_check.js`, `functional_groups_check.js` | One-off Playwright checks during the migration | No caller; superseded by the Playwright specs (`automatic-import`, `import-checks`, `scheduled-refresh`, `functional-groups*`, `dotnet-host`) |

Kept although they look legacy: SAP Lens 1 `SLBAK2` reading and the v1 data migration (the supported v1 import path), the HKDF labels
(cryptographic input), legacy archive entry and manifest products (restore of SAP Lens backups), historical migration documents and
`backend/tools` (fixture provenance), EF migration identifiers (schema history).

## 5. Script inventory and supported entry points

Every executable script was traced to its callers (`git grep` on its file name, CI, installers, tests, docs).

| Entry point | Purpose | Notes |
| --- | --- | --- |
| `backend/scripts/build-release.ps1` / `.sh` | Build, test and publish a release folder | One per platform, same contract |
| `backend/scripts/verify-release.ps1` | Verify a release folder against its manifest | Called by both build scripts, installers and deployment |
| `backend/scripts/build-installers.ps1` | Desktop and Server installers from a verified release | Windows only |
| `backend/scripts/deploy/Deploy-AuthLens.ps1` | The only deployment entry: Status, Health, Build, Deploy, InstallService, Restore, Rollback, Recover, AuditAcl, ProtectAcl, RestoreAcl | Module `AuthLens.Deploy.psm1` with `AuthLens.Acl.ps1` and `AuthLens.Paths.ps1` |
| `backend/scripts/deploy/deploy-windows.sh` | Runs `Deploy-AuthLens.ps1` over SSH from Linux | Thin wrapper, no own logic |
| `backend/scripts/Service-Manager.ps1` | Shipped in releases: host key, recovery copy, activation codes | Local administration without the SDK |
| `backend/scripts/start-server-test.ps1` | Isolated acceptance server on Windows | Refuses production paths |
| `AuthLens.Api` maintenance options | `--backup-key`, `--restore`, `--adopt-legacy-database`, `--migrate-v1`, schema and backup commands | The executable itself; scripts call it |
| `scripts/check-*.py`, `scripts/product-version.mjs`, `scripts/sync-lucide-catalog.mjs`, `scripts/browser-server.mjs` | Repository checks, version mirror, icon catalogue, Playwright test host | Called by CI, npm scripts and AGENTS.md commands |

Development-only: `backend/scripts/check-powershell.ps1` (parser check, CI), the Pester and Bash tests under `backend/scripts/tests`,
`backend/scripts/tests/v1-migration-procedure.ps1` (scripted run of the documented v1 import), `Measure-AclPerformance.ps1` (benchmark),
and `backend/tools` (v1 fixture generators and benchmarks; each `*_reference.py` is the provenance of a committed fixture and needs an external
SAP Lens 1 checkout). No two scripts perform the same operation.

## 6. Naming review

- **Backend:** projects, assemblies, namespaces and executables are `AuthLens.*`. The `V1*` classes in `AuthLens.Api` (for example
  `V1Access`, `V1SodDecisions`) are kept: `V1` names the HTTP contract the React UI calls (the API shape inherited from SAP Lens 1), as
  opposed to the native `/api/v1` endpoints in `Endpoints.cs`. Renaming 35 classes in 89 files would change no behaviour. `V1DataMigration`
  and `SLBAK2`/`IsV2` name SAP Lens 1 import and archive format versions. "Legacy reviews" (`SodLegacyReview`, `/api/sod/reviews`) is a
  SoD review type, not a product name.
- **Frontend:** components, hooks and files carry no product name. Internal identifiers were renamed (`authLensView` history state,
  `authlens-sign-in-required` event, test helper `__authLensCopied`). Persisted browser keys (`sap-lens-session`, `sap-lens-reviewer`,
  `sap-lens-filter-sidebar` and others), cookies and `X-SAP-Lens-*` headers stay so existing sessions and preferences keep working
  ([naming register](../architecture/VERSIONING.md#naming-register)). The private npm package is `authlens-frontend` (previously `sap-role-checker`).

## 7. Compatibility matrix

| From | To AuthLens | Status |
| --- | --- | --- |
| SAP Lens (.NET) backup `.slbak` (`SLBAK3`, entry `sap-lens-v2.sqlite3`) | Restore into a fresh installation, also on another machine | Supported; tested on Linux [T] |
| AuthLens backup | SAP Lens | Not supported (forward only) |
| SAP Lens 1 backup (`SLBAK2`) | v1 data migration | Supported, unchanged |
| SAP Lens data directory | `--adopt-legacy-database` (explicit, verified) | Supported; tested on Linux [T] |
| SAP Lens configuration export | Settings import | Accepted |
| SAP Lens release folders and manifests | `verify-release.ps1` | Accepted |
| `SAP_LENS_*` environment variables | Server | Ignored with a warning |
| SAP Lens service, data, keys, TLS, Desktop folder | AuthLens | Never read or changed |

Schema: unchanged (same EF migrations); only the file name differs. Encryption: unchanged (same algorithms and labels).

## 8. Validation

Linux only, 2026-11-20, on commit `bb33ea1` plus this documentation:

| Check | Result |
| --- | --- |
| .NET build and whole suite (`AuthLens.Tests`) | 0 warnings; 444/444 passed |
| Pester (`backend/scripts/tests`) | 144 passed, 9 failed, 30 skipped; the 9 are ACL remediation tests that call the Windows ACL API and fail identically at the baseline `814c88d`; skips are Windows-only |
| Bash SSH orchestrator test, PowerShell parser | 18/18; 23/23 files |
| Frontend type check, lint, unit tests, build | 0 errors; 0 errors; 43/43; built |
| Browser specs touched by the cleanup (20 files, one worker) | 43 passed, 140 failed; every test that passed at the baseline still passes; the failures fail at the baseline too (the `POST /api/configuration` harness gap, and `desktop.spec` at the same step) |
| Repository checks (docs, secrets, structure, workflows, Python and Node tests, Lucide catalogue, ruff, `git diff --check`) | All pass |
| Linux release build and `verify-release.ps1` | Verified: `AuthLens-2.0.0-alpha.1-…-win-x64` (17 files) and `-linux-x64` (8); `AuthLens.Api.exe`, `AuthLens.exe`, manifest product AuthLens |

Not run: the complete browser suite, and anything native on Windows (service, installers, ACLs, WebView2 downloads). The
[AuthLens acceptance checklist](../deployment/WINDOWS_DEPLOYMENT.md#acceptance-checklist-windows-pending) is pending.

## 9. Technical debt found and not changed

- `LICENSE.md` names SAP Lens (owner decision).
- `AuthLens.Acl.ps1` still builds a source/target plan; since the service migration was removed every entry point passes no target, so
  the target branch (target parents, provisioning) is reachable only from `AuthLens.Acl.Tests.ps1`. Its fixtures model the reported SAP Lens
  VM layout (`C:\saplens2`, `SapLens2`). Simplify both once the ACL tests can run on Windows; on Linux they cannot verify an ACL change.
- Feature documents `ACCOUNT_REVIEW.md`, `EMPLOYEE_DIRECTORY.md` and `IMPORT_AND_REFRESH.md` still describe SAP Lens 1 file storage under
  `%LOCALAPPDATA%\SAP Lens`; AuthLens keeps that data in SQLite. They predate the rename and need a separate rewrite.
- Logo file names `sap-lens.png`/`sap-lens.ico` and the `saplens_session` cookie keep the earlier name (renaming gains nothing visible and the
  cookie change signs users out).
- 9 Pester ACL remediation tests fail on Linux because they call the Windows ACL API; they fail identically at the baseline.
- 307 browser specs use the SAP Lens 1 `POST /api/configuration` contract the .NET host refuses ([browser tests](../development/README.md#browser-tests)).
