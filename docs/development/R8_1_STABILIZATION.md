# R8.1 stabilization record

Follow-up to the R8 audit ([code](CODE_REVIEW_R8.md), [security](SECURITY_REVIEW_R8.md),
[test performance](TEST_PERFORMANCE_R8.md)). Sections are added per phase; dated 1 November 2026.

## Phase 1: verified baseline

| Item | Verified result |
| --- | --- |
| Branch and commit | `work` at `174b19c`, equal to `origin/work`, clean tree, no running test servers |
| Fast Validation run 154 (`174b19c`) | success (GitHub Actions) |
| Run 153 (`39c9c7e`), run 152 (`7826b4f`) | success |
| Run 151 (`5569f90`) | failure, cause below |
| Execution settings (R8) | backend 849 tests (3 skipped), browser 716 tests, 1 worker per Playwright process, no retries |

**Run 151 cause (confirmed from the job log).** The documentation commit moved `UI_UX_GAP_AUDIT.md` to the archive, while the
tracker row `UI-014` still referenced the old path. `test_validation_tracker.test_ids_are_stable_and_every_reference_exists`
failed (1 of 846 tests); everything else, including `check-docs.py`, passed. The next commit (`7826b4f`) migrated the tracker and was green.
It was a real regression in a pushed commit, not an environment flake. The lesson for Fast Validation: a phase that moves or renames
documentation must run the repository and tracker tests, not only `check-docs.py`.

**Process cleanup of the 161-failure R8 run.** The failures came from a broad `pkill -f playwright` issued by the assistant from a shell that
matched its own command line, not from repository code. A search of all scripts, workflows, tests and documentation found no `pkill`,
`killall` or `kill -9`; the only process signals are `terminate()`/`SIGTERM` on child processes the code started itself
(`test_server.py`, `install-linux-server.py`, `test-native-deployment.py`, `server-deployment.spec.ts`).

**Confirmed defect found while auditing: leaked test directories.** Playwright stops its `webServer` with SIGKILL unless
`gracefulShutdown` is set, so `serve-browser-tests.py` never removed its temporary configuration directory. The sandbox held 616
`sap-lens-browser-*` directories totalling 1.9 GB. Fixes:

- `playwright.config.ts`: `gracefulShutdown: { signal: 'SIGTERM', timeout: 10_000 }`.
- `scripts/serve-browser-tests.py`: handles SIGTERM (uvicorn re-raises the signal after shutdown, which would skip the cleanup), writes an
  owner marker, and at start removes only directories whose owner process no longer exists (or marker-less ones older than 6 hours). It never
  signals a process, and on Windows it keeps directories because `os.kill` would terminate there.
- `scripts/run-tests.py`: before sharding, reports ports already in use and stops with a message. It never stops a process it did not start.
- Tests in `backend/tests/test_test_profiles.py`: stale-directory sweep, busy-port report, SIGTERM cleanup of the real server.

After the change a Playwright run leaves no directory and no process behind (checked with a two-test spec).

## Phase 2: security hardening

| Finding | Change | Evidence |
| --- | --- | --- |
| SEC-02 failed Basic sign-ins | `AuthThrottle` in `backend/deployment.py`, applied in the server middleware: per-client counters, doubling cooldown, 429 with `Retry-After`, bounded state (1024 clients), trusted-proxy aware client identity, both credential parts always compared | `test_auth_throttle` (18 tests: threshold, expiry, cap, window, success reset, bounded state under flooding, 16-thread exact counting, spoofed `X-Forwarded-For`, IPv6 /64, malformed headers, log content, configuration bounds, local and desktop modes unthrottled) |
| SEC-03 secret file | `check_secret_permissions`: owner-only by default; group read only with `SAP_LENS_AUTH_SECRET_GROUP_READ=1` and a group the service account belongs to; other access and group write or execute always refused; judged on the opened file; never chmod; `--init-secret` creates the file with mode 0600 atomically | `test_secret_file_policy` (8 tests incl. symlink target, proxy mode, umask 0 creation, no overwrite) |
| SEC-04 headers | Added `Permissions-Policy` (no device capabilities) and CSP `object-src 'none'`; `unsafe-inline` styles stay (measured portal coordinates); HSTS stays at the TLS proxy because the application also serves HTTP loopback and cannot know that the proxy terminates TLS for every client | `test_security_surface` |
| SEC-07 systemd | Added `PrivateDevices`, `ProtectKernelTunables`, `ProtectKernelModules`, `ProtectControlGroups`, `LockPersonality`, `RestrictRealtime`, `RestrictSUIDSGID`, `RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6`. Not added: `SystemCallFilter` and `MemoryDenyWriteExecute` (can break Python extensions; need a real boot) | `systemd-analyze verify` accepts the unit; `test_deployment_contracts`. A real systemd start is not tested here |

