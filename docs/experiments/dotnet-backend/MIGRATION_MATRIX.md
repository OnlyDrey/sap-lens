# Migration completion matrix (source of truth)

The single place that says what of SAP Lens v1 is migrated to SAP Lens 2 (.NET), how it is verified and what remains. Route-level detail is
generated in [ROUTE_AUDIT.md](ROUTE_AUDIT.md) (`tools/route_audit.py`); this matrix adds the workflow level that a route list hides
(filters that answer 501 inside an implemented route, sub-routes behind a template, behaviour without its own route). The dependency-ordered
work list with acceptance criteria is [MIGRATION_BACKLOG.md](MIGRATION_BACKLOG.md); per-area history is in [FEATURE_PARITY.md](FEATURE_PARITY.md).

Status: **Done** (served with the v1 contract and contract-tested), **Partial** (served, with named gaps), **Missing** (answers `501 not_migrated`).
Parity: **Verified** (identical results against Python v1 on synthetic fixtures), **Contract** (shape, validation and refusals tested; no
data-dependent comparison needed or possible), **Pending**.

Baseline 2026-11-16 at `902ddba`: route audit **83 of 145** UI route strings implemented. After MIG-009: **87 of 145**. After MIG-010: **89 of 145**. After MIG-008: **92 of 145**. After MIG-004: **93 of 145** (the 22 Functional Group routes share one UI route string). Every unimplemented route answers `501 not_migrated`.

