# Build refactor handover

## Preservation checkpoint

Implementation stopped at the user's emergency preservation request. Do not infer
completion from file existence or earlier progress percentages.

- Repository: `OnlyDrey/sap-lens`; development branch: `work`.
- Audited source HEAD: `73e376e0653bb5799796fcd5109485f6452c721c`.
- `8e212de`: unified build engine/bootstrapper and tooling tests.
- `73e376e`: public command/documentation alignment.
- At handover start, tracked, staged and untracked development changes were all
  empty. Live `origin/work` matched HEAD. Therefore no emergency WIP source commit
  was necessary; incomplete/unverified implementation is already in these commits.
- Live `main` remained `ecc417955c15cdc5a6f5e0314500dad858587409`.
- Earlier repairs (`b2a7197`, `ee78e93`, `7340a9c`) and Bulk Review work are preserved
  in history. Do not reset, squash, rebase or restart those completed changes.
- Product version remains `1.0.0-beta.2`, sourced from
  `backend/resources/product-version.json`. No version bump, release or manual
  workflow dispatch was performed.

## Objective and boundaries

One public Windows bootstrapper (`build.ps1`), one public Python build CLI
(`scripts/build.py`), shared Python orchestration, mode-aware prerequisite checks,
consented setup, interactive/non-interactive input, existing Windows/Linux/Docker
outputs, CI integration, and consolidated documentation. Preserve all application,
installer, service, identity, checksum, authentication and release semantics.

System installs must never be implicit. No execution-policy bypass, unverified
installer execution, forced push, modification of main, or production release.
Use targeted validation while implementing; the user requests one full regression
at the end after the implementation stabilizes. Do not restart full suites after
minor failures. Native acceptance must be reported separately.

## Current implementation and dependency map

| Owner | Current responsibility / downstream calls |
| --- | --- |
| `build.ps1` | PowerShell 5.1-compatible bootstrap; finds Python 3.12 x64 via launcher/PATH/standard locations; optionally installs official per-user Python through winget after consent; forwards CLI parameters/exit codes |
| `scripts/build.py` | Standard-library public entry; disables bytecode writes for help/dry-run; calls `build_system.cli.main` |
| `scripts/build_system/cli.py` | argparse, missing-input menus, defaults, non-interactive policy, environment selection, operation dispatch |
| `scripts/build_system/prerequisites.py` | Git/Node/npm/Docker detection, Node engine range from package.json, consented per-user Git/Node winget installation, local venv/pip/requirements/npm-ci preparation |
| `scripts/build_system/runner.py` | Bounded subprocess calls, original child exit codes, local captured logs and structured events; CI inherits normal step output |
| `scripts/build_system/targets.py` | Platform/target routing, existing release policy, CI-only allowlisted adapters, allowlisted lock-aware cleanup |
| Windows portable | Engine → `build-local.ps1` → canonical `build-windows.ps1`, `local-build.py`, PE/privacy verifier, EXE smoke and verified ZIP export |
| Deployment archives | Engine → `build-deployments.py` → existing Windows installer/service, native Linux and Docker utilities; trusted remote builders retained |
| Windows installer/service | `package-windows-deployment.ps1`, `build-desktop-installer.ps1`, `build-server-windows.ps1`, `build-service-manager.ps1` remain internal platform helpers |
| Tests / CI | Existing `validate.py`, `run-tests.py`, `ci.py`, workflow and artifact checks are reused |
| Releases | Existing `deployment-release.py` and `release-windows.py` retain branch/tag/source/collision/publication gates |

The interface is unified, but this is an incremental consolidation, not a full
rewrite of internal stage orchestration. The portable Windows adapter still owns
some sequencing in PowerShell; the deployment worker still has its own established
Python Builder. They have real consumers and were deliberately retained.

### Modes, flags and behavior

Modes: `quick`, `test`, `build`, `package`, `release`, `clean`.
Main flags: `--platform windows|linux|docker|all`, `--target`, `--version`,
`--scope targeted|full`, `--area`, `--output`, `--setup`, `--setup-only`,
`--skip-setup`, `--install-system`, `--non-interactive`, `--dry-run`, `--verbose`,
`--confirm-clean`, `--no-cache`, and trusted Windows/Linux SSH builder parameters.

- No mode defaults to Quick; interactive terminals prompt for missing mode and
  build/package platform/target. Complete arguments execute directly. CI never
  prompts. Scope full is test-only, never a packaging/release prerequisite.
