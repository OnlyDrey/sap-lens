# Security review (R8)

Date: 2026-10-31. Revision reviewed: `53f292e` plus the R8 changes. This is an internal, evidence-based review. It is **not** a penetration test,
a certification or proof that SAP Lens is secure. Earlier dated review: [archived security review](../archive/implementation/SECURITY_REVIEW.md).
Boundary and configuration guidance: [security architecture](../architecture/SECURITY.md) and the [deployment security guide](../deployment/SECURITY.md).

## Method

Protections were checked in practice, not assumed from documentation:

- Every API operation (122, taken from the OpenAPI schema) was called without the launch capability, with a foreign `Origin`, with a wrong
  capability and with a foreign `Host`; in server mode every operation was called without credentials and with wrong credentials. The result is kept
  as the regression test `backend/tests/test_security_surface.py`.
- Static reading and searches for unsafe sinks (`eval`, `exec`, `pickle`, `yaml.load`, shell invocation, `innerHTML`, `dangerouslySetInnerHTML`,
  `window.open`), for CSV writers, for hard-coded secrets, for logging of private values and for storage use.
- Review of `Dockerfile`, `compose.yml`, `deploy/linux/sap-lens.service`, the server upload endpoint, path confinement and the authentication code.
- `npm audit` (production and development): 0 vulnerabilities. `pip-audit` on `requirements.txt`, `requirements-dev.txt` and
  `requirements-desktop.txt`: no known vulnerabilities. These reflect the advisory databases on the review date only.

## Findings register

Severity scale: Critical, High, Medium, Low, Informational. No Critical, High or Medium issue was confirmed.

| ID | Severity | Component and file | Evidence and reproducibility | Exploitability and impact | Remediation | Status | Test coverage |
|---|---|---|---|---|---|---|---|
| SEC-01 | Low | CSV export, `backend/routers/data_sources.py` (refresh changes export) | The local `safe()` function neutralised only values whose stripped text begins with `= + - @ TAB CR`. Values such as `﻿=1+1`, `\x01=1+1`, `\x00@SUM(1)` and `\nA` were exported unchanged (probe against `csv_exports.spreadsheet_cell`, which prefixes all of them). | Needs a crafted value in an imported CSV that reaches a change report, and a user opening the export in a spreadsheet that honours it. Impact: formula execution prompts in the viewer's spreadsheet. | Use the shared `spreadsheet_cell` for every export. | Resolved | `test_security_surface.SpreadsheetExportTests` |
| SEC-02 | Low | Server authentication, `backend/deployment.py` | Failed Basic attempts are not throttled or locked out. Constant-time comparison and a 32 to 256 character secret limit guessing; the deployment guide already states the absence of brute-force throttling. | Online guessing against an exposed server. Impact: access to shared investigation data if the secret is weak or the proxy is absent. | Throttle at the gateway or reverse proxy (the documented deployment); an in-app limiter needs a state and lockout design decision. | Accepted and documented; approval needed for an in-app limiter | `test_security_surface.ServerBoundaryTests` (authentication required everywhere) |
| SEC-03 | Low | Secret file check, `backend/deployment.py` | The secret file is rejected only when readable by *other* users (`mode & 0o007`); group-readable files (for example `0640`) are accepted. | A local user in the owning group can read the shared access secret. | Tighten to `0o077`; this can break systemd or container secret mounts that deliver `0440`/`0640`, so it needs a compatibility decision. | Open: needs approval | `test_security_surface` (rejection for other users) |
| SEC-04 | Informational | Response headers, `backend/main.py` | CSP forbids unsafe scripts (tested) but allows `style-src 'unsafe-inline'` (inline styles carry measured coordinates). No HSTS, `Permissions-Policy` or cross-origin isolation headers. | Defence in depth only. HSTS belongs to the TLS-terminating proxy. | Add `Permissions-Policy` and document HSTS at the proxy. | Open (recommendation) | `test_security_surface.DesktopBoundaryTests` |
| SEC-05 | Informational | Server uploads, `backend/server_uploads.py` | The upload response returns the server-side staging path to the authenticated client; the client needs it to select the source. | Reveals an internal path to an already authenticated user. | None needed. | Accepted | `test_server` upload tests |
| SEC-06 | Informational | Access model | One shared access boundary, no per-user roles; review decisions record a self-reported reviewer name (documented). | Repudiation: decisions are not tied to an authenticated identity. | Optional: derive the reviewer from the proxy identity header in proxy mode (design decision). | Accepted (by design) | n/a |
| SEC-07 | Informational | systemd unit, `deploy/linux/sap-lens.service` | Already uses `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`, `ProtectHome`, `UMask=0077`, a dedicated user. Further sandboxing is possible. | Hardening opportunity. | Consider `PrivateDevices`, `ProtectKernelTunables`, `ProtectControlGroups`, `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`, `SystemCallFilter=@system-service`; test under systemd first. | Open (recommendation) | not executable here |

## Controls verified in practice

| Area | Result |
|---|---|
| Authentication and authorization | All 122 API operations refuse requests without the launch capability, with a foreign origin, with a wrong capability and with a foreign `Host`; only `/health/live`, `/health/ready` and `/health` are outside `/api/`. Server mode: every operation needs credentials; `PUT`, `DELETE` and `PATCH` are refused (405). |
| CSRF | State-changing calls need the custom `X-SAP-Lens` header and an allowed origin; CORS allows no credentials. No cookie authentication exists. |
| Injection and unsafe sinks | No `eval`, `exec`, `pickle`, unsafe YAML or shell invocation (the only subprocess use runs fixed Windows commands); no HTML injection sinks in the frontend; SQL is not used. Report text is escaped before it reaches ReportLab markup (`sod_reports.py` has one `Paragraph` construction site). |
| Path traversal | Server mode confines every CSV read to the source root or managed uploads after resolving symbolic links; absolute `.csv` paths are required; uploads use server-generated names and reject path characters. Desktop mode reads the paths of the signed-in user by design. |
| CSV formula injection | All CSV writers go through `spreadsheet_cell` after SEC-01. |
| Resource exhaustion | JSON bodies limited (16 KB default, larger only for configuration packages); CSV limits of 128 MiB and one million rows; upload streams bounded per source. |
| Error disclosure | One generic 500 message in desktop and server mode; no paths or exception names in responses (tested). |
| Network binding | Defaults to loopback; non-loopback access needs HTTPS origin, explicit allowed hosts and Basic or proxy authentication; `local` mode requires a loopback binding and origin. |
| Secrets | No credentials in the repository; secrets are read from files; `.env` examples contain none. |
| Frontend storage | `sessionStorage` holds the launch capability, reviewer and dismissed-notice values; `localStorage` holds theme and sidebar preferences only. No SAP data is cached and no service worker exists. |
| Containers | Non-root UID 10001, read-only root filesystem, all capabilities dropped, `no-new-privileges`, secret from file, loopback publish by default, health check. |
| Dependencies | `npm audit`: 0 vulnerabilities; `pip-audit`: none for runtime, development and desktop requirements. |

## Not performed (environment limits)

Native Windows validation (WebView2 isolation, Windows Service account and ACLs, UNC paths, installer and update behaviour), Linux systemd
and Docker runtime acceptance, active penetration testing, fuzzing of the CSV parsers and a review of TLS termination at a real proxy. These
remain manual or CI-on-Windows activities.

## Changes made in R8

SEC-01 fixed; `backend/tests/test_security_surface.py` added (9 tests). No deployment behaviour was changed; SEC-02, SEC-03 and SEC-07 are
left for an explicit decision because they affect deployment compatibility.
