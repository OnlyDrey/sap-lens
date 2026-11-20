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
- **Result at the end of the work** (excluding the inventory file itself): 922 tracked files: 359 unchanged, 359 renamed, 194 changed in place,
  10 added, 10 removed. 218 files still contain an earlier name; all of them are classified below. Only `LICENSE.md` needs an owner decision.

## 2. Remaining earlier names by class

| Class | Files | Why they stay |
| --- | --- | --- |
| Compatibility | 58 | Read SAP Lens backups, configuration exports, release folders and manifests; refuse or adopt `sap-lens-v2.sqlite3`; leave earlier services and folders untouched; warn about `SAP_LENS_*`; keep browser storage keys, cookies and `X-SAP-Lens-*` headers |
| Historical | 54 | Dated migration records, ported SAP Lens 1 behaviour, deployment text that names earlier services in order to never touch them |
| Test | 51 | Assert the compatibility above, or rename v1 reference text through `ProductRename` |
| Documentation | 30 | Name the earlier product, the repository `sap-lens`, or the migration path |
| Tooling | 15 | `backend/tools` regenerate v1 fixtures from an external SAP Lens 1 checkout (`SAP_LENS_V1_BACKEND`) |
| Fixture | 5 | Recorded v1 evidence; regenerated, never edited by hand |
| Asset | 4 | Logo and icon file names (`assets/sap-lens.ico`, `sap-lens.png`); the logo is unchanged by request |
| Owner decision | 1 | `LICENSE.md` names the product in legal text; AGENTS.md keeps licensing intact, so the owner changes it |

## 3. Implemented changes

| Commit | Change |
| --- | --- |
| `b76517d` | Projects, namespaces, solution and executables `AuthLens.*` (`AuthLens.Api.exe`, `AuthLens.exe`); deployment module and scripts `AuthLens.*`; installer scripts |
| `45b3875` | Product text AuthLens (UI, reports, OpenAPI, installers, `--version`); export file names `authlens-*`; `AUTHLENS_*` environment variables (old names warn); release folders `AuthLens-*`; new installer AppIds; `verify-release.ps1` still accepts earlier products |
| `44f6ea7` | Database `authlens.sqlite3`; a directory with only `sap-lens-v2.sqlite3` is refused; explicit `--adopt-legacy-database`; backups write `authlens.sqlite3`/product AuthLens and restore SAP Lens archives; offline `--restore --replace-all-data`; fresh installs skip the recovery backup |
| `d93035f` | One service `AuthLens`, one root `C:\ProgramData\AuthLens` with a private ACL created before staging; actions Install, Deploy, Restore; the `SapLens2` to `sap-lens` service migration, earlier-service detection and earlier configuration lookups removed; `AL` function prefix; Desktop folder `%LOCALAPPDATA%\AuthLens` with no earlier-folder fallback |
| this commit | Documentation consolidated to the AuthLens model; `.gitignore` covers `*.authlens.json`, `AuthLens-diagnostics*.json` and `*.slbak` (synthetic fixtures excepted); test launcher identity file `authlens-test-server.json`; stale Windows-only junction test of the removed migration copy deleted; this audit |

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

Kept although they look legacy: SAP Lens 1 `SLBAK2` reading and the v1 data migration (the supported v1 import path), the HKDF labels
(cryptographic input), legacy archive entry and manifest products (restore of SAP Lens backups), historical migration documents and
`backend/tools` (fixture provenance), EF migration identifiers (schema history).

## 5. Compatibility matrix

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

## 6. Validation

See the final report of this task and [release status](RELEASE_STATUS.md). Native Windows (service, installers, ACLs, WebView2) has not run;
the [AuthLens acceptance checklist](../deployment/WINDOWS_DEPLOYMENT.md#acceptance-checklist-windows-pending) is pending.

## 7. Technical debt found and not changed

- `LICENSE.md` names SAP Lens (owner decision).
- Feature documents `ACCOUNT_REVIEW.md`, `EMPLOYEE_DIRECTORY.md` and `IMPORT_AND_REFRESH.md` still describe SAP Lens 1 file storage under
  `%LOCALAPPDATA%\SAP Lens`; AuthLens keeps that data in SQLite. They predate the rename and need a separate rewrite.
- Logo file names `sap-lens.png`/`sap-lens.ico` and the `saplens_session` cookie keep the earlier name (renaming gains nothing visible and the
  cookie change signs users out).
- 9 Pester ACL remediation tests fail on Linux because they call the Windows ACL API; they fail identically at the baseline.
- 307 browser specs use the SAP Lens 1 `POST /api/configuration` contract the .NET host refuses ([browser tests](../development/README.md#browser-tests)).