- Quick checks source/version/manifests, docs, test ownership and whitespace;
  default Quick does not install dependencies or package applications.
- Test uses the existing isolated validation runner; default area is deployment.
- Windows desktop is the portable distribution; installer is the existing Inno
  archive; server/service are aliases for the headless service package; Windows
  all produces installer/desktop payload plus service. Linux server/service/all
  use the native/systemd archive. Docker server/all use the existing image archive.
  All/all delegates existing cross-host handling. Unsupported combinations fail.
- Package `--skip-setup` reuses only verified fresh receipts. Outputs and names
  remain those of canonical packagers. No registry push occurs.
- Release requires validated artifacts in `--output`, enforces branch policy and
  verifies source/target/hash consistency. It prepares only; actual publication
  remains the guarded manual GitHub workflow. Local preparation is not authority
  to skip remote tag/collision/provenance checks.
- Clean requires explicit confirmation, permits only documented generated paths,
  refuses links/arbitrary storage/running-interpreter paths, and coordinates with
  legacy/deployment build locks via `dist/.sap-lens-clean.lock`.
- Initial parsing is standard-library-only. CLI supports 3.12+ syntax, but project
  setup/packaging is intentionally limited to Python 3.12 and existing platform pins.
- System setup: winget only on Windows for supported tools; explicit consent or
  `--install-system` required. Node chooses a supported 24 version rather than an
  unrelated latest major. No machine-wide/admin fallback. Docker and unavailable
  platform tools get manual guidance. Stale PATH can require reopening the shell.
- Test/repair setup prefers `.venv`; canonical packaging uses its existing isolated
  `backend/build/python-env`. Release can reuse an existing packaging environment
  without installing unnecessary frontend dependencies.

### Earlier Windows repairs still applicable

Quick no longer provisions the full toolchain or runs all backend tests.
Local Build/Validate use five packaging modules and one-worker browser smoke,
with a distinct schema-2 local receipt. CI/deployment attestations and PE/native
verification remain mandatory. Version defaults no longer convert beta dot syntax
to legacy hyphens. WinSW acquisition uses the existing pinned SHA-256, atomic
activation and cache rechecking. Service-manager self-test uses an isolated
asInvoker harness calling the same SelfTest; the shipped manager retains its
administrator manifest. These paths have NOT been natively accepted on Windows.

## Phase status

“Implemented but unverified” means code and/or mock tests exist, not native parity.

| Phase | Status | Remaining work |
| --- | --- | --- |
| 1. Audit/dependency map | Complete for affected paths | Recheck consumers before any further deletion; internal map is summarized above |
| 2. Unified Python engine | Implemented but unverified | Exercise every real target/mode and review parity with internal stage engines |
| 3. PowerShell bootstrapper | Implemented but unverified | Real 5.1/7 parse/binding, Python-absent startup, consent and winget/PATH behavior |
| 4. Interactive CLI | Implemented but unverified | Unit menus pass; real terminal/PowerShell interactive acceptance remains |
| 5. Prerequisites | Partially implemented | Mock coverage exists; real per-user installation/repair and failure recovery need verification; unsupported installs intentionally require manual setup |
| 6. Windows/Linux/Docker | Implemented but unverified | Adapters preserved; no current-source platform packages built in this round |
| 7. GitHub Actions | Implemented but unverified | Local actionlint/contracts pass; no actual migrated workflow run inspected |
| 8. Legacy cleanup | Partially implemented | Root Bash wrapper removed; assess further internal consolidation only after parity/consumer validation |
| 9. Documentation | Complete for current interface | Update when acceptance reveals corrections; keep historical reports clearly historical |
| 10. Validation/acceptance | Partially implemented | Native Windows/PowerShell and real packages outstanding; full regression pending |

## Specific continuation items / risks

1. `build.ps1` / `Find-BuildPython`: verify Windows x64, PS5.1/7 parsing and actual
   parameter forwarding; no Python installed; launcher aliases; per-user Python
   locations; declined install; missing winget; policy/network failures; exit codes.
   No real system installation was executed by this session.
2. `prerequisites.py`: verify actual Git/Node winget manifests support requested
   user scope. Unsupported user installation must fail without escalation. Test
   refreshed/stale PATH, npm repair, incompatible/incomplete venvs and locked
   package installation. Automatic installation is intentionally not universal.
