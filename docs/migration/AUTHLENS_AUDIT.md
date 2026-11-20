# AuthLens rename and consolidation audit (2026-11-20)

Record of the repository-wide audit and the rename from SAP Lens to AuthLens. Baseline: commit `814c88d` (before the rename). The canonical
rules that came out of it live in the [naming register](../architecture/VERSIONING.md#naming-register), the
[installation layout](../deployment/WINDOWS_DEPLOYMENT.md#installation-layout) and
[migrating from SAP Lens](../deployment/WINDOWS_DEPLOYMENT.md#migrating-from-sap-lens); this file is the audit trail, not a procedure.

The per-file inventory is [authlens-inventory.json](authlens-inventory.json): the upstream rename checkpoint compared with 814c88d, with status
(unchanged, changed, renamed with its previous path, added, removed), the naming references before and after, and for each remaining
reference a classification and reason. Its counts are historical; the Windows continuation below records subsequent changes. Its original documentation paths and license classification describe that checkpoint, before the approved archive move and product-reference update.

## 1. Scope and method

- **Inspected:** all 922 tracked files of the baseline (code, scripts, tests, installers, workflows, docs, fixtures, examples, assets). Each was
  searched for `SAP Lens`, `SapLens`, `sap-lens`, `SAP_LENS`, `saplens`; binaries were listed by name only.
- **Not a global replace:** names were changed per category (identifiers, product text, file names, environment variables, paths), each with
  exclusions for persisted, cryptographic, API-contract and historical identifiers. Every exclusion is listed in the naming register.
- **Upstream rename checkpoint** (including the inventory file): 917 tracked files: 366 unchanged, 359 renamed, 181 changed in place,
  11 added; 16 removed. 237 files still contain an earlier name; all of them are classified below. The licensing continuation changes product references only and leaves ownership and legal terms unchanged.

## 2. Remaining earlier names at the upstream rename checkpoint

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

- License product references were updated to AuthLens with explicit approval in the Windows continuation; legal clauses and ownership wording are unchanged.
- Logo file names `sap-lens.png`/`sap-lens.ico` and the `saplens_session` cookie keep the earlier name (renaming gains nothing visible and the
  cookie change signs users out).
- 15 browser tests remained open at the Linux checkpoint; current Windows results supersede them in [release status](RELEASE_STATUS.md).

## Windows continuation assessment (2026-11-20, baseline 50bed6d)

The checkout fast-forwarded from 814c88d to 50bed6d (18 commits; no divergent history). Pre-existing local work was retained in a named Git stash, reconciled through the AuthLens renames, and left available for recovery. Six superseded untracked drafts/helpers were moved byte-for-byte into an ignored preservation directory under build/test-artifacts, with SHA-256 manifest; they were not published or destroyed.

| Area reviewed | Classification and disposition |
| --- | --- |
| Product metadata, namespaces, React identity, executables, logos | Correct at upstream baseline; keep version 2.0.0-alpha.1 and original assets. Historical protocol/storage names remain compatibility identifiers. |
| Server paths and Desktop defaults | Correct canonical Server root; Desktop explicit data override was defective because logs/mutex still used the real profile. Explicit overrides now isolate data, logs, profile and mutex; native published Desktop self-check and location contracts passed. |
| SQLite naming, schema identifiers, legacy adoption | Correct canonical database and explicit legacy-only refusal; preserve historical schema IDs and legacy readers. |
| Import checks and activation | Local fixes preserve per-job policy, header-only rejection and existing data. They are reconciled rather than discarded. |
| Managed source files and portable backup | Incomplete: observations persisted, raw CSV copies were missing from backups. Extended the existing import transaction/report metadata and backup engine, without schema changes. |
| Accounts, roles, reviews, SoD evidence | SQLite holds immutable records and snapshots; source inspection confirms no extra evidence-file engine. Functional Groups and Desktop Account Review request aliases were defective attribution inputs; use the existing stable profile/account. |
| Refresh revision/reporting | Defective SAP revision included the unrelated SoD source. Share the existing revision helper across responses; retain SoD's own generation. |
| Browser failures | Mixed outdated fixtures/navigation/auth assumptions and actual attribution/download defects. Reproduce and fix by category, without timeout increases or assertion removal. |
| Report/download paths | Defective quoted-only export filename parsing; reuse the existing strict RFC 6266 parser and retain per-export patterns. Windows fixture paths use fileURLToPath. |
| Backup encryption, retention, restore safety | Existing engine and policy retained; extend archive whitelist/checksums and staged validation for database-referenced managed copies. Old archives lacking copies remain supported. |
| Installer/update and Windows acceptance | Incomplete/unverified. Compiler and elevated SCM prerequisites are absent; do not claim native installer, service, rollback or reboot acceptance. |
| Optional Python reference generators | Required fixture provenance, not runtime dependencies. Proposed local deletions were not applied because the upstream audit records their callers/purpose. Versioned browser workbooks remove the obsolete local Python helper. |
| Historical documentation | Necessary evidence belongs under docs/archive; preserve contents and update links. Active release status must identify current results separately from old Linux evidence. |
| Licensing | Product references updated only. Proprietary license type, ownership wording, legal terms, liability and third-party attribution requirements are unchanged; no rights or owner were invented. |

The lack of native acceptance is a release blocker, not a reason to skip independent implementation or testing. Final counts and the release recommendation are recorded in [release status](RELEASE_STATUS.md). No push is authorized by this mission.

Windows continuation root causes: raw CSV copies were missing from the backup boundary; reviewer aliases came from request bodies instead of the stable actor; SAP revisions included the independent SoD publication; export filenames accepted only quoted headers; Windows file URLs were treated as POSIX paths; explicit Desktop data overrides shared normal profile resources; Server installer updates overwrote files without verified rollback. Browser fixtures also read settings before a confirmed save completed, assumed a fixed optional-source count despite reset retaining lifecycle history (the fixture now explicitly seeds disabled SoD plus a static directory), and omitted the captured directory snapshot variables. These corrections preserve the state, identity, history and data-retention assertions. The complete checkpoint and scoped corrections are reported separately, not combined into a claimed clean single full run.

## Installer stabilization continuation (baseline 798d3d0)

Local implementation now adds an Inno transaction adapter over the existing verified release/deployment/backup engine. Previously, Desktop
copied its executable without verified rollback and Server deliberately refused updates. Both stage unique immutable packages and hashed helper
inventories; Desktop uses private atomic checkpoints and backup/readiness/binary recovery, and Server delegates to the existing versioned state
machine with mandatory previous-release/schema/account proof. Windows PowerShell 5.1 needs nonempty backup paths for File.Replace; unique retained
checkpoint paths fix that native incompatibility. Child PowerShell selection is explicit under PSHOME, with no PATH dependency or PowerShell 7
requirement. Custom Desktop data profiles are retained in shortcuts, launch and updates. No schema, product version, UI identity or CI change.

Native isolated Desktop fresh install, update with an encrypted verified backup, interrupted recovery and preserved canonical data passed using
the previously verified bfa7226 package. A further native fixture replaced bfa7226 with the verified 8d05990 binary, injected a readiness failure after real replacement, verified the old binary
and its real probe, then passed update and interrupted recovery. SCM remains mocked and Inno remains uncompiled; this is adapter acceptance,
not compiled Setup acceptance. Protective backup, schema compatibility and recovery hash guards are unchanged or stricter. No existing service/data/TLS/key
was selected. New portable governance coverage restores the application-written v1 fixture's review history and frozen SoD evidence into fresh
canonical storage through the shared backup engine; the former SoD-fixture gap in the matrix was stale and is corrected.

The [current inventory](MIGRATION_MATRIX.md#release-stabilization-inventory-2026-11-20) distinguishes COMPLETE/PARTIAL/MISSING/BLOCKED. Native tray
and start-at-login are missing capabilities, not silently enabled by restoring an obsolete bridge. Final counts, local commits and remaining
acceptance gates are in [release status](RELEASE_STATUS.md). No push, publication or production operation is authorized.
