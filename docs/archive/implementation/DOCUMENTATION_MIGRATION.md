# Documentation migration inventory — 26 October 2026

The 59 original Markdown documents were reviewed for purpose, headings, current
contracts, historical evidence and repository consumers before migration. Current
source/scripts/tests own behavior. No application runtime or build policy was
changed; packaging edits update documentation inputs only. No substantive historical
report was deleted solely because it was old. The five merged source files are
removed as duplicate authorities, not copied into an archive. Selected feature
validation was extracted into FEATURE_BASELINES; privacy P-01 remains unchanged.

| Original document | Purpose / audience | Action | Canonical destination | Decision |
| --- | --- | --- | --- | --- |
| `CONFIGURATION.md` | Configuration and recovery; operators | Move | [getting-started/CONFIGURATION.md](../../getting-started/CONFIGURATION.md) | Canonical topic ownership; relative references migrated |
| `DEPLOYMENT.md` | SAP Lens deployment; operators | Move | [deployment/README.md](../../deployment/README.md) | Canonical topic ownership; relative references migrated |
| `DEPLOYMENT_PACKAGES.md` | Downloadable deployment packages; operators | Merge | [deployment/BUILD.md](../../deployment/BUILD.md) | Overlapping procedures/contracts consolidated; superseded placement descriptions corrected |
| `LOCAL_DEPLOYMENT_BUILDS.md` | Local deployment builds; operators | Merge | [deployment/BUILD.md](../../deployment/BUILD.md) | Overlapping procedures/contracts consolidated; superseded placement descriptions corrected |
| `LOCAL_WINDOWS_BUILD.md` | Build SAP Lens locally on Windows; operators | Merge | [deployment/BUILD.md](../../deployment/BUILD.md) | Overlapping procedures/contracts consolidated; superseded placement descriptions corrected |
| `INSTALLATION_WINDOWS_DESKTOP.md` | Windows Desktop installation and upgrades; operators | Move | [deployment/WINDOWS_DESKTOP.md](../../deployment/WINDOWS_DESKTOP.md) | Canonical topic ownership; relative references migrated |
| `DEPLOYMENT_WINDOWS_SERVER.md` | Windows Server service; operators | Move | [deployment/WINDOWS_SERVICE.md](../../deployment/WINDOWS_SERVICE.md) | Canonical topic ownership; relative references migrated |
| `DEPLOYMENT_LINUX_DOCKER.md` | Linux Docker Compose; operators | Move | [deployment/LINUX_DOCKER.md](../../deployment/LINUX_DOCKER.md) | Canonical topic ownership; relative references migrated |
| `DEPLOYMENT_LINUX_NATIVE.md` | Linux native/systemd and browser client; operators | Move | [deployment/LINUX_NATIVE.md](../../deployment/LINUX_NATIVE.md) | Canonical topic ownership; relative references migrated |
| `DEPLOYMENT_SECURITY.md` | Server security boundary; operators | Move | [deployment/SECURITY.md](../../deployment/SECURITY.md) | Canonical topic ownership; relative references migrated |
| `RELEASES.md` | Workflow-driven Windows versions and releases; operators | Move | [deployment/RELEASES.md](../../deployment/RELEASES.md) | Canonical topic ownership; relative references migrated |
| `WINDOWS_CODE_SIGNING.md` | Windows code signing readiness; operators | Move | [deployment/CODE_SIGNING.md](../../deployment/CODE_SIGNING.md) | Canonical topic ownership; relative references migrated |
| `DASHBOARD.md` | Dashboard and shared notifications; investigators | Move | [features/DASHBOARD.md](../../features/DASHBOARD.md) | Canonical topic ownership; relative references migrated |
| `ACCOUNT_REVIEW.md` | SAP Account Review; investigators | Move | [features/ACCOUNT_REVIEW.md](../../features/ACCOUNT_REVIEW.md) | Canonical topic ownership; relative references migrated |
| `USER_COMPARISON.md` | User Comparison; investigators | Move | [features/COMPARE_USERS.md](../../features/COMPARE_USERS.md) | Canonical topic ownership; relative references migrated |
| `SAVED_FILTERS.md` | Saved Filters; investigators | Move | [features/SAVED_FILTERS.md](../../features/SAVED_FILTERS.md) | Canonical topic ownership; relative references migrated |
| `ROLE_PRESENTATION.md` | Role presentation and transaction investigation; investigators | Rewrite | [features/ROLE_LOOKUP.md](../../features/ROLE_LOOKUP.md) | Canonical topic ownership; relative references migrated |
| `INVESTIGATION_FILTERS.md` | Catalogue and assignment investigation filters; investigators | Merge | [features/FILTERS.md](../../features/FILTERS.md) | Overlapping procedures/contracts consolidated; superseded placement descriptions corrected |
| `LIVE_FILTERS.md` | Live transaction filters and evidence presentation; investigators | Merge | [features/FILTERS.md](../../features/FILTERS.md) | Overlapping procedures/contracts consolidated; superseded placement descriptions corrected |
| `CSV_IMPORT.md` | CSV profiles and preserved relationships; investigators | Rewrite | [data/CSV_SCHEMAS.md](../../data/CSV_SCHEMAS.md) | Canonical topic ownership; relative references migrated |
| `CSV_DATA_LIFECYCLE.md` | CSV data lifecycle and refresh evidence; investigators | Move | [data/IMPORT_AND_REFRESH.md](../../data/IMPORT_AND_REFRESH.md) | Canonical topic ownership; relative references migrated |
| `EMPLOYEE_DIRECTORY.md` | Employee Directory and optional features; investigators | Rewrite | [data/EMPLOYEE_DIRECTORY.md](../../data/EMPLOYEE_DIRECTORY.md) | Canonical topic ownership; relative references migrated |
| `DATA_HEALTH.md` | Data Health & Coverage; investigators | Move | [data/DATA_HEALTH.md](../../data/DATA_HEALTH.md) | Canonical topic ownership; relative references migrated |
| `CLASSIFICATION.md` | CSV-based SAP area labels; investigators | Move | [data/CLASSIFICATION.md](../../data/CLASSIFICATION.md) | Canonical topic ownership; relative references migrated |
| `MODULES.md` | Central SAP area registry; investigators | Move | [data/SAP_MODULES.md](../../data/SAP_MODULES.md) | Canonical topic ownership; relative references migrated |
| `ARCHITECTURE.md` | Architecture and performance; developers | Move | [architecture/SYSTEM.md](../../architecture/SYSTEM.md) | Canonical topic ownership; relative references migrated |
| `API_REFERENCE.md` | Local API reference; investigators | Move | [architecture/API.md](../../architecture/API.md) | Canonical topic ownership; relative references migrated |
| `DESIGN_SYSTEM.md` | SAP Lens design system; developers | Move | [architecture/DESIGN_SYSTEM.md](../../architecture/DESIGN_SYSTEM.md) | Canonical topic ownership; relative references migrated |
| `COMPONENT_LIBRARY.md` | Component Library and UI architecture inventory; developers | Move | [architecture/COMPONENTS.md](../../architecture/COMPONENTS.md) | Canonical topic ownership; relative references migrated |
| `NAVIGATION_PATTERNS.md` | Navigation patterns; developers | Move | [architecture/NAVIGATION.md](../../architecture/NAVIGATION.md) | Canonical topic ownership; relative references migrated |
| `DESKTOP.md` | Windows Desktop 1.2; investigators | Move | [architecture/DESKTOP.md](../../architecture/DESKTOP.md) | Canonical topic ownership; relative references migrated |
| `UX_AND_THEMES.md` | Desktop workspace and themes (1.2); investigators | Move | [architecture/APPEARANCE.md](../../architecture/APPEARANCE.md) | Canonical topic ownership; relative references migrated |
| `SECURITY_REVIEW.md` | Security and optimization review; developers | Rewrite | [architecture/SECURITY.md](../../architecture/SECURITY.md) | Current boundaries rewritten; dated review preserved separately |
| `PRIVACY.md` | Public repository privacy; developers | Move | [architecture/PRIVACY.md](../../architecture/PRIVACY.md) | Canonical topic ownership; relative references migrated |
| `DEVELOPMENT.md` | Run SAP Lens from source (no EXE); developers | Move | [development/DEVELOPMENT.md](../../development/DEVELOPMENT.md) | Canonical topic ownership; relative references migrated |
| `CI_ARCHITECTURE.md` | CI architecture; developers | Move | [development/CI.md](../../development/CI.md) | Canonical topic ownership; relative references migrated |
| `DEPRECATIONS.md` | Deprecation maintenance; developers | Move | [development/DEPENDENCY_MAINTENANCE.md](../../development/DEPENDENCY_MAINTENANCE.md) | Canonical topic ownership; relative references migrated |
| `ACCESS_INSIGHTS_FEASIBILITY.md` | Access Insights feasibility and evidence inventory; investigators | Move | [proposals/ACCESS_INSIGHTS.md](../../proposals/ACCESS_INSIGHTS.md) | Canonical topic ownership; relative references migrated |
| `AUTHORIZATION_RISK_ANALYSIS_CONCEPT.md` | Authorization Risk Analysis — future concept; investigators | Move | [proposals/AUTHORIZATION_RISK.md](../../proposals/AUTHORIZATION_RISK.md) | Canonical topic ownership; relative references migrated |
| `ACCOUNT_REVIEW_VALIDATION.md` | Operational UI, settings and account-review validation; maintainers / historical evidence | Archive | [archive/validation/ACCOUNT_REVIEW_VALIDATION.md](../../archive/validation/ACCOUNT_REVIEW_VALIDATION.md) | Unique dated results/constraints retained; not current instructions |
| `DIRECTORY_AND_DASHBOARD_VALIDATION.md` | Directory, feature and investigation workflow validation; maintainers / historical evidence | Archive | [archive/validation/DIRECTORY_AND_DASHBOARD_VALIDATION.md](../../archive/validation/DIRECTORY_AND_DASHBOARD_VALIDATION.md) | Unique dated results/constraints retained; not current instructions |
| `INSTALLATION_LIFECYCLE_VALIDATION.md` | Installation lifecycle implementation and validation; maintainers / historical evidence | Archive | [archive/validation/INSTALLATION_LIFECYCLE_VALIDATION.md](../../archive/validation/INSTALLATION_LIFECYCLE_VALIDATION.md) | Unique dated results/constraints retained; not current instructions |
| `INVESTIGATION_TOOLS_VALIDATION.md` | Investigation tools — implementation and validation; maintainers / historical evidence | Archive | [archive/validation/INVESTIGATION_TOOLS_VALIDATION.md](../../archive/validation/INVESTIGATION_TOOLS_VALIDATION.md) | Unique dated results/constraints retained; not current instructions |
| `LOCAL_BUILD_VALIDATION.md` | Local build validation record; maintainers / historical evidence | Archive | [archive/validation/LOCAL_BUILD_VALIDATION.md](../../archive/validation/LOCAL_BUILD_VALIDATION.md) | Unique dated results/constraints retained; not current instructions |
| `PACKAGING_VALIDATION.md` | Cross-platform packaging validation — 24 October 2026; maintainers / historical evidence | Archive | [archive/validation/PACKAGING_VALIDATION.md](../../archive/validation/PACKAGING_VALIDATION.md) | Unique dated results/constraints retained; not current instructions |
| `DEPLOYMENT_RELEASE_VALIDATION.md` | Deployment channels and publication — Phase 2; maintainers / historical evidence | Archive | [archive/validation/DEPLOYMENT_RELEASE_VALIDATION.md](../../archive/validation/DEPLOYMENT_RELEASE_VALIDATION.md) | Unique dated results/constraints retained; not current instructions |
| `DEPLOYMENT_VALIDATION.md` | Cross-platform deployment validation — 24 October 2026; maintainers / historical evidence | Archive | [archive/validation/DEPLOYMENT_VALIDATION.md](../../archive/validation/DEPLOYMENT_VALIDATION.md) | Unique dated results/constraints retained; not current instructions |
| `STABILIZATION_VALIDATION.md` | Frozen implementation — stabilization and delivery validation; maintainers / historical evidence | Archive | [archive/validation/STABILIZATION_VALIDATION.md](../../archive/validation/STABILIZATION_VALIDATION.md) | Unique dated results/constraints retained; not current instructions |
| `UI_CONSOLIDATION_VALIDATION.md` | UI consolidation — implementation and validation; maintainers / historical evidence | Archive | [archive/validation/UI_CONSOLIDATION_VALIDATION.md](../../archive/validation/UI_CONSOLIDATION_VALIDATION.md) | Unique dated results/constraints retained; not current instructions |
| `UI_REFINEMENT.md` | UI refinement records; maintainers / historical evidence | Archive | [archive/validation/UI_REFINEMENT.md](../../archive/validation/UI_REFINEMENT.md) | Unique dated results/constraints retained; not current instructions |
| `UI_REFINEMENT_PHASE1.md` | UI refinement: implementation and validation; maintainers / historical evidence | Archive | [archive/validation/UI_REFINEMENT_PHASE1.md](../../archive/validation/UI_REFINEMENT_PHASE1.md) | Unique dated results/constraints retained; not current instructions |
| `VALIDATION.md` | Desktop validation records; maintainers / historical evidence | Archive | [archive/validation/VALIDATION.md](../../archive/validation/VALIDATION.md) | Unique dated results/constraints retained; not current instructions |
| `WINDOWS_PACKAGING.md` | Windows packaging hardening and readiness; maintainers / historical evidence | Archive | [archive/validation/WINDOWS_PACKAGING.md](../../archive/validation/WINDOWS_PACKAGING.md) | Unique dated results/constraints retained; not current instructions |
| `BUILD_PERFORMANCE.md` | Windows build performance; maintainers / historical evidence | Archive | [archive/validation/BUILD_PERFORMANCE.md](../../archive/validation/BUILD_PERFORMANCE.md) | Unique dated results/constraints retained; not current instructions |
| `ACCESS_INVESTIGATION.md` | Local access investigation; maintainers / historical evidence | Archive | [archive/implementation/ACCESS_INVESTIGATION.md](../../archive/implementation/ACCESS_INVESTIGATION.md) | Unique dated results/constraints retained; not current instructions |
| `CLASSIFICATION_ARCHITECTURE.md` | Domains and classification: functional review; maintainers / historical evidence | Archive | [archive/implementation/CLASSIFICATION_ARCHITECTURE.md](../../archive/implementation/CLASSIFICATION_ARCHITECTURE.md) | Unique dated results/constraints retained; not current instructions |
| `REPOSITORY_CLEANUP.md` | Repository cleanup audit — 2026-10-20; maintainers / historical evidence | Archive | [archive/implementation/REPOSITORY_CLEANUP.md](../../archive/implementation/REPOSITORY_CLEANUP.md) | Unique dated results/constraints retained; not current instructions |
| `SETTINGS_REFINEMENT.md` | Settings and role visual refinement; maintainers / historical evidence | Archive | [archive/implementation/SETTINGS_REFINEMENT.md](../../archive/implementation/SETTINGS_REFINEMENT.md) | Unique dated results/constraints retained; not current instructions |
| `README.md` | SAP Lens documentation; investigators | Rewrite | [README.md](../../README.md) | Canonical topic ownership; relative references migrated |

