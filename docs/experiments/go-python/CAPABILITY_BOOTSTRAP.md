# Security assessment: capability bootstrap (finding F1)

Scope: assessment only. The existing production security model was not changed. Reproduced on Linux against the unchanged backend started by the Go host, with synthetic data. The code path is operating-system independent; the Windows-specific consequence (other users on the same machine) is analysed but NOT EXECUTED.

## Question

Can a local process obtain the session capability without an authenticated application handoff? **Yes**, today, in any process that runs `create_app(browser_access=True)`. The Desktop app does: `backend/desktop.py` calls `create_app(..., browser_access=True)` and also hands the same token to its WebView2 window in-process (`window.evaluate_js(... '#session=' + token)`), so the HTTP document route is redundant for WebView2 and is an extra disclosure path.

## Mechanism

`GET /` (`backend/main.py`, `desktop_document`) injects the capability into the HTML when the request carries `Sec-Fetch-Mode: navigate`, `Sec-Fetch-Dest: document`, `Sec-Fetch-Site` in `none|same-origin|same-site`, and no foreign `Origin`. Browsers set `Sec-Fetch-*` themselves, so a web page cannot forge them, which is what the check is for (cross-site scripts and frames are refused). A non-browser client can send any header. The remaining gates (exact loopback `Host`, loopback client address) do not distinguish between local users or processes.

## Reproduction (synthetic, Linux; repeats with `tests/test_capability_bootstrap.py`)

1. Start the host: `saplens-host --runtime /tmp/poc-linux --data /tmp/poc-data --hold 60s`, note the printed URL.
2. As any local process:
   `curl -s -H 'Sec-Fetch-Mode: navigate' -H 'Sec-Fetch-Dest: document' -H 'Sec-Fetch-Site: none' http://127.0.0.1:PORT/` and read the value in `sessionStorage.setItem('sap-lens-session',"...")`.
3. `curl -s -H 'X-SAP-Lens: <value>' http://127.0.0.1:PORT/api/settings` returns 200. Without the header, or with a wrong value, 403.

Observed and tested: works; refused without the navigation headers, with `Sec-Fetch-Site: cross-site`, with a foreign `Origin`, and with a foreign `Host` (also blocks DNS rebinding); the capability differs per launch and one launch's capability does not work on another.

## Threat model

| Actor | Can reach the port | Gets the capability | Real impact |
| --- | --- | --- | --- |
| Remote web page (cross-site, DNS rebinding) | yes, via browser | no: `Sec-Fetch-Site`, `Origin` and `Host` checks | none found |
| Another OS user on the same machine (RDS, VDI, shared workstation) | yes: loopback is machine-wide, not per user | **yes** | read and write all SAP role and SoD data served by that user's instance, which that user's file permissions were meant to protect |
| Malicious process of the same user | yes | yes | low marginal: it can already read that user's data files and the app's own storage |
| Low-integrity or sandboxed process with loopback access | possibly | yes | depends on the sandbox; not tested |
| Process on another machine | no: 127.0.0.1 only | n/a | none |

Port discovery is trivial (OS-assigned, visible in `netstat` and the process list), so the OS-assigned port is not a secret.

## Impact

High for multi-user Windows machines, low for single-user machines. It undermines the stated purpose of the capability (a per-launch secret) because the secret is available on request. The Go host does not worsen this and does not fix it.

## Recommended remediation (for a later, approved change)

1. **Stop serving the capability over HTTP.** In Desktop (WebView2) keep the in-process handoff only. For browser mode the host issues a single-use **launch ticket**, passed to the browser in the URL fragment (never sent to the server, never in a log), exchanged once by the page for the capability over `POST` (`Origin` checked), with a short expiry (for example 30 s) and no reuse. The document route returns the plain HTML.
2. **Bind to the launching user on Windows.** Compare the connecting peer's owning process or token SID (from the TCP table for the client port) with the launching user's SID and refuse others. This closes the other-user case that the ticket alone does not, if the ticket leaks through a shared command line. Needs native Windows validation.
3. Keep the `X-SAP-Lens` header, the `Host` and `Origin` checks, and per-launch rotation.
4. Do not log the ticket or put it in an argument visible to other users; prefer the host opening the browser or shell itself.

Remediation 1 alone leaves a same-user process able to read the browser's command line; that is the same trust level as the user's own files and is accepted.

## Required regression tests (written as the contract; two exist today)

| Test | Status |
| --- | --- |
| Navigation headers alone do not yield a capability | present, `expectedFailure` until remediated |
| Cross-site, foreign Origin, foreign Host, missing headers yield no capability | present, passing |
| Capability is per launch and not valid on another launch | present, passing |
| Ticket is single use, expires, and is rejected when replayed or when the `Origin` is foreign | to add with the remediation |
| Ticket and capability never appear in argv, environment, logs or data files | present for the capability; add the ticket |
| Another Windows user cannot connect or exchange | Windows only, NOT EXECUTED |
| UI loads end to end through the ticket (browser smoke) | to add |
| WebView2 handoff still works without the HTTP document route | Windows only, NOT EXECUTED |

## Runtime integrity: install time, start time or both

**Both, with different jobs.**

- **Installation:** verify everything: SHA-256 of every file against the manifest, Authenticode of every image, installer identity bound to the payload, and set the tree read-only for non-administrators (for example under Program Files). This is where a full pass is affordable.
- **Start:** verify the manifest's own signature and the set of executable images that will be loaded (about 52 files, tens of MB, expected well under a second; not measured), refuse on mismatch, and report the failure with a distinct exit code. Do not hash all 9000 files at every start.
- **Limits that must be stated:** App Control enforces code signing on images (exe, dll, pyd) but not on Python source or `.pyc`. The experiment compiles hash-based `.pyc` with `unchecked-hash`, which means the interpreter runs the `.pyc` **without checking it against the source**. Tampering with a `.py` or `.pyc` in a writable tree is therefore not caught by Python and not by App Control. The defence is the directory ACL plus the signed manifest and startup check of the application files that matter (`app\backend`, the `.pth` file). A startup check is only meaningful if the manifest is signed and the tree is not writable by the attacker, otherwise they change both.