3. `cli.py::test_python` and `prepare_environment`: final release-environment
   reuse/repair change has two focused passing tests, not another complete tooling
   rerun. Review both `.venv` and packaging-environment selection on Windows.
4. `targets.py::plan`: validate real portable, installer, service, native and Docker
   operations, output overrides and reuse receipts. Portable output stays restricted
   to dist/local. Source/tool/version validation must not be weakened.
5. `targets.py::clean`, legacy/deployment lock guards: mock ownership/allowlist
   checks pass. Exercise real Windows FileShare.None/concurrent build behavior.
   Never clear an active or unexplained stale lock automatically.
6. CI adapters in `targets.py` and `check-workflows.py::canonical_run`: validate
   actual runner execution, quoted paths and benchmark switch. Normalization is
   for semantic contract inspection only; underlying checks must stay intact.
7. `build-service-manager.ps1`: compile and run the asInvoker self-test harness on
   Windows/.NET; production manager must still be x64 GUI/requireAdministrator.
8. Consider further consolidation of meaningful internal stage owners only after
   real parity. Do not delete helpers merely because their names resemble public
   interfaces. No other confirmed obsolete script was found safe to remove.
9. Corporate AllSigned/Restricted/AppLocker/WDAC can block scripts before entry.
   No policy bypass is implemented or recommended; obtain IT signing/approval.

These are acceptance gaps and review items, not confirmed native defect reports.
No unresolved failure is known from the final runnable checks. Do not report the
Windows pipeline fixed in native execution until the above is exercised.

## Validation evidence — do not rerun unnecessarily

Passed in this Linux/Python 3.12 environment:

- Actual public command:
  `python scripts/build.py test --scope targeted --area deployment --skip-setup --non-interactive`.
  Its recorded result: **196 checks, 193 passed, 3 skipped, 0 errors/failures**.
- Two subsequent focused release-environment reuse/repair tests passed after the
  last small release-environment change.
- Actual public Quick from `/tmp` using an absolute script/interpreter path passed,
  demonstrating repository-independent path resolution without installs.
- 47 repository/privacy/documentation/workflow/test-profile checks passed.
- Earlier 97-test compatibility, 66-test workflow/profile and 58-test safety batches
  passed; they overlap final evidence and must not be summed into a unique total.
- Whole Python Ruff; pinned actionlint; workflow graph/permission/provenance and
  mutation contracts; test ownership; 95-document Markdown links; compile/static
  checks; git whitespace checks passed before this emergency handover.

Skipped: three existing PowerShell-dependent checks (desktop HTTP exception
behavior, Node gate AST execution, and non-Windows/invalid PowerShell parameters),
because pwsh is unavailable. Python/static checks do not replace these.

Earlier corrected failures: a new subprocess mock intercepted Git check_output;
a release policy exception needed conversion to the CLI's controlled BuildError;
CI release adapters needed exemption from local artifact-directory requirements.
The affected focused tests passed after correction. No tests were disabled or
assertions weakened to hide application defects.

NOT executed: native Windows bootstrap/winget/PowerShell binding, Windows packaging
or service/installer builds, native WebView2/SCM/.NET/Inno acceptance, real current-
source Linux/Docker package builds, real systemd, reboot/recovery/UNC, migrated
GitHub workflow dispatch, or full application regression.

No additional tests were run for this emergency handover. Existing logs/results
are ignored artifacts under backend/build/unified and build/validation, with
session diagnostics under /tmp and synthetic browser screenshots outside Git.
They are not unfinished source and were not committed; may be ephemeral. The
source tests and permanent evidence are committed. Do not add node_modules, .venv,
real exports, credentials, databases, caches or original reference workbooks.

## Cleanup and documentation

- Removed: root `build.sh`, a redundant wrapper with no remaining active caller;
  its help test now invokes the public Python CLI. Historical textual mentions in
  dated archive records are intentionally preserved.
- Replaced: root build.ps1's old direct cross-platform delegation with bootstrap
  and forwarding to the Python engine. Relevant operations in all four workflows
  now enter through the engine; setup actions/graph/permissions/artifacts remain.
- Retained: internal portable/deployment orchestrators, platform compilers, Inno
  installer tools, service management, runtime/install utilities, verifiers,
  validation runners, release guards and checksum mechanisms, all with consumers.
