# Cross-platform deployment validation — 24 October 2026

Historical runtime checkpoint at `a857539`: **native Windows acceptance pending**.
The subsequent packaging/workflow implementation and current results are in
[Packaging validation](PACKAGING_VALIDATION.md). Statements below describe the
earlier runtime checkpoint, before the additional packaging workflow.
Starting branch `work`, source baseline `f82973125b4b028c8dc59bb02d10c209741fc271`.
Remote `work` was fetched and subsequently confirmed unchanged during delivery.
No Windows builds, Actions dispatches, tags, releases or repository settings changed.

## Architecture and scope

One FastAPI factory, one React production frontend, existing CSV lifecycle and
business rules. `backend/server.py` owns the headless listener/lease; deployment
policy/capabilities are centralized. Desktop continues to use its WebView2 entry
point and one-file packaging. A storage lease/marker now separates concurrent
writers/deployment modes. No Python/Node dependency changes or additional workflow.

Server-native default: loopback, exact allowed host/origin, local peer boundary.
Network deployment requires configured Basic access or an authenticated gateway
with real-peer CIDRs, secret header and identity attestation. HTTPS public origins
are required outside localhost. Shared access has administrator capabilities;
per-user permissions/authentication remain explicitly future work.

Browser uploads stream into managed storage, remain unconfirmed until existing
preview/import operations, and use Static mode. Dynamic file reads are confined to
operator-configured roots; symlink escapes are rejected. Existing source replacement,
change reports, snapshots, settings and export semantics remain shared.

## Executed validation

Commands were run from the repository root, with the prepared Python 3.12 virtual
environment. External logs are under `/workspace/sap-lens-dev/cross-platform/` in
the execution workspace; they are not shipped in distributions or tracked in Git.

| Check | Result |
| --- | --- |
| `npm --prefix frontend ci --cache /workspace/.npm-cache --no-audit --no-fund` | Passed, 143 packages |
| `npm --prefix frontend run check:types` | Passed |
| `npm --prefix frontend run build` | Passed; existing large-chunk warning remains |
| `.venv/bin/python -W error::DeprecationWarning -m unittest discover -s backend/tests -v` | **336 passed**, 27.786 s |
| `PATH=/workspace/sap-lens/.venv/bin:$PATH PLAYWRIGHT_EXECUTABLE_PATH=/usr/bin/chromium npm --prefix frontend run test:browser` | **224 passed**, 6.5 min, one full run, no retries |
| `.venv/bin/python -m pip check` | No broken requirements |
| `python -m pip_audit -r backend/requirements-dev.txt -r backend/requirements-build.txt --cache-dir /workspace/.pip-audit-cache` using the separate existing audit venv | No known vulnerabilities in Linux-resolved dependencies; Windows-specific resolution remains pending |
| `npm --prefix frontend audit --omit=dev --cache /workspace/.npm-cache` | 0 vulnerabilities |
| Full `npm audit --json` | 3 existing moderate development advisories: tailwindcss, postcss-nested, postcss-selector-parser; no production advisory |
| `pwsh -NoProfile -File scripts/check-powershell.ps1` | Six scripts parse/static guards pass, including both new service scripts |
| `.venv/bin/python scripts/check-workflows.py` and existing `actionlint` | Passed; original three workflow triggers/permissions/integrity contracts unchanged |
| `node scripts/sync-lucide-catalog.mjs --check` | 1,447 icons verified |
| `docker compose config --quiet` | Passed |
| `git diff --check`, documentation/asset/privacy checks | Passed; protected README opening block compared exactly |

The final PowerShell/source-ACL correction leaves UNC ACL administration to the
share owner instead of attempting remote ACL changes. Its affected syntax/static
checks and three deployment-contract tests were rerun successfully; no repeated
full browser run was needed. Documentation-only changes received link checks.

### Shared server regression coverage

Eight focused server tests cover invalid exposure configuration, Basic admission,
real-peer proxy authentication, forged forwarding headers, hostile host/origin,
factory-mode authentication, staged uploads/preview/confirmation, independent
sources, malformed names, empty/oversized streams, filesystem confinement,
redacted diagnostics, and data-store ownership. Linux process testing verifies
production frontend/API serving, duplicate instance rejection, occupied-port
failure, SIGTERM shutdown and restart with the original Static CSV removed.
Existing backend lifecycle tests additionally cover dynamic full replacement,
failed replacement preservation and persisted Employee Directory data.

