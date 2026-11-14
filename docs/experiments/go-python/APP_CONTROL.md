# App Control findings

Status: **no Windows App Control evidence exists for the bundled tree.** What follows is existing repository evidence, static analysis done on Linux, and the diagnostics prepared for Windows. App Control was not changed, bypassed or weakened, and nothing here claims that signing guarantees acceptance.

## Existing evidence (from the product's own documentation, not from this experiment)

- On a Windows test machine an enforcing, signed platform policy (`VerifiedAndReputableDesktop` plus a supplemental policy) blocked the unsigned Desktop EXE and the payload the installer extracts (Code Integrity events 3077 and 3033). See `docs/deployment/CODE_SIGNING.md` and `docs/deployment/WINDOWS_DESKTOP.md`.
- The product is a PyInstaller **one-file** EXE (`--onefile --windowed`). In that run the EXE was refused before it could extract anything, so **nothing is known about whether the files PyInstaller extracts to a temp folder at each start would also have been blocked**. This matters for the comparison: the existing architecture is not a single-file story at the policy level.
- Signature is necessary but not sufficient; no evidence shows that self-signing or an arbitrary commercial certificate would be accepted.

## Static inventory of the experimental Windows tree (Linux, headers only)

Source: [windows-static-inventory.json](windows-static-inventory.json), produced by `windows/pe_inventory.py`. A present certificate table does not mean the signature is valid or trusted.

| Group | Images | Embedded certificate table |
| --- | --- | --- |
| Whole tree (unpruned) | 75 (52 `.pyd`, 13 `.dll`, 10 `.exe`), mixed amd64/x86/arm64 (pip and venv launchers) | 4 `.dll` only |
| Needed to run the backend (excluding pip, venv, tcl/tk, test) | 52: 42 `.pyd`, 8 `.dll`, `python.exe`, `pythonw.exe` | `vcruntime140.dll`, `vcruntime140_1.dll` (Microsoft) |
| `python.exe`, `pythonw.exe`, `python312.dll`, `python3.dll` | 4 | none: the python-build-standalone interpreter is unsigned |
| Wheel-origin native images (PIL 8, lxml 7, charset_normalizer 2, argon2 bindings, cffi, cryptography, pydantic_core) | 21 | none |
| Our Go host | 1 | none (unsigned) |

So about 50 unsigned images from three origins (python-build-standalone, seven wheel publishers, our host) would each have to satisfy the policy. The pruned tree drops pip, tkinter and tests (about 20 images) but not the runtime set. Hash rules for unsigned files change with every rebuild and are not sustainable ([CODE_SIGNING](../../deployment/CODE_SIGNING.md)).

## Where failure can occur, and how the diagnostics tell them apart

Windows can refuse at process creation (host, interpreter) or later at image load (any `.pyd` or `.dll`), and a load refusal surfaces in Python as a generic `ImportError`. The harness therefore starts the three stages separately and imports each extension in its own process.

| Class | Evidence required | Where |
| --- | --- | --- |
| `executable_blocked_by_policy` | native error 1260 or 4551 at creation, or an enforced Code Integrity record for the host file | W04 |
| `interpreter_blocked` | same, for `python.exe` | W05 |
| `native_extension_blocked` | an enforced record (3077, 3033) for that `.pyd` or `.dll` below the runtime root, inside the time window | W06 |
| `native_load_failure_unclassified` | `ImportError` without an enforced record. Not called a block: it can be a missing runtime DLL, a search-path problem, or an audit-only (3076) record | W06 |
| `missing_dependency` | `ModuleNotFoundError` | W06 |
| `application_startup_failure` | the process ran, then failed its own contract (exit code, no READY, failed check) with no enforced record | W05, W07 |
| `blocked_component_during_startup` | no READY and an enforced record below the runtime root | W07 |
| `installer_failure` | not applicable: the experiment has no installer | n/a |

Rules: translated message text is never parsed; a missing signature is recorded but is not proof of a block; an unreadable event log is a limitation, and it makes W14 NOT EXECUTED rather than PASS; 3076 audit records are reported as "would be blocked". All of this logic is tested with synthetic records (`Test-Phase1Logic.ps1`, 22 assertions, passes on Linux).

## What a path to compatibility could look like (for IT to decide, not claimed)

1. Sign every image we ship or own (host, and either re-signed interpreter and extensions or an upstream-signed interpreter) with one publisher certificate, and have the security administrator add that publisher as a supplemental-policy signer rule. This is the only option that survives rebuilds. Whether the organization accepts the publisher is IT's decision.
2. Prefer an interpreter distribution that is already signed upstream (the CPython embeddable package from python.org is a candidate to evaluate; it is a different distribution than the one used here and is untested).
3. Keep third-party wheel `.pyd` files out of the trust boundary where possible, or re-sign them as our own after verifying their upstream hash ([SIGNING_CONTRACT](SIGNING_CONTRACT.md)).
4. Anything that relies on exclusions, path allow rules for user-writable folders or turning enforcement to audit is not an acceptable remediation and was not tried.

Open question that only Windows can answer: whether the organization's policy accepts such a signer for roughly 50 images in a user-visible install folder, and what the one-file product would do under the same policy after its EXE is signed.