Compatibility: an existing 0640 secret now stops the server at start with a message that names the file, its mode and both remedies. The Docker installer
and `compose.yml` keep their 0640 file (the container user is not the host owner) and set the opt-in. SEC-05 and SEC-06 stay accepted. Windows ACLs are applied
by service provisioning and are not verified by the runtime.

The tests found one defect in the first implementation: `AuthThrottle` defines `__len__`, so an empty throttle was falsy and the middleware skipped it; the
middleware now compares with `is not None`.

## Phase 3: SoD descriptions in PDF and DOCX reports

- `sod_metadata.frozen` stores a compact copy of the resolved descriptions (risks and activities of the snapshot, origins and differing alternates included) in every newly captured review snapshot (`metadata`, version 1). It is part of the immutable, content-addressed snapshot.
- `sod_metadata.for_period` returns that copy (`basis: captured`) or, for a snapshot captured before R8.1, only the local business text frozen with its risk records (`basis: legacy`). Imported descriptions are never reconstructed for a legacy period and current values are never shown as history.
- `sod_reports` uses the same resolver output in the formal report (risk table in the findings section, activity table and source legend in the appendices) and in the remediation report (terms table; current evidence is labelled as current). Reports for data without descriptions keep their tables and text.
- Compatibility: no migration; existing snapshots, decisions, approvals and checksums are untouched. Detection reads no description (`test_detection_results_do_not_depend_on_descriptions`).
- Evidence: `test_sod_report_metadata` (13 tests: imported, local fallback, missing, differing alternates, source labels, approved-period immutability and identical model checksum, open period, legacy snapshot, plain datasets, special characters, long text, markup escaping, PDF font limit, remediation current versus frozen) and all 275 SoD backend tests.
- Limit: a description with characters outside the bundled PDF font fails the PDF with the existing explicit 422 message; the DOCX is unaffected.

## Phase 4: Ruff and ESLint