Six new browser cases use a **real Basic-protected headless server**, not only
mock routes: Unicode file upload, staging feedback, existing preview/confirmation
APIs, Static mode, mapped role visibility, runtime capabilities and actual browser
diagnostic download. Light/dark at **375, 800 and 1280 px**; screenshots reviewed.
No horizontal page overflow observed in those cases. Existing 218 cases remain.

### Docker execution

Final image built successfully with Docker 28.4.0 / BuildKit:

`sha256:88741255bb7b2287247f979f84d20eddaeda8f4994b676ba6e7b9e18103a56c9`

The managed environment required its existing proxy passed as build arguments,
a temporary `build_ca` secret and proxy hostname mapping. No TLS bypass or CA baked
into the image. The final source copy normalizes application read permissions;
otherwise this workspace's 0600/0700 source modes prevented UID10001 execution.

A synthetic smoke harness executed the final image with UID10001, read-only root,
dropped capabilities, a private secret and named data volume. It verified frontend,
authenticated API, rejection without credentials, CSV upload/import, health probe,
restart persistence, and removal/recreation with the same volume. Test containers,
secret/data volumes were removed afterwards. Compose configuration was checked;
the runtime smoke used Docker directly with equivalent settings. The workspace's
filesystem does not support assigning the bind-secret group, so the smoke used an
isolated secret volume rather than claiming the documented host-secret setup ran.
No public image or artifact was published.

## Native acceptance not executed

- Windows Service bundle compilation/PE inspection on real Windows, SCM install,
  start/stop/restart/reboot/recovery, noninteractive session and domain/gMSA/UNC access.
- Existing desktop packaged EXE, WebView2, native file/save dialogs and shutdown.
- A running systemd host: installation, boot enablement, journald and hardening at runtime.
- Firefox, Safari, iOS and Android hardware browsers. Mobile Chromium viewport
  checks do not certify those browser engines/devices.
- Administrator-managed HTTPS proxy/gateway integration against a real identity provider.

The implemented Windows server builder requires a fresh canonical local validation
receipt and verifies the pinned WinSW wrapper, x64 console PE, resource identity,
frontend, embedded modules/privacy and per-file SHA-256. These are implemented
checks, **not a claim that a Windows package was built or verified here**. The
Windows desktop verifier/release workflow remains unchanged.

This checkpoint is ready for target-platform acceptance testing, not an assertion
that all final native acceptance criteria are met. `AGENTS.md` requires explicit
approval before pushing with Windows validation incomplete. Retain `[skip ci]`
under the user's standing instruction until withdrawn; do not dispatch a workflow.

## Changed-file inventory

- Runtime/security/storage: `backend/deployment.py`, `server.py`, `healthcheck.py`,
  `storage_lease.py`, `server_uploads.py`, and integration in `main.py`, `config.py`,
  `configuration_routes.py`, `csv_import.py`, `employee_directory.py`,
  `routers/employees.py`, `diagnostics.py`, `request_limits.py`, `desktop.py`.
- Frontend: `Settings/BrowserSourceUpload.tsx`, `SettingsView.tsx`,
  `ImportPresets.tsx`, `EmployeeDirectory.tsx`, `Diagnostics.tsx`.
- Deployment: `Dockerfile`, `.dockerignore`, `compose.yml`,
  `deploy/server.env.example`, `deploy/linux/sap-lens.service`.
- Windows tools: `scripts/build-server-windows.ps1`, `manage-server-service.ps1`,
  `verify-server-bundle.py`, and `check-powershell.ps1` integration.
- Regression tests: `backend/tests/test_server.py`, `test_deployment_contracts.py`,
  `frontend/tests/server-deployment.spec.ts`.
- Documentation: `docs/DEPLOYMENT*.md`, `docs/ARCHITECTURE.md`, README deployment
  link outside the protected block; `.gitignore` excludes private secrets/server output.
