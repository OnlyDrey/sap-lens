# Migration completion matrix (source of truth)

The single place that says what of SAP Lens v1 is migrated to SAP Lens 2 (.NET), how it is verified and what remains. Route-level detail is
generated in [ROUTE_AUDIT.md](ROUTE_AUDIT.md) (`tools/route_audit.py`); this matrix adds the workflow level that a route list hides
(filters that answer 501 inside an implemented route, sub-routes behind a template, behaviour without its own route). The dependency-ordered
work list with acceptance criteria is [MIGRATION_BACKLOG.md](MIGRATION_BACKLOG.md); per-area history is in [FEATURE_PARITY.md](FEATURE_PARITY.md).

Status: **Done** (served with the v1 contract and contract-tested), **Partial** (served, with named gaps), **Missing** (answers `501 not_migrated`).
Parity: **Verified** (identical results against Python v1 on synthetic fixtures), **Contract** (shape, validation and refusals tested; no
data-dependent comparison needed or possible), **Pending**.

Baseline 2026-11-16 at `902ddba`: route audit **83 of 145** UI route strings implemented. Every unimplemented route answers `501 not_migrated`.

| Area / feature | v1 implementation | SAP Lens 2 implementation | Status | Parity | Tests (.NET) | Dependencies | Remaining work | MIG |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Shell: version, application info, runtime, presentation, registry, product identity | `main.py`, `version.py`, `routers/presentation.py` | `V1Compatibility`, `ProductIdentity` | Done | Contract | `V1CompatibilityTests`, `VersioningTests` | - | Desktop native options (start at login, tray) are not offered by the .NET Desktop (`runtime` reports them unavailable) | - |
| Authentication, accounts, sessions, audit, identity migration (`auth/*`, 16) | `auth_store.py`, `routers/authentication.py` | `AccountStore`, `V1Auth` | Done | Contract (Argon2id store compatible) | `AccountsTests`, `SessionTests`, `ReverseProxyTests` | - | Adoption of an existing v1 `accounts.sqlite3` tested only on Linux | - |
| Role catalogue, Role Lookup, naming, access package, legacy compare | `cache.py`, `routers/roles.py`, `access_package.py` | `V1Compatibility`, `V1AccessPackage`, `V1Compare` | Done | Verified | `FunctionalEquivalence`, `AccessPackageTests`, `AccessExportTests` | - | - | MIG-R05 |
| User Access, user detail, selection, assignment exports | `routers/access.py`, `csv_exports.py` | `V1Access` | Done | Verified | `AccessTests`, `AccessExportTests` | Functional Groups for its group filters | Functional Group filter values | MIG-004 |
| Release Roles and exports (`access/release-*`, `access/exports/{users,release-roles,releases}`) | `routers/access.py` | `V1ReleaseRoles` | Done | Verified | `AccessExportTests` | - | - | - |
| User comparison, saved filters | `routers/user_comparison.py`, `saved_filters.py` | `V1Access`, `V1SavedFilters` | Done | Verified | `AccessTests`, `DashboardAndSavedFiltersTests` | - | - | - |
| Dashboard | `routers/dashboard.py` | `V1Dashboard` | Partial | Verified (catalogue, users, assignments, releases) | `DashboardAndSavedFiltersTests` | SoD overview (MIG-013), Account Review KPIs | Directory and Account Review KPIs report `null` with a reason; SoD overview card | MIG-013 |
| Data Health and coverage | `routers/data_health.py` | `V1DataHealth` | Done | Verified | `DataHealthTests`, `SodLifecycleTests` | - | - | - |
| Diagnostics and export | `diagnostics.py` | `V1Diagnostics` | Partial | Contract (key sets equal v1) | `DiagnosticsTests` | MIG-008 | Scheduler state reports "never attempted" | MIG-019 |
| Data Sources: browse, select, upload, preview, history, cancel, employee inspection | `routers/data_sources.py`, `csv_lifecycle.py` | `V1DataSources`, `ImportService` | Partial | Verified for imports | `DataSourcesTests`, `ImportAndJobTests` | - | Refresh report detail and change export; SoD source inspection (last milestone) | MIG-010 |
| Import profile header inspection and preview (`import/*`, `user-import/*`) | `configuration_routes.py`, `csv_import.py`, `user_access.py` | - | Missing | Pending | - | CSV readers (exist) | All four routes | MIG-009 |
| Manual and scheduled refresh (`refresh`, `refresh-schedule/*`) | `main.py`, `refresh_schedule.py`, `cron_schedule.py` | - | Missing | Pending | - | MIG-009 readers, path sources | All three routes, scheduler | MIG-008 |
| Settings save re-imports after profile or module changes | `perform_apply` in `configuration_routes.py` | Settings stored; next import uses them | Partial | Pending | `ConfigurationTests` | Path sources | Re-import of the active dataset | MIG-002 |
| Configuration: export, import, reset, theme | `config.py`, `configuration_routes.py` | `V1Configuration`, `V1Settings` | Partial | Verified | `ConfigurationTests` | Image codec | `logo_base64` in configuration import answers 501 | MIG-001 |
| Branding: custom logo (`branding/*`) | `branding.py` (Pillow) | - | Missing | Pending | - | Image codec decision | Both routes; logos in reports | MIG-001 |
| Employee Directory (`employees/*`, 7) | `employee_directory.py` | `V1Employees` | Partial | Verified | `EmployeeDirectoryTests` | - | Position-change history | MIG-003 |
| Account Review (`account-review/*`, `reviewer-profile`) | `account_review.py`, `review_identity.py` | `V1AccountReview` | Partial | Verified | `AccountReviewTests` | Directory history | Position and manager change evidence (`position_change_id`, `manager_change_id` are null) | MIG-003 |
| Functional Groups (`functional-groups`) | `functional_groups.py`, router | - | Missing | Pending | - | - | Definitions, membership, analysis, filters | MIG-004 |
| Backup and restore (`backups/*`, 11; `storage/*` status and migration, 3) | `application_backups.py`, `backup_crypto.py`, `routers/storage.py` | Native SQLite backups at `/api/v1/admin/backups`; lifecycle re-baseline only | Missing | Pending | `PersistenceTests` (native) | - | v1 contract on SQLite backups, encryption, schedule, retention, storage status | MIG-005 |
| Data retention (`retention/*`, 4) | `data_retention.py` | - | Missing | Pending | - | SoD review data for its SoD part | Non-SoD datasets first | MIG-007 |
| SoD source, catalogue, reference library, analysis, evidence, export, appearance, metadata | `sod_import.py`, `sod_catalogue.py`, `sod_analysis.py` | `V1SodCatalogue`, `V1SodAnalysis` | Partial | Verified | `SodAnalysisTests`, `SodCatalogueTests`, `SodReferenceWorkbookTests` | Functional Groups | `functional_groups`/`managers` analysis filters answer 501 | MIG-004 |
| SoD decisions, subject, bulk review, remediation actions, simulation, review subjects, lifecycle memory | `sod_decisions.py`, `assignment_lifecycle.py`, `routers/sod_governance.py` | `SodDecisionStore`, `AssignmentLifecycle`, `V1SodDecisions` | Partial | Verified | `SodDecisionRoutesTests`, `SodBulkReviewTests`, `SodLifecycleTests`, `SodSimulateTests` | - | Legacy risk decisions `sod/reviews/{x}`; `GET sod/decisions/assignment` | MIG-014 |
| SoD scope, filter options, overview | `sod_scope.py` | - | Missing | Pending | - | MIG-014, MIG-016 | Three routes | MIG-013 |
| SoD explorer, access list, matrix, queue | `routers/sod_governance.py` | - | Missing | Pending | - | MIG-014 | Nine routes | MIG-015 |
| SoD periods (lifecycle, transitions, recapture, compare, deletion impact, frozen snapshots) | `sod_periods.py` | - | Missing | Pending | - | MIG-014 | Eight routes | MIG-016 |
| SoD remediation list and export | `sod_governance.py` | - | Missing | Pending | - | MIG-014 | Two routes | MIG-017 |
| SoD reports (preview, PDF, DOCX, remediation CSV/PDF, branding) | `sod_reports.py` (ReportLab, python-docx) | - | Missing | Pending | - | MIG-016, MIG-017, PDF/DOCX dependency decision | Seven routes | MIG-018 |
| Migration of existing v1 data (decisions, lifecycle memory, evidence, reviews, settings) | JSON stores | - | Missing | Pending | - | All stores above | Import with verification ([MIGRATION_STRATEGY.md](MIGRATION_STRATEGY.md)) | MIG-014 |
| Packaging, versioning, Windows service, reverse proxy | v1 installers and scripts | `build-release.*`, `ProductIdentity`, `ProxyTrust` | Done (Linux) | Contract | `PublishTests`, `VersioningTests`, Pester | Windows VM | Native Windows acceptance of Server, Desktop, service and upgrade | - |

## How this matrix is kept

Update the row of an area in the commit that changes its status, and regenerate [ROUTE_AUDIT.md](ROUTE_AUDIT.md) when routes change. A row
moves to Done only with its tests named; Verified needs a comparison against Python v1 on synthetic data.