## Ownership and consolidation decisions

- Build commands, environments, receipts, artifact names and troubleshooting now
  have one owner: deployment/BUILD.md. Platform guides own installation/lifecycle.
- Source fields live in data/CSV_SCHEMAS.md. Lifecycle and matching responsibilities
  are separate; old all-or-nothing refresh and no-durable-SAP-snapshot claims were
  corrected against csv_lifecycle.py and deployment/source tests.
- User profile/filter/evidence instructions were updated for the implemented direct
  comparison cells, chips and in-panel release dates. Technical UI ownership stays
  with the existing architecture/component documents.
- Dated CI timing/implementation and legacy release validation were extracted into
  BUILD_PERFORMANCE and WINDOWS_PACKAGING. No performance or native acceptance
  claim is inferred from the migration.
- Native bundle documentation member names remain stable for manifest compatibility.
  Repository source paths changed; the adapter prevents repository-index links from
  accidentally targeting a different packaged README. Four operating guides and
  native documentation assembly are covered by regression tests.

## Migration validation

The docs tree contains **69 Markdown documents**, previously 59. The increase is
from concise directory indexes, explicit Quick Start/Testing/user/release guides
and extracted historical evidence, not competing topic authorities. Only README.md
remains in the docs root. All 69 documents are reachable from that index.

`python scripts/check-docs.py` checked 73 repository Markdown documents including
README/AGENTS/license/examples: zero broken relative links/images/anchors. External
URLs were not fetched. Repository-wide old-path searches found only the root index;
legacy documentation filenames in distribution assembly are intentional stable
bundle members, mapped to current sources.

Focused tests passed: documentation 6, deployment contracts/packaging/release mocks
29, local build/orchestration 28, repository integrity 3, privacy 3, workflows 14,
build reporting 7 (**90 tests**). Actionlint, workflow static checks, PowerShell
parsing/service-helper regressions and Git whitespace checks passed. These are not
fresh production package builds. No browser/application behavior changed, so no
comprehensive browser suite or native packaging was rerun.

No new identities, private exports, infrastructure, credentials or branding assets
were introduced. Accepted historical P-01 remains unchanged. Native Windows EXE,
installer/SCM/WebView2, real systemd/reboot/recovery/UNC and physical mobile-browser
acceptance remain outstanding. No push, workflow dispatch or release was performed.