| Area / feature | v1 implementation | SAP Lens 2 implementation | Status | Parity | Tests (.NET) | Dependencies | Remaining work | MIG |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Shell: version, application info, runtime, presentation, registry, product identity | `main.py`, `version.py`, `routers/presentation.py` | `V1Compatibility`, `ProductIdentity` | Done | Contract | `V1CompatibilityTests`, `VersioningTests` | - | Desktop native options (start at login, tray) are not offered by the .NET Desktop (`runtime` reports them unavailable) | - |
| Authentication, accounts, sessions, audit, identity migration (`auth/*`, 16) | `auth_store.py`, `routers/authentication.py` | `AccountStore`, `V1Auth` | Done | Contract (Argon2id store compatible) | `AccountsTests`, `SessionTests`, `ReverseProxyTests` | - | Adoption of an existing v1 `accounts.sqlite3` tested only on Linux | - |
| Role catalogue, Role Lookup, naming, access package, legacy compare | `cache.py`, `routers/roles.py`, `access_package.py` | `V1Compatibility`, `V1AccessPackage`, `V1Compare` | Done | Verified | `FunctionalEquivalence`, `AccessPackageTests`, `AccessExportTests` | - | - | MIG-R05 |
| User Access, user detail, selection, assignment exports | `routers/access.py`, `csv_exports.py` | `V1Access` | Done | Verified | `AccessTests`, `AccessExportTests`, `FunctionalGroupTests` (organization filters, row annotation) | - | Free-text search over Directory job title and department (v1 includes them when a Directory is loaded) | MIG-004 |
| Release Roles and exports (`access/release-*`, `access/exports/{users,release-roles,releases}`) | `routers/access.py` | `V1ReleaseRoles` | Done | Verified | `AccessExportTests` | - | - | - |
| User comparison, saved filters | `routers/user_comparison.py`, `saved_filters.py` | `V1Access`, `V1SavedFilters` | Done | Verified | `AccessTests`, `DashboardAndSavedFiltersTests` | - | - | - |
| Dashboard | `routers/dashboard.py` | `V1Dashboard` | Partial | Verified (catalogue, users, assignments, releases) | `DashboardAndSavedFiltersTests` | SoD overview (MIG-013), Account Review KPIs | Directory and Account Review KPIs report `null` with a reason; SoD overview card | MIG-013 |
| Data Health and coverage | `routers/data_health.py` | `V1DataHealth` | Done | Verified | `DataHealthTests`, `SodLifecycleTests` | - | - | - |
| Diagnostics and export | `diagnostics.py` | `V1Diagnostics` | Done | Contract (key sets equal v1) | `DiagnosticsTests`, `RefreshTests` (scheduler state) | - | - | MIG-019 |
| Data Sources: browse, select, upload, preview, history, cancel, employee inspection | `routers/data_sources.py`, `csv_lifecycle.py` | `V1DataSources`, `V1RefreshReports`, `RecordDiff`, `ImportService` | Partial | Verified (imports; report detail and export: 60 runs over roles, users, Employee Directory and SoD matrix) | `DataSourcesTests`, `ImportAndJobTests`, `RefreshReportTests`, `tools/refresh_report_check.js` (React) | - | SoD source inspection and the SoD `risk_change_summary` of a report (last milestone) | MIG-010 |
| Import profile header inspection and preview (`import/*`, `user-import/*`) | `configuration_routes.py`, `csv_import.py`, `user_access.py` | `V1ImportPreview`, `CsvImport.InspectHeader` | Done | Verified (20 runs over 8 synthetic CSVs: delimiters, cp1252, duplicate and missing headers, ragged rows, manual mappings) | `ImportPreviewTests`, `AccountsTests` (admin), `tools/import_preview_check.js` (React flow on a Server) | CSV readers | - | MIG-009 |
| Manual and scheduled refresh (`refresh`, `refresh-schedule/*`) | `main.py`, `scheduler.py`, `routers/refresh_schedule.py`, `cron_schedule.py` | `V1Refresh`, `V1RefreshSchedule`, `RefreshScheduler`, `CronSchedule` | Done | Verified (cron: 665 next-run cases incl. DST gaps and repeated hours, 57 descriptions, parse errors, 13 previews; refresh counts equal v1 diff) | `RefreshTests`, `tools/refresh_schedule_check.js` (React) | - | Unchanged-file detection compares parsed records (v1: file fingerprint); a changed but record-identical file is still unchanged | MIG-008 |
| Settings save re-imports after profile or module changes | `perform_apply` in `configuration_routes.py` | `V1DataSources` (configuration save), `V1Refresh.ImportWithSettingsAsync` | Partial | Contract | `ConfigurationTests`, `SettingsReimportTests` | - | Module display-name overrides (`module_overrides`) are stored but not applied to catalogue responses (`module_name`); v1 rebuilds the catalogue with them | MIG-002 |
| Configuration: export, import, reset, theme | `config.py`, `configuration_routes.py` | `V1Configuration`, `V1Settings`, `LogoStore` | Done | Verified | `ConfigurationTests`, `BrandingTests` | - | - | MIG-001 |
| Branding: application and report logos (`branding/*`, `sod/reports/branding`) | `branding.py`, `report_branding.py` (Pillow) | `ImageSanitizer` (SkiaSharp), `LogoStore`, `V1Branding` | Done | Verified (26 image cases equal v1) | `ReportingTests`, `BrandingTests` | - | - | MIG-001 |
| Employee Directory (`employees/*`, 7) | `employee_directory.py` | `V1Employees`, `PositionChangeStore`, `PositionChanges` | Done | Verified (change detection) | `EmployeeDirectoryTests`, `PositionChangeTests` | - | NFKC folding of compatibility characters (BLK-GLOBALIZATION) | MIG-003 |
| Account Review (`account-review/*`, `reviewer-profile`) | `account_review.py`, `review_identity.py` | `V1AccountReview` | Done | Verified | `AccountReviewTests`, `FunctionalGroupTests`, `PositionChangeTests` | - | - | MIG-003 |
| Functional Groups (`functional-groups/*`, 22 routes) | `functional_groups.py`, `organization.py`, `functional_group_analysis.py`, router | `FunctionalGroupStore`, `V1FunctionalGroups` | Partial | Verified (identity keys, rules, suggestions, format 1 migration, analysis); Contract (workflow) | `FunctionalGroupTests`, `tools/functional_groups_check.js` (React) | - | NFKC folding of compatibility characters (BLK-GLOBALIZATION); SoD `functional_groups`/`managers` filters (SoD milestone) | MIG-004 |
| Backup and restore (`backups/*`, 11; `storage/*` status and migration, 3) | `application_backups.py`, `backup_crypto.py`, `routers/storage.py` | Native SQLite backups at `/api/v1/admin/backups`; lifecycle re-baseline only | Missing | Pending | `PersistenceTests` (native) | - | v1 contract on SQLite backups, encryption, schedule, retention, storage status | MIG-005 |
| Data retention (`retention/*`, 4) | `data_retention.py` | - | Missing | Pending | - | SoD review data for its SoD part | Non-SoD datasets first | MIG-007 |
| SoD source, catalogue, reference library, analysis, evidence, export, appearance, metadata | `sod_import.py`, `sod_catalogue.py`, `sod_analysis.py` | `V1SodCatalogue`, `V1SodAnalysis` | Partial | Verified | `SodAnalysisTests`, `SodCatalogueTests`, `SodReferenceWorkbookTests` | Functional Groups | `functional_groups`/`managers` analysis filters answer 501 | MIG-004 |
| SoD decisions, subject, bulk review, remediation actions, simulation, review subjects, lifecycle memory | `sod_decisions.py`, `assignment_lifecycle.py`, `routers/sod_governance.py` | `SodDecisionStore`, `AssignmentLifecycle`, `V1SodDecisions` | Partial | Verified | `SodDecisionRoutesTests`, `SodBulkReviewTests`, `SodLifecycleTests`, `SodSimulateTests` | - | Legacy risk decisions `sod/reviews/{x}`; `GET sod/decisions/assignment` | MIG-014 |
| SoD scope, filter options, overview | `sod_scope.py` | - | Missing | Pending | - | MIG-014, MIG-016 | Three routes | MIG-013 |
| SoD explorer, access list, matrix, queue | `routers/sod_governance.py` | - | Missing | Pending | - | MIG-014 | Nine routes | MIG-015 |
| SoD periods (lifecycle, transitions, recapture, compare, deletion impact, frozen snapshots) | `sod_periods.py` | - | Missing | Pending | - | MIG-014 | Eight routes | MIG-016 |
| SoD remediation list and export | `sod_governance.py` | - | Missing | Pending | - | MIG-014 | Two routes | MIG-017 |
| SoD reports (preview, PDF, DOCX, remediation CSV/PDF) | `sod_reports.py` (ReportLab, python-docx) | Renderers `PdfReportRenderer`, `DocxReportRenderer` ([REPORTING_ARCHITECTURE.md](REPORTING_ARCHITECTURE.md)); branding routes done | Partial | Verified (renderers: content, pages, metadata equal v1 on synthetic models) | `ReportingTests` | MIG-016, MIG-017 | Report models and routess | MIG-018 |
| Migration of existing v1 data (decisions, lifecycle memory, evidence, reviews, settings) | JSON stores | - | Missing | Pending | - | All stores above | Import with verification ([MIGRATION_STRATEGY.md](MIGRATION_STRATEGY.md)) | MIG-014 |
| Packaging, versioning, Windows service, reverse proxy | v1 installers and scripts | `build-release.*`, `ProductIdentity`, `ProxyTrust` | Done (Linux) | Contract | `PublishTests`, `VersioningTests`, Pester | Windows VM | Native Windows acceptance of Server, Desktop, service and upgrade | - |

