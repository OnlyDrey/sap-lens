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