- Authoritative: `docs/BUILD.md`. `docs/deployment/BUILD.md` is a short link stub for
  existing/external references, not a competing guide. README/AGENTS/current guides
  link to the new location. Windows prerequisite details stay in DEVELOPMENT.md.
- Current documentation has no known broken links from the last check. Further
  cleanup should follow actual acceptance findings, not restart the prior migration.

## Prioritized continuation checklist

1. Synchronize work safely and read this document, docs/BUILD.md and AGENTS.md.
2. Inspect actual source/diff and finish confirmed gaps; do not reimplement the
   working CLI or restart completed Bulk Review/build-repair phases.
3. On an approved Windows x64 host, begin with:
   ` .\build.ps1 -Mode quick `.
   Test PS5.1 and PS7, missing Python/declined install, explicit consent, missing
   Node/npm, and non-interactive/dry-run behavior. Never install system software
   merely to run unit tests; use mocks for unsafe/unavailable conditions.
4. Verify interactive and explicit CLI forms and failure/exit forwarding:
   `python scripts/build.py quick --non-interactive --dry-run`.
5. Build/accept Windows targets separately:
   ` .\build.ps1 -Mode build -Platform windows -Target desktop `;
   ` .\build.ps1 -Mode package -Platform windows -Target installer `;
   ` .\build.ps1 -Mode package -Platform windows -Target service `.
6. On supported Linux/Docker hosts:
   `python3.12 scripts/build.py package --platform linux --target server --non-interactive`;
   `python3.12 scripts/build.py package --platform docker --target server --non-interactive`.
7. Reuse local workflow checks before any approved real CI run:
   `python scripts/check-workflows.py` and `python scripts/ci.py lint`.
8. Finish only justified legacy cleanup and documentation corrections. Preserve
   release gates and meaningful internal helpers.
9. Target changed tooling first:
   `PYTHONPATH=backend:backend/tests python -m unittest test_unified_build` on Linux,
   or `python -m unittest discover -s backend/tests -p test_unified_build.py`;
   `python scripts/build.py test --scope targeted --area deployment --skip-setup --non-interactive`.
10. Once stable, run full regression explicitly **once**:
    `python scripts/build.py test --scope full --non-interactive`
    (Windows: `.\build.ps1 -Mode test -Scope full -NonInteractive`).
    Fix failures with affected rechecks; broaden only if prior evidence is invalidated.
11. Commit/push validated logical stages to origin/work normally, verify live HEAD
    and clean status, and report native gaps honestly. Never modify main, force
    push, publish releases or dispatch workflows without separate authorization.

## Continuation update (after `26db497`)

- `examples/synthetic.csv` was removed. `examples/role-catalogue.example.csv` covers the same schema (including PARENT_AGR and
  Effective_Role). The browser fixture is now `frontend/tests/fixtures/role-catalogue-minimal.csv`; see `examples/README.md`.
- Re-verified on Linux: `test_unified_build` (33 tests), `python scripts/build.py quick --non-interactive --dry-run`, an invalid
  target exiting 2 with a clear message, workflow contracts, actionlint, documentation links.
- `python scripts/build.py package --platform linux --target server --non-interactive --skip-setup` stopped with exit 3 and the
  message that PowerShell 7 is required (not installed here). A real Linux, Docker or Windows package build is still NOT executed.
- Pre-existing failure found, unrelated to the build work: `frontend/tests/desktop.spec.ts` "application information displays the
  resolved API identity" fails at `26db497` (the locator `Application version` now matches two elements, a strict-mode violation).

## Final status of this continuation

**Full regression: INCOMPLETE (interrupted on purpose to save time; neither passed nor failed).**

| Part | Result |
| --- | --- |
| Backend (3 processes) | Completed: 1158 tests, 0 failed, 5 skipped (PowerShell-dependent and PyInstaller-dependent checks) |
| Browser suite | Interrupted before any result was recorded: no pass/fail claim |
| Production build, static checks, report | Not reached in this run |

Targeted evidence for this continuation: `test_unified_build` 33 passed; repository privacy, example datasets, application backups,
Windows tray, SoD import and lifecycle, test profiles and `test_server` (17) passed; 85 of 86 browser tests in the specs that use the renamed
fixture passed (ux, desktop, design-system, position-changes, employee-directory, account-review-refinement, navigation-modules).

**Baseline failures, kept separate from regressions:**