## Blockers and gap register (migration attempt 2026-11-17)

State: **MIGRATION_ATTEMPT_COMPLETE_WITH_GAPS** at `935f5ce` (route audit 93 of 145). Not production-ready. Root causes:

| ID | Root cause | Affects | Decision needed |
| --- | --- | --- | --- |
| BLK-GLOBALIZATION | `Directory.Build.props` builds the server with `InvariantGlobalization=true`: no NFKC folding of compatibility characters (ligatures, full-width letters, no-break space), and on Windows no IANA time zone names (`local` and `UTC` work) | MIG-004, MIG-003 text folding (test `Compatibility_characters_fold_like_python_v1` skipped with this ID); MIG-008 schedules in IANA zones on Windows | Yes: enable ICU for the server (Windows ships ICU; Linux needs libicu) or accept the gap |
| BLK-IMAGE | Resolved 2026-11-17: SkiaSharp (MIT), see [REPORTING_ARCHITECTURE.md](REPORTING_ARCHITECTURE.md) | MIG-001 done | No |
| BLK-REPORTS | Resolved 2026-11-17: SkiaSharp PDF backend and Open XML SDK (MIT), renderers implemented and compared with v1; the routes wait for BLK-SOD-SCOPE | MIG-018 routes | No |
| BLK-SOD-SCOPE | Every remaining SoD route resolves its review context through `sod_scope` (scope query, frozen period snapshots, review store) and `sod_periods`; neither exists in .NET, and they are interdependent | MIG-013, MIG-015, MIG-016, MIG-017, MIG-014 remainder, SoD part of MIG-007, SoD `functional_groups`/`managers` filters, Dashboard SoD card | No decision; next milestone, in order MIG-016 + `sod_scope` -> MIG-013 -> MIG-015/017 -> MIG-018 |
| BLK-BACKUP-DESIGN | v1 backups are encrypted archives of JSON files restored at restart (scrypt or host-key AES-256-GCM); SAP Lens 2 stores SQLite. The v1 route contract can be served (AES-GCM in the base library, Argon2id already approved), but restore, key escrow and storage migration change all application data | MIG-005 (14 routes), import of encrypted v1 `.slbak` files (scrypt is not in the base library) | Yes: approve the SQLite-backed design (Argon2id instead of scrypt for new backups; v1 `.slbak` import only for unencrypted or host-key archives, or approve a scrypt implementation) |
| BLK-V1-DATA | Importing existing v1 stores (decisions, lifecycle memory, evidence, review history, Functional Groups, settings) needs every target store; it is an irreversible data migration | v1 data migration | Yes: approval required before any data migration runs on real installations |

