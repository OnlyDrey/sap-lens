# Phase 1: Windows feasibility gate

Branch `experiment/go-python`. Not a product migration. No application, installer, deployment, CI or version file was changed.

## Status: INCOMPLETE (Windows execution was not available)

This session ran on Linux. No Windows host, no Windows App Control and no Windows Job Object were available, so **no Windows result exists**. Per the phase rules the phase is reported as incomplete, not successful. Everything below that is marked executed ran on Linux or is static analysis; none of it is Windows validation.

| Acceptance criterion | Status | Basis |
| --- | --- | --- |
| 1. Windows runtime execution verified | NOT MET | Not executed. Harness, bundle and exact commands are ready ([WINDOWS_VALIDATION](WINDOWS_VALIDATION.md)) |
| 2. Go supervision and cleanup correct on Windows | NOT MET | Linux passes (Python suite 70 tests including 1 expected failure for the unremediated bootstrap, plus 10 Go tests). Windows Job Object path never executed |
| 3. Security boundaries intact | PARTLY | Linux boundary tests pass. One test from Phase 0 was vacuous and was fixed (below). Bootstrap finding F1 confirmed ([CAPABILITY_BOOTSTRAP](CAPABILITY_BOOTSTRAP.md)) |
| 4. App Control compatibility shown, or IT-approved path identified | NOT MET | No evidence either way for the bundled tree. Existing repo evidence shows the unsigned product EXE is already blocked on a policy machine. Remediation path is a design question for IT ([APP_CONTROL](APP_CONTROL.md)) |
| 5. Defensible benefit over existing packaging | NOT DEMONSTRATED | No size, file-count or startup advantage; benefit is auditability only ([PACKAGING_COMPARISON](PACKAGING_COMPARISON.md)) |

## What was delivered

| Deliverable | Where |
| --- | --- |
| Windows validation harness (14 stages, PASS / FAIL / BLOCKED / NOT EXECUTED) | `experiments/go-python/windows/Test-WindowsFeasibility.ps1` |
| Read-only App Control diagnostics | `experiments/go-python/windows/Get-AppControlDiagnostics.ps1` |
| Pure-logic classification (host / interpreter / extension / startup / dependency / installer) with self-test | `Phase1Common.ps1`, `Test-Phase1Logic.ps1` |
| Reproducible Windows validation bundle builder | `windows/make_bundle.py` |
| Static PE inventory (Linux) and its result | `windows/pe_inventory.py`, [windows-static-inventory.json](windows-static-inventory.json) |
| Test instructions and evidence template | [WINDOWS_VALIDATION](WINDOWS_VALIDATION.md) |
| App Control findings | [APP_CONTROL](APP_CONTROL.md) |
| Security assessment, reproduction, remediation, regression tests | [CAPABILITY_BOOTSTRAP](CAPABILITY_BOOTSTRAP.md) |
| Packaging comparison | [PACKAGING_COMPARISON](PACKAGING_COMPARISON.md) |
| Signing-aware verification contract (design only) | [SIGNING_CONTRACT](SIGNING_CONTRACT.md) |

## Executed in this session (Linux, not Windows)

| Check | Result |
| --- | --- |
| Branch and commit verified (`experiment/go-python`, `843c005`), tree clean at start | done |
| PowerShell parse of all four scripts (pwsh 7 on Linux) | passed |
| `Test-Phase1Logic.ps1` (87 assertions: classification of synthetic Code Integrity records, bundle and archive verification, process ownership, outcome mapping, child processes, static lint) | passed |
| Harness run on a non-Windows host reports 14 stages NOT EXECUTED, exit code 3 | passed |
| Static scan: harness contains no policy, registry, service, Defender or installer operations; ASCII only | passed |
| Windows bundle built twice on Linux: identical host exe hash and identical runtime archive hash | passed |
| Static PE inventory of the Windows tree (75 images) | done, see APP_CONTROL |
| Capability bootstrap reproduced against the unchanged backend (synthetic data) | confirmed, see CAPABILITY_BOOTSTRAP |
| `python experiments/go-python/run_all.py` (gofmt, vet linux and windows, `go test -race`, cross-builds, 70 Python tests) | passed; govulncheck NOT EXECUTED (database unreachable) |

## Correction to Phase 0

The Phase 0 test "wrong capability is forbidden" sent the header `X-SAP-Lens-Session`; the backend reads `X-SAP-Lens`, so the request was unauthenticated and the test passed vacuously. It now sends the real header and a positive control (the issued capability returns 200). The boundary itself is correct; only the evidence was weak. The Windows harness uses the corrected checks.

## Decision

See [PHASE1_DECISION](PHASE1_DECISION.md).

## Runner hardening (follow-up)

`windows/Run-Phase1.ps1` is the single entry point: it verifies the bundle against a separately supplied checksum, validates and extracts the archive into a fresh run folder, runs the self-test, harness and diagnostics in separate processes, and always writes `run-summary.json` and `.txt`. Result vocabulary: PASS, FAIL, BLOCKED, NOT EXECUTED, HARNESS ERROR. Changes to the existing tools: the harness records a HARNESS ERROR instead of dying without a result, works in Constrained Language Mode far enough to report it, refuses elevated sessions, and stops only processes this run created; the host redirects temp, home and application-data folders into the isolated data directory. Details and commands: [WINDOWS_VALIDATION](WINDOWS_VALIDATION.md). Still NOT EXECUTED on Windows.

## First Windows run and fix (R04)

The first Windows run (Windows PowerShell 5.1) passed R01 to R03 and ended with HARNESS ERROR at R04: `AuthorizationManager check failed.`, exit code 1. Cause (strongly supported by the evidence and the code, not reproduced here): the self-test was started in a `-NonInteractive` child PowerShell; the script carried a Mark-of-the-Web and the policy was `Unrestricted`, which makes PowerShell prompt, and a noninteractive child cannot answer. The unsigned `saplens-host.exe` is separately blocked by App Control (Code Integrity events 3077 and 3033), which is the finding Phase 1 was meant to produce.

Fix: bundle scripts now run in the runner's own session; security refusals are classified NOT EXECUTED with the original error preserved; nothing is unblocked or bypassed. See [WINDOWS_VALIDATION](WINDOWS_VALIDATION.md#script-authorization-and-mark-of-the-web). Not yet re-run on Windows.
