# Local build validation record

## Cross-platform implementation checkpoint

The root `build.ps1`/`build.sh` share one Python coordinator and the existing
canonical Windows, Docker and Linux package implementations. Explicit SemVer
local metadata uses schema 3, with no fabricated CI run or tag. Schema 1 developer
and legacy release identities and schema 2 deployment CI identities remain readable.

A local <=24-hour receipt binds the clean Git source, compiled frontend, Python
environment, tool versions, host and successful mandatory checks. CI never falls
back to a local receipt. Only standard POSIX venv interpreter/lib aliases are
allowed while hashing; unrelated symlinks remain rejected. Ordinary Windows
release admission is unchanged. Native local Windows uses its already validated
host environment; CI still installs/audits its Windows-specific dependencies.

Docker packaging now consumes the validated frontend stage. Ordinary source
Docker builds retain their frontend compilation path. Docker context privacy
exclusions remain after the compiled-asset allowlist. All requested targets are
reported independently, including unavailable builders and failed prerequisites.
Cross-host use requires explicit trusted SSH hosts, exact clean commits, host-key
verification and same-invocation manifests; there is no cross-compiler or silent skip.

Targeted local receipt/orchestration tests: **10 passed**. Existing deployment
contracts/publication tests: **29 passed**. PowerShell parsing/static guards,
shell syntax, actionlint, workflow contracts and whitespace checks passed.
A clean-source checkpoint is required before the actual CLI/package integration
run because the build system deliberately refuses uncommitted inputs.

Native Windows/WebView2/SCM/UNC and remote Windows/Linux builder integration have
not been tested here. Final Linux package results will be appended after actual
execution, separately from these unit/static results. No pushes, tags, releases
or workflow dispatches have occurred. Installation feature work is still gated on
this phase's available validation.