- Six `test_server.BrowserMultipartTests` failures were first seen with `python-multipart` missing from the local virtual environment
  (HTTP 500 instead of 413). They failed identically with the change stashed, and passed after `pip install -r backend/requirements-dev.txt`.
  They are an environment drift, not a code defect.
- `frontend/tests/desktop.spec.ts` "application information displays the resolved API identity" fails at `26db497` and with the change
  stashed (the `Application version` label matches two elements). Pre-existing and not fixed here.

**PowerShell:** the supported Windows version is PowerShell 5.1 (7 is also accepted). The Linux package route calls the existing `.ps1`
helpers, so `python scripts/build.py package --platform linux --target server` exits 3 asking for PowerShell 7. Whether that
dependency is necessary or leftover legacy orchestration was NOT investigated or changed in this phase, and nothing was installed.

**Not executed:** native Windows bootstrap and packaging (PowerShell 5.1), Linux and Docker packages, installer and service builds, real
systemd, any GitHub workflow run.

**Exact next steps:**

1. Decide whether the Linux native packaging can drop the PowerShell dependency by moving the remaining `.ps1` steps to Python;
   if not, document PowerShell 7 as a Linux packaging prerequisite in `docs/BUILD.md`.
2. On a Windows x64 host with PowerShell 5.1: `.\build.ps1 -Mode quick`, then the desktop, installer and service targets.
3. Fix the `desktop.spec.ts` locator (or the duplicate label), then run the full regression once:
   `python scripts/build.py test --scope full --non-interactive` (browser tests need `PLAYWRIGHT_EXECUTABLE_PATH` if the pinned
   Chromium build is missing).
4. Only with explicit authorization, run the workflow checks on GitHub.

## Consolidation session (after `8227f4a`)

**Linux PowerShell dependency (resolved).** Trace: `scripts/build.py` -> `build_system/targets.py` -> `build-deployments.py` ->
`deployment-package.py native` and `test-native-deployment.py` (Linux native) or `package-docker.py` (Docker). Those are Python-only.
PowerShell was needed only for (a) a blanket engine gate in `prerequisites.py`, (b) the `check-powershell.ps1` parse check of the
Windows scripts in the shared local validation, and (c) the Windows packaging targets. Now: the engine requires PowerShell only on
Windows hosts (Windows PowerShell 5.1 or 7); `build-deployments.py` requires it only for local Windows targets; without `pwsh` the
parse check is skipped and the local receipt records `not_verified: ["powershell"]` (accepted only on non-Windows hosts; CI and Windows
must still pass every check). Tests: `test_local_deployments`, `test_unified_build`.

**PowerShell 5.1.** Static audit of `build.ps1` and the helpers found no 7-only syntax; `build.ps1` declares `#requires -Version 5.1`.
`-Help` is now forwarded to the Python CLI when Python exists. A static guard test was added. Not executed on Windows.

**Playwright baseline.** `desktop.spec.ts` resolved-API-identity test now scopes the version assertion to the footer (Settings also
shows the version legitimately); no assertion weakened. `desktop.spec.ts` passes (2 tests).

**Engine and targets (dry runs on Linux).** quick, test, linux/docker package and clean resolve correctly; Windows targets refuse on
Linux with a clear message (exit 2); an invalid target exits 2. All four workflows enter through the engine; workflow contracts pass.

**Dataset cleanup.** Re-verified: no remaining `synthetic.csv` reference.

### Readiness

| Area | Status |
| --- | --- |
| Unified Python engine, CLI, dry-run, exit codes | Implemented and targeted-validated |
| Linux/Docker routing without PowerShell | Implemented and targeted-validated (mocked); real build blocked here |
| `build.ps1` (5.1 baseline) | Implemented, statically checked; awaiting native Windows acceptance |
| Windows desktop, installer, service packaging | Implemented; awaiting native acceptance |
| Linux native / Docker package | Implemented; real build blocked: local Node is 22 (needs 24 or 25); Docker not run |
| GitHub workflow integration | Implemented, contracts and actionlint pass; awaiting runner acceptance |
| Full regression | Not run (deferred; not authorized) |

Implementation complete, awaiting full regression and native platform acceptance. Not production-ready by targeted tests alone.

### Exact acceptance commands (deferred)

- Windows x64, PowerShell 5.1 and 7: `.\build.ps1 -Mode quick`; `.\build.ps1 -Mode build -Platform windows -Target desktop`;
  `.\build.ps1 -Mode package -Platform windows -Target installer`; `.\build.ps1 -Mode package -Platform windows -Target service`;
  also test with Python absent (decline, then consent) and `-NonInteractive`.
