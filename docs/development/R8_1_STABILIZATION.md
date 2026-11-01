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