| Tool | Configuration | Result |
| --- | --- | --- |
| Ruff 0.17.3 | `ruff.toml`: correctness rules only (see [Testing](TESTING.md#linting)); frontend, docs, deploy and build output excluded | 193 candidate findings were triaged. Fixed: 28 unused imports, 3 f-strings without placeholders, 3 unused variables, 9 `raise` without `from` (all hide internal detail on purpose, so `from None`), 1 useless expression (the `url.port` validation is now an explicit assignment), 4 loop-variable closures in a test. Silenced on the line with a reason: 1 blocking path call in a bounded upload staging scan, 1 `yaml.load` with a `BaseLoader` subclass. Not selected on purpose: `B008` (71 FastAPI default-call idiom hits), `PLW1510`, `B905`, formatting rules. Result: clean |
| ESLint 10.14.0 + typescript-eslint 8.72.1 + react-hooks 7.1.1 | `frontend/eslint.config.js`, `npm run lint` | 145 findings at first. Fixed or justified: unused imports and variables in 8 specs, a literal BOM made explicit, an unused initial assignment and a confusing line break in `IconPicker`, two regex escapes, a justified control-character rule and an async timer callback with its own `try/catch`. Browser globals for `public/theme.js`, `_` prefix for intentionally unused parameters. Result: 0 errors, 111 warnings (30 `exhaustive-deps` in 16 `src` files, 81 `no-explicit-any` in `tests`), enforced as a ceiling |

CI: both workflows gained `ruff` and `eslint` steps (reported through `CI_REQUIRED`; `check-workflows.py` requires them), `ruff` is pinned in `requirements-dev.txt`, and `run-tests.py` runs both in its static stage.
`npm audit --omit=dev` stays clean. `npm audit` for development dependencies reports 11 moderate advisories, all from `minimatch` below 11.0.1 inside the ESLint toolchain (a denial of service for untrusted glob patterns, which
ESLint never receives here); the suggested automatic fix is a downgrade to ESLint 4 and is not applied. They are recorded, not suppressed.

Existing debt (CQ-04 to CQ-06) was re-verified, not changed: `MetricTile`, `FilterTile`, `EvidenceBadge`, `AccountEvidence` and `SourceStatusSummary` are still defined without a consumer outside their own files;
`SettingsView.tsx` has 1158 lines and three other components exceed 640 lines; the long backend functions are unchanged. Recommendation: remove or adopt the five components together with their documentation rows, and split `SettingsView`
by tab when a feature next touches it. Deferred: they need behaviour-preserving refactors with browser coverage, not lint fixes.

## Phase 5: test execution

| Change | Detail |
| --- | --- |
| Backend | Unchanged default: `auto` runs `min(3, CPUs)` processes (each test builds its own storage, so there is no shared state). The R8 evidence run used `--jobs 1`, which also serialised the backend: 849 tests took 170 s serially and 65 s with three processes; the 891 tests of R8.1 take 74 s |
| Browser processes | `--browser-jobs N|auto` or `SAP_LENS_BROWSER_JOBS`, at most 3; `auto` = CPUs minus one, 1 to 3 (a 1 or 2 CPU host stays at one process). The default stays one process |
| Distribution | Spec files are assigned deterministically, longest first, from measured seconds (`browser_seconds_hint` in `scripts/test-map.json`, checked against the spec list); replaces Playwright's `--shard`, which balanced by test count |
| Isolation and cleanup | Each process owns its server, port (18745 upward), configuration directory and Chromium. Processes start in their own process group; on completion, error or interrupt the runner stops only those groups (SIGTERM, then SIGKILL after 20 s), never by name. Busy ports are reported, not cleared |
| Reporting | A failure names its process (index, port, spec files), the failing tests and the log tail. The regression report adds seconds per process and the ten slowest tests (also in `--report` JSON: `shard_detail`, `slowest`, `failed`) |
| Fast Validation | New `fast [feature ...]` profile: whitespace, documentation links, workflow contracts, Ruff, ESLint, TypeScript, smoke and the named features' tests. `fast access-package` took 128 s (ESLint 22 s, TypeScript 19 s, smoke 47 s, feature tests 40 s) |
| Accessibility audit | The 97 s test is now six tests (dashboard and main views, SoD views, Settings sections, each at 1280 and 375 px) with identical views, widths and checks. They take 8.7, 20.2, 10.9, 7.0, 19.5 and 10.6 s (77 s together), so a failure names its group and one group can be rerun |

Measured on the six-spec, 93-test benchmark subset of R8 (4 vCPUs, one worker per process, no failures in any run):

| Processes | R8 | R8.1 runner | Process seconds (R8.1) | Speed-up against the same-day serial run |
| --- | --- | --- | --- | --- |
| 1 | 308 s | 359 s | 358 | 1.00x |
| 2 | 232 s | 227 s | 225, 223 | 1.58x |
| 3 | 206 s | 207 s | 206, 202, 197 | 1.73x |

The serial run was 16% slower than the R8 serial run on this host and day; the speed-up is quoted against the same-day figure and the absolute figures are shown so the variance is visible. Balancing
the processes (within 5% instead of 3.4, 3.3 and 2.8 minutes) did not shorten the wall time, which stays CPU-bound, but it makes the result independent of which process finishes last.

Observed flake: in a three-process run of 395 select-related tests, one test (`release-roles` multiple user groups) failed while other work shared the host and passed in seven isolated runs. No retry was added; the
documented rule is to reproduce a parallel failure with `--browser-jobs 1 --grep TITLE` before classifying it.

## Phase 6: full regression, limits and recommendations

Final full regression (`regression --browser-jobs 3`, commit `9409ec9`, 4 vCPUs, Python 3.12, Node 22 in this sandbox, headless Chromium): **passed**.

| Stage | Result | Time |
| --- | --- | --- |
| Backend (3 processes) | 896 tests, 3 skipped (PowerShell x2, PyInstaller), 0 failed | 73.6 s (processes 56.9, 50.9, 72.0 s) |
| Production build including TypeScript | passed | 25.2 s |
| Browser (3 processes) | 731 tests, 0 failed | 1415.8 s (processes 1369.5, 1397.5, 1413.7 s) |
| Documentation links, workflow contracts, Lucide catalog, Ruff, ESLint, `git diff --check`, `pip check` | passed | 25 s together (ESLint 23.7 s) |
| Total | OK | 1539.8 s (25.7 min) |

Dependency audits: `npm audit --omit=dev` found 0 vulnerabilities; `pip-audit` of `backend/requirements.txt` found none. `npm audit` for development dependencies reports the 11 moderate `minimatch` advisories described under Phase 4.

Against the R8 baseline (serial, `--jobs 1`: backend 170 s, browser 716 tests in 34.5 min, about 38 min in total): the browser suite now has 731 tests and finishes in 23.6 min (31% shorter wall time, 1.94 s instead of 2.89 s per test),
the backend in 74 s, and the whole regression in 25.7 min. The three processes finished within 3% of one another. Parallelism helped; it is CPU-bound, and the gain (about 1.5x on the whole suite) matches the subset benchmark, not a
linear speed-up.

The first full run of this configuration failed three tests, which were investigated rather than retried:

| Test | Cause | Outcome |
| --- | --- | --- |
| `settings-refinement` shared navigation and dropdown geometry | A real regression of the new Select: a plain Arrow key opened the list where the browser changes the value (failed 3 of 3 serial reruns) | Fixed: a closed select opens on Enter, Space or Alt+Arrow and leaves Arrow, Home, End and typing to the browser |
| `release-roles` several user groups and usernames | A racy test: it read the table right after typing, before the 250 ms debounce and request applied the filter (failed about one in three runs, serial or parallel) | Fixed: the read waits until the table stops changing; the final assertion is unchanged; 10 of 10 repeated runs pass |
| `data-aware-ux` loading and reconnect during Back and Forward | Reached the 120 s timeout under three-process load; passed 3 of 3 serial reruns and in the final full run. It is the intermittent failure noted since R6 | Not changed: no trace of a failure is retained to show the cause. Recommended: keep a retained Playwright trace for it in CI |

New or environment-dependent behaviour: three-process load exposes timing-sensitive tests that a serial run hides (two of the three failures above were visible in an earlier three-process batch too). Keep `retries: 0`, reproduce a parallel failure with
`--browser-jobs 1 --grep TITLE`, and fix racy reads at the test.

### Known limitations and deferred improvements

- Native Windows desktop, WebView2, the Windows service and ACLs, real systemd boot and Docker were not run; tracker items R81-03, R81-14 and R81-15 stay Not tested.
- Sign-in throttling is per process (no shared state across workers or restarts); behind an unlisted reverse proxy every user shares the proxy's address. SEC-04 `unsafe-inline` styles and HSTS stay (HSTS belongs to the TLS proxy); `SystemCallFilter` and `MemoryDenyWriteExecute` are not applied.
- A report description with characters outside the bundled PDF font fails the PDF explicitly; older snapshots have no imported descriptions and say so.
- ESLint backlog: 30 hook-dependency warnings and 81 `any` uses in specs (ceiling enforced). CQ-04 to CQ-06 (unused shared components, long functions, `SettingsView`) remain.
- No Windows or manual UI acceptance was performed by a person; every R8.1 tracker item is Not tested with approval Pending.

Deployment-specific recommendations: throttle and audit sign-ins at the gateway for organisational deployments as well; list the reverse proxy in `SAP_LENS_TRUSTED_PROXIES` and make it set `X-Forwarded-For`; use `chmod 600` secrets and set `SAP_LENS_AUTH_SECRET_GROUP_READ=1` only where another account must read the file;
confirm the Windows secret ACL with `icacls` after any manual change; boot the hardened systemd unit once before relying on it.

## Follow-up: one build target dropdown

`build-deployments.yml` replaces the single `platform` input with one `build_target` choice (`all`, `windows-all`, `windows-desktop`, `windows-service`, `linux-all`, `linux-docker`, `linux-native`). An intermediate version had two inputs
(`operating_system` and `package`); GitHub cannot make one dropdown depend on the other, so the package list showed incompatible choices, and that version and its combination validation were removed. A new first job, **Resolve Build Selection**, runs
`scripts/deployment-release.py plan` (standard library only), resolves the choice once, rejects only an unknown value (possible through a manual API dispatch) before shared validation or any packaging runner starts, exposes the selected packages
(`packages` and one flag per job) and writes a summary with the target, the resolved packages and each package as selected or skipped. Shared validation needs the plan; each package job runs only when `needs.plan.outputs.<job> == 'true'`, so unselected
packages are skipped and start no runner. The publisher takes the package list from the plan, checks it against a fresh resolution of the same target, requires every selected job to have succeeded with verified outputs and every unselected job to have been
skipped, and collects only same-run artifact IDs of the selected packages. Artifact names, versioning, channel rules, verification and the publication environment gates are unchanged.

Evidence (nothing was dispatched): `test_deployment_selection` (the seven values, planner outputs and summary for each, unknown values, the planned-list check, the workflow's job conditions evaluated per selection including that a Linux target starts no Windows
runner and a Windows target no Linux packaging runner, exactly one build-selection dropdown, publication gating with skipped siblings and an unselected artifact that must not ride along), the ported `test_deployment_release`, the workflow contract
(`check-workflows.py`) and the pinned actionlint (`scripts/ci.py lint`, exit 0). Not validated: a real GitHub run of the workflow; the `plan` job, the skipped-job behaviour on GitHub's runners and a publication with a partial selection are verified only through these offline models.