| MIG | Feature | Status | Completed | Missing | Dependencies | Priority |
| --- | --- | --- | --- | --- | --- | --- |
| MIG-002 | Settings save re-import | PARTIALLY_MIGRATED | Format changes re-import, versions, schedule checks | Module display-name overrides in catalogue responses | - | Low |
| MIG-004 | Functional Groups | PARTIALLY_MIGRATED | 22 routes, User Access and Account Review integration | NFKC (BLK-GLOBALIZATION), SoD filters (BLK-SOD-SCOPE) | MIG-013 | Medium |
| MIG-005 | Backup and restore, storage status | NOT_MIGRATED | Native SQLite backups (`/api/v1/admin/backups`) | v1 contract (14 routes) | BLK-BACKUP-DESIGN | High |
| MIG-007 | Data retention | NOT_MIGRATED | - | 4 routes; SoD datasets need periods and reviews | BLK-SOD-SCOPE | Medium |
| MIG-010 | SoD source inspection, risk change summary | NOT_MIGRATED (part) | Report detail and export done | `data-sources/sod/inspect`, `inspection`, `risk_change_summary` | BLK-SOD-SCOPE | Low |
| MIG-013/015/016/017 | SoD scope, explorer, matrix, queue, periods, remediation | NOT_MIGRATED | Decisions, bulk review, simulation, lifecycle (MIG-014 parts) | 22 routes | BLK-SOD-SCOPE | High |
| MIG-014 | SoD legacy risk decisions, assignment decision read | PARTIALLY_MIGRATED | See row above | `sod/reviews/{x}`, `GET sod/decisions/assignment` | BLK-SOD-SCOPE | Medium |
| MIG-018 | SoD reports | PARTIALLY_MIGRATED | Renderers, report branding | Report models and 6 routes | MIG-016, MIG-017 (BLK-SOD-SCOPE) | Medium |
| - | Migration of v1 data | NOT_MIGRATED | Strategy documented | Importers with verification | BLK-V1-DATA, all stores | High |
| - | Windows acceptance (Desktop, Server, service, installer, upgrade, rollback) | UNVERIFIED (environment) | Linux builds and Pester tests | Native runs on a Windows VM | Windows environment | High |

## How this matrix is kept

Update the row of an area in the commit that changes its status, and regenerate [ROUTE_AUDIT.md](ROUTE_AUDIT.md) when routes change. A row
moves to Done only with its tests named; Verified needs a comparison against Python v1 on synthetic data.
