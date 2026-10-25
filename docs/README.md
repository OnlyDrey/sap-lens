# SAP Lens documentation

Start with [deployment](DEPLOYMENT.md) for platform selection or
[development](DEVELOPMENT.md) to run from source without an EXE.
Implementation support, successful package builds and native target acceptance
are distinct; use the validation records below for actual results and limitations.

## Using SAP Lens

- [Synthetic examples](../examples/README.md)
- [Role/user/release investigation](ACCESS_INVESTIGATION.md)
- [Dashboard](DASHBOARD.md), [role presentation](ROLE_PRESENTATION.md)
- [User comparison](USER_COMPARISON.md), [Account Review](ACCOUNT_REVIEW.md)
- [Saved Filters](SAVED_FILTERS.md), [investigation filters](INVESTIGATION_FILTERS.md)
- [CSV import](CSV_IMPORT.md), [CSV lifecycle](CSV_DATA_LIFECYCLE.md)
- [Employee Directory](EMPLOYEE_DIRECTORY.md), [Data Health](DATA_HEALTH.md)
- [Configuration and recovery](CONFIGURATION.md), [SAP Modules](MODULES.md)

## Installation, builds and operations

- [Deployment overview](DEPLOYMENT.md), [security requirements](DEPLOYMENT_SECURITY.md)
- [Windows Desktop installation](INSTALLATION_WINDOWS_DESKTOP.md)
- [Windows Server Service](DEPLOYMENT_WINDOWS_SERVER.md)
- [Linux Docker](DEPLOYMENT_LINUX_DOCKER.md)
- [Linux Native/systemd and local browser client](DEPLOYMENT_LINUX_NATIVE.md)
- [Downloadable packages and manual workflow inputs](DEPLOYMENT_PACKAGES.md)
- [Local cross-platform builds](LOCAL_DEPLOYMENT_BUILDS.md)
- [Local Windows builds and prerequisites](LOCAL_WINDOWS_BUILD.md)
- [Windows packaging internals](WINDOWS_PACKAGING.md), [desktop lifecycle](DESKTOP.md)
- [Versioning and legacy desktop releases](RELEASES.md)
- [Signing considerations](WINDOWS_CODE_SIGNING.md), [build timings](BUILD_PERFORMANCE.md)

## Development and shared UI

- [Development commands](DEVELOPMENT.md), [repository instructions](../AGENTS.md)
- [Architecture](ARCHITECTURE.md), [API reference](API_REFERENCE.md)
- [Design system](DESIGN_SYSTEM.md), [Component Library](COMPONENT_LIBRARY.md)
- [Navigation patterns](NAVIGATION_PATTERNS.md), [themes](UX_AND_THEMES.md)
- [CI architecture](CI_ARCHITECTURE.md)
- [Access Insights feasibility](ACCESS_INSIGHTS_FEASIBILITY.md)
- [Future authorization-risk concept](AUTHORIZATION_RISK_ANALYSIS_CONCEPT.md)

## Validation, privacy and historical decisions

- [Current installation/lifecycle validation](INSTALLATION_LIFECYCLE_VALIDATION.md)
- [Local build results](LOCAL_BUILD_VALIDATION.md)
- [Deployment release safeguards](DEPLOYMENT_RELEASE_VALIDATION.md)
- [Packaging checkpoint](PACKAGING_VALIDATION.md), [runtime checkpoint](DEPLOYMENT_VALIDATION.md)
- [UI refinement baseline](UI_REFINEMENT_PHASE1.md), [UI consolidation](UI_CONSOLIDATION_VALIDATION.md)
- [Repository cleanup inventory](REPOSITORY_CLEANUP.md), [privacy/history concerns](PRIVACY.md)
- [Security review](SECURITY_REVIEW.md), [deprecations](DEPRECATIONS.md)
- [Classification compatibility](CLASSIFICATION.md); the
  [older assessment](CLASSIFICATION_ARCHITECTURE.md) is historical, not current UI guidance.

Older validation documents retain the source/phase to which they apply; they do
not certify newer commits or unexecuted Windows/systemd/UNC behavior. No
CHANGELOG.md is maintained: [GitHub Releases](https://github.com/OnlyDrey/sap-lens/releases)
holds release notes/history. A release page link does not imply that every current
local packaging definition has already produced a published artifact.
