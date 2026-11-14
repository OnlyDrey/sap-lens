# Windows limitations and Phase 1 decision

## Windows status

| Item | Status |
| --- | --- |
| Go host cross-compile and `go vet` for windows/amd64 | Executed on Linux, passed |
| Windows runtime tree assembled from Linux | Experimental. Built (hash-locked wheels with `win_amd64` tags), never executed |
| Windows Job Object code, exclusive bind, process-tree stop | NOT EXECUTED |
| Native smoke, installer acceptance | NOT EXECUTED |
| Windows App Control verification | NOT EXECUTED. App Control was not weakened or bypassed |
| Defender / antivirus scan cost of about 9000 files | NOT MEASURED |

Not Windows validation. Linux numbers are not Windows-equivalent.

## Open Windows risks

- Every native file loaded must satisfy App Control: 52 `.pyd`, 13 `.dll`, 10 `.exe` in the unpruned tree, mostly third-party and unsigned (python-build-standalone, wheel authors). Signing is necessary but not sufficient. The existing package verifiers reject signed or foreign binaries and would need a coordinated change. A frozen build has one executable and fewer files to cover, which is the strongest argument against this approach.
- No installer exists for the bundled tree. Upgrade, rollback, service account permissions and path length (deep `site-packages`) are unexamined.
- The Go host is a new unsigned native executable and a new supply chain item.

## Recommendation

Conditional GO for a Windows-gated Phase 1, NO-GO for any migration or product change.

Reasons:
- Measured: no startup or memory advantage, 2.1 to 2.4 times larger distribution, 5 to 6 times more files. Benefit is auditability and reproducibility only.
- Lifecycle and security boundaries work as designed on Linux, and the only unresolved question that can decide the architecture is App Control on Windows.

Phase 1, if approved, should be limited to:
1. Run the Windows tree and host on a Windows machine with App Control enforced, record what is blocked.
2. Decide the browser capability bootstrap (SECURITY finding 1) and runtime manifest verification.
3. Ship `build-version.json` identity in the bundled runtime.

Stop criterion: if App Control blocks unsigned third-party native files with no acceptable signing or allow-listing path, stop. The frozen build stays the better fit, and the Go host would then only be worth considering as a Desktop shell question, which is separate.