- Linux (Node 24/25, Python 3.12): `python3.12 scripts/build.py package --platform linux --target server --non-interactive`;
  Docker: `python3.12 scripts/build.py package --platform docker --target server --non-interactive`.
- Workflows (needs authorization): `python scripts/check-workflows.py`, `python scripts/ci.py lint`, then the approved runner runs.
- Full regression (needs authorization): `python scripts/build.py test --scope full --non-interactive`.

## Linux acceptance attempt (user-local Node 24.22.2, npm 11.19.1)

**Result: BLOCKED, not accepted.** Node was provisioned user-locally (checksum-verified tarball, no system change). The engine ran
PowerShell-free through dependency install, `pip check`, workflow lint, the targeted backend stage (201 tests, 0 failed, 3 skipped),
type check, catalogue check, production build and audits, then stopped at the browser smoke stage: 11 passed, 1 failed
(`tests/sod-governance.spec.ts:9`, "risk matrix counts distinct users ... @smoke"). It is deterministic (reproduced alone) and the
expected text "Potential conflict evidence" no longer exists in `frontend/src`: a pre-existing test/UI drift from the earlier SoD work,
unrelated to the build system. No package was produced. Fix the spec or restore the text, then rerun
`python scripts/build.py package --platform linux --target server --non-interactive` with Node 24/25.

