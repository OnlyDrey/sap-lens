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
