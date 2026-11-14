# Security considerations

Verified on Linux by [tests](README.md#tests). Windows items are design only unless stated.

## Enforced and tested

- Loopback only: listener bound to 127.0.0.1 with an OS-assigned port; test reads `/proc/net` for loopback address and absence on IPv6.
- Existing host/origin boundary and session capability are used unchanged: no `/api` access without the capability (403), wrong capability (403), foreign `Host` or `Origin` (403).
- The capability is handed over on stdin. Tests find it in no argv, no environment, no data file. The host redacts it from any child output.
- Child runs `python -I` with an explicit minimal environment (no proxy variables, tokens or user site).
- Data confined to a marker-guarded, mode-0700 directory; the backend refuses a missing, relative, unmarked or symlinked-marker location and does not touch it.
- No orphan backend after SIGTERM, SIGINT, SIGKILL of the host (Pdeathsig plus stdin-EOF watchdog) or start timeout.
- Wheel and interpreter hashes verified before use; archive extraction rejects traversal, absolute paths and unsafe links; the manifest detects changed, missing and unexpected files.

Correction (Phase 1): the original wrong-capability test used a header name the backend does not read, so it was vacuous. It now uses `X-SAP-Lens` and has a positive control. See [PHASE1](PHASE1.md).

## Findings

1. Browser-mode capability bootstrap (pre-existing design, not changed). `GET /` with `Sec-Fetch-*` navigation headers returns the HTML with the session capability injected. Any local process that can open a loopback connection and send those headers can obtain it. The existing Desktop browser access has the same property. The Go host does not change or worsen this, but also does not fix it. Any production use needs a decision on this boundary. Assessed in Phase 1: [CAPABILITY_BOOTSTRAP](CAPABILITY_BOOTSTRAP.md).
2. The interpreter hash comes from the release `SHA256SUMS` over TLS. It is a pin, not an independent signature. A compromised release would pass.
3. Integrity is checked at test and assembly time. The host does not verify the manifest at startup, so a tampered installed tree is not detected at runtime. Cheap to add, expensive in startup time for 9000 files unless limited to executables.
4. The data-directory marker protects against pointing the PoC at a real installation. It is not an access-control mechanism.
5. `govulncheck` could not run. Go toolchain vulnerabilities (1.24.7) were not scanned.
6. No authentication or authorization code was changed or bypassed.