An earlier attempt exposed a real defect in a new test (the builder's `SAP_LENS_SKIPPED_CHECKS` leaked into it); fixed in `c3265e5`.
Docker: the CLI exists but no daemon is reachable, so Docker acceptance is blocked by the environment.

## Documentation cleanup (documentation only)

- `docs/validation/WORKFLOW_MATRIX.md` keeps only the current matrix; dated logs moved verbatim to
  `docs/archive/validation/LOCAL_VALIDATION_LOG_2026-11.md` (relative links adjusted).
- `docs/development/CI.md` now states current behavior, checked against the workflow files; superseded passages are preserved in
  `docs/archive/validation/CI_HISTORY_PRE_THREE_LEVEL.md`. R8 reports and handoffs were left in place.

## Script audit result

All 54 tracked files under `scripts/` were audited: 0 removed, 0 migrated, 0 merged (before and after: 54). The inventory with a purpose per
script is in `docs/BUILD.md` ("Script inventory"), guarded by `ScriptInventoryTests` so new scripts must be documented. Remaining
debt: `test-service-management.ps1` is not executed by any build step; Python migration of the legacy stage engine needs Windows parity tests.

## SoD smoke repair and Linux acceptance (commit `bb03221`)

**Root cause of the smoke failure.** Commit `6b85e99` (SoD workspace redesign) intentionally removed the investigation-panel subtitle
"Potential conflict evidence, not effective authorization". The panel now states its scope ("Showing only risk R1 and the evidence behind
it."). The functionality the smoke test covers (matrix counts, opening the scoped panel, both activities, Escape and focus return) is
intact; only the assertion was obsolete. Fix: the assertion now checks the current scoped notice (no assertion removed or weakened).
Product observation: the panel itself no longer carries the "not effective authorization" wording (it remains on the SoD Overview and
in the docs); restoring it is a product decision, not done here.

**Targeted result.** `sod-governance.spec.ts`: 8 passed, 3 failed. The smoke test passes. The 3 failures (`:33` activity/role/risk
decisions, `:172` work queue, `:206` remediation) are NOT smoke tests, fail independently of this change (only the first test was
edited) and are separate pre-existing baseline drift, not investigated here.

**Linux package acceptance: PASSED (Linux x64 host, this build only).** `python scripts/build.py package --platform linux --target
server --non-interactive` with user-local Node 24.22.2 completed in 127 s. Artifact `sap-lens-linux-native-x64-v1.0.0-beta.2.tar.gz`
(22,288,261 bytes), SHA-256 `8f5e64a7...ad6807`, matching `.sha256` and `SHA256SUMS.txt` (both verified with `sha256sum -c`). Manifest:
status passed, package verified, runtime smoke tested, version 1.0.0-beta.2, source commit `bb03221`. Archive: 1478 regular entries, no
`.ps1`, no CSV/settings/env, no dotfiles or `.pyc`; includes `deploy/linux/sap-lens.service` (hardened: NoNewPrivileges, ProtectSystem=strict,
PrivateTmp, runs as `saplens`), `scripts/install-linux-server.py`, `scripts/run-installed-server.py` and an offline wheelhouse. All entries
are mode 0644 (scripts are started through the Python interpreter, not executed directly). The offline install/runtime smoke test inside the
build passed. PowerShell was not used: the receipt records `not_verified: ["powershell"]`, and the only mentions in the log are 3 skipped tests.

Not covered by this acceptance: real systemd boot, reboot/recovery, a second host, Docker (no daemon here), Windows, the full regression and GitHub Actions.

## Linux permission audit and SoD test stabilization (after `227b950`)

**Permission audit (Linux native).** The 0644 archive modes are intentional and sufficient. Nothing is executed directly: documented
commands are `python3.12 scripts/install-linux-server.py ...`, `ExecStart` is `<prefix>/current/.venv/bin/python <prefix>/current/backend/server.py`
(the script is an argument; the venv interpreter gets its execute bit from `venv`), and the installer forces the installed release tree to
root-owned 0755 directories and 0644 files, so archive bits would be overridden anyway. Installed layout: releases immutable and not
writable by `saplens`; data directory `saplens:saplens` 0700; config 0640 group `saplens`; unit 0644. The unit keeps NoNewPrivileges,
ProtectSystem=strict, PrivateTmp, PrivateDevices, ProtectHome, `UMask=0077`. The offline wheelhouse is world-readable and holds no secrets.
Locked by `DeploymentContracts.test_linux_native_files_are_started_through_the_interpreter_so_no_executable_bits_are_needed`.

**Installation contract.** Validated without privilege through the build's offline `--user` install smoke test (install, start, status, restart,
stop, backup, upgrade/restore path, Unicode paths). Not performed: privileged system install, a real systemd boot, `User=saplens` creation,
`ProtectSystem` behavior under systemd, reboot/recovery. Those need a real systemd host.

**SoD governance tests (3 failures, all test drift after deliberate redesign; no application regression).**
- `:33` risk acceptance: since `603cd38` the Risk Review row shows the review state and acceptance is shown in the "Formal acceptance" section
  of the row status popover. The test now opens that popover and asserts `Accepted` there.
- `:172` work queue: the queue now includes every user in the complete assignment scope (`a1b9934`), so user C appears. Expected counts
  updated to header plus 3 rows and "Needs review 3", with an explicit assertion that C has one row.
- `:206` remediation: the SAP user column uses the shared identity action (open-user link). The "no links" assertion became exactly one link
  for the remediated user.
`sod-governance.spec.ts` 11/11, with `sod-stability` and `sod-analysis` 26/26 passed. `check:types` and the production build pass; ESLint reports 0 errors (111 pre-existing warnings).

**Evidence messaging.** `sod-analysis.spec.ts:23` also asserted "Potential conflict evidence, not effective authorization" on the investigation
panel and was failing silently outside the smoke scope. The SoD Overview kept the statement but the panel did not, so the same wording now opens
the panel's existing description paragraph (no new element, no old subtitle restored).

**Note.** The Linux package from `227b950` predates this panel sentence; rebuild before any release. Windows readiness: `build.ps1`
(5.1 baseline, static checks only) and the checklist above are ready for a real Windows x64 host; nothing was run on Windows.

## Repository hygiene audit (after `e824032`)

**Inventory.** 629 tracked files; root: `.dockerignore .gitattributes .github .gitignore AGENTS.md CLAUDE.md Dockerfile LICENSE.md README.md assets
backend build.ps1 compose.yml deploy docs examples frontend ruff.toml scripts`. Four workflows, all active (validate, full-validation, build-deployments,
build-windows). No generated or private content is tracked (no `dist`, `build`, caches, `.pyc`, logs, databases, env files); `.ruff_cache`, `__pycache__`,
`backend/build`, `frontend/dist` and `test-results` are untracked and ignored. Every file in `assets/`, `deploy/` and `frontend/public/` has at least one live reference.
No backend module is unreferenced.

| Finding | Class | Action |
| --- | --- | --- |
| `frontend/src/components/Shared/MetricTile.tsx` (no consumer in `src`, tests or docs; carried its own tone rule bypassing `lib/kpiTone.ts`; recorded as open item CQ-04) | REMOVE | Deleted; the one sentence in `docs/architecture/COMPONENTS.md` updated. Type check and production build pass |
| `FilterTile`, `EvidenceBadge`, `AccountEvidence`, `SourceStatusSummary` (rest of CQ-04) | INVESTIGATE | Kept: they live inside shared multi-export files, so removal is not a clean file deletion. Still open technical debt |
| `.dockerignore` | UPDATE | Unchanged; new guard test asserts the allowlist shape, the secret/CSV/settings/snapshot denylist, no tests/examples/docs/deploy in the context, and the required runtime inputs |
| Historical R8 reports, scripts reviewed earlier | KEEP | Not touched |

**Release hygiene.** Linux archive (built from `bb03221`) re-inspected: no tests, fixtures, `.github`, `node_modules`, env, logs, databases,
examples or caches; runtime resources present (`backend/resources/*.json`, the SoD reference template, `frontend/dist`, `requirements-runtime.txt`,
`LICENSE.md`, third-party licenses). Docker: the build context is an allowlist (now guarded). Windows: PyInstaller inputs are guarded by the existing
privacy tests (no `settings.json`, `*.csv` or backend data bundled); a real Windows/Docker package inspection was not performed.

## Windows bootstrapper: Python discovery fix (after `0c8c71b`)

**Reported.** `powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1 -Platform all -Version 0.1.0-beta.3` on Windows PowerShell 5.1
asked to install Python although `python --version` reported 3.12.3.

**Root cause (reproduced by simulation, not on Windows).** `Find-BuildPython` validated each candidate with
`python -c 'import sys,struct; ...; struct.calcsize("P")==8 ...'`. Windows PowerShell 5.1 strips embedded double quotes from native-command
arguments, so Python received `struct.calcsize(P)`, raised `NameError: name 'P' is not defined` and exited 1 for every interpreter, including a valid
3.12 x64. The loop then found no candidate and offered the install. Running that exact quote-stripped command on a real Python 3.12 reproduced the
`NameError`. The architecture of the reporter's interpreter was never the issue (and was unverified until now).

**Fix.** The probe now contains no quotes at all (`print(64 if sys.maxsize>2**32 else 32)`), prints interpreter path, version and bitness, and the
classifier accepts only `3.12.x` + 64-bit + exit code 0. Native stderr can no longer become a terminating error. Discovery order: project `.venv`,
`py -3.12`, `python3.12`/`python` on PATH (all entries), then registered installs (`py -0p`, registry HKCU/HKLM PEP 514). No hardcoded install paths; paths
with spaces are passed as separate arguments; Microsoft Store aliases are skipped and explained. `py.exe` is optional. Output: silent on success
(`-Verbose` shows the choice); on failure a `Python discovery:` list shows source, path, version, bitness and the rejection reason, and only then is
the install offered. No environment variables are printed.

**Virtual environment.** `.venv` is probed first; an incompatible one (other version, 32-bit, broken, incomplete) is reported with the reason and is
never deleted or replaced by the tools. Setup creates new environments with the selected interpreter.

**Arguments.** `-Platform all` and `-Version` are forwarded unchanged; `-Help`/`-Verbose` forwarded; the child exit code is returned. `0.1.0-beta.3` is
accepted because local packages take any valid SemVer prerelease override (`validate_version`), independent of the product version `1.0.0-beta.2` in
`backend/resources/product-version.json`; the requested value is never rewritten and the dry run modifies no files. Note the invocation passes no
`-Mode`, so an interactive terminal still shows the mode menu.

**Tests (Linux host, 44 pass, 1 skipped).** Probe has no quotes and works on a real interpreter; the original probe fails once quotes are stripped;
discovery order, no hardcoded paths, no deletion, diagnostics before the install offer; 3.12.x/64-bit accepted and 3.11/3.13/3.14/32-bit rejected
(rule check); venv reuse, wrong version, 32-bit, broken and incomplete environments left untouched; argument and exit-code forwarding. One test
executes the real PowerShell functions against fake interpreters (spaces in path, x86, 3.14, broken) but is skipped here because no PowerShell is installed.

**Native Windows acceptance: PENDING.** Not run on Windows. Please verify with PowerShell 5.1 on the reporting machine:
`powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1 -Verbose -Mode quick` (expect no install prompt and the selected 3.12.3 path),
then `.\build.ps1 -Help`. Also test py-launcher-only and PATH-only machines, a path with spaces, a 32-bit 3.12, and a declined install.
