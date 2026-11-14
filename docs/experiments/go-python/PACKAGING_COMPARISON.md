# Packaging comparison

Compares the product's PyInstaller **one-file** build, a PyInstaller **one-dir** build (measured only as a Linux stand-in in Phase 0) and the experimental bundled-runtime tree with the Go host. **No Windows measurement exists for any row.** Linux figures are labelled and are not Windows results.

| Aspect | PyInstaller one-file (product) | PyInstaller one-dir | Bundled runtime + Go host (experiment) |
| --- | --- | --- | --- |
| Windows compatibility | proven in production use (unsigned) | same bootloader and hooks, not built here | built on Linux, never run on Windows |
| Native dependency handling | PyInstaller hooks collect `.pyd` and DLLs, `--collect-data` and `--copy-metadata` flags in the build; embedded in one archive | same, laid out on disk | hash-locked wheels unpacked as-is; no hooks, but also nothing prunes unused modules |
| Files signed or signable | one EXE signable; embedded `.pyd`/`.dll` are extracted to a temp folder at every start and are not signed by the EXE's signature | many images on disk, signable in place | about 50 unsigned images plus the host, signable in place |
| App Control | EXE blocked on the policy machine (existing evidence). Unknown whether extracted temp files would be blocked after the EXE is signed | every image must satisfy policy; stable install path | every image must satisfy policy; stable install path; more third-party origins visible |
| Startup (Linux only, Phase 0) | one-file not measured (adds extraction) | 1.29 s | 0.98 to 1.08 s (host included) |
| Memory (Linux only) | not measured | 86.0 MiB | 78.8 MiB direct, 87.0 MiB with host |
| Distribution size (Linux, unpacked / archive) | not measured | 82.5 MB / 36 MB | 171 to 198 MB / 58 to 69 MB (Windows tree 144 MB / 53 MB) |
| File count (Linux) | 1 file on disk | 1,575 | 7,700 to 9,343 |
| Reproducibility | not assessed | not assessed | tree and archive hashes identical across builds (tested) |
| Patching | bump CPython and libraries in the build venv, rebuild | same | bump the lock (interpreter hash, wheel hashes), rebuild; upstream python-build-standalone releases are unsigned |
| Supply chain | PyInstaller and hooks packages | same | python-build-standalone, wheels, Go toolchain, our host |
| Installer integration | current Inno Setup ships one EXE; verifiers expect an unsigned single PE | file list grows | about 9,000 files: install time, uninstall list, AV scan cost, path length, and verifier changes (see below). No installer exists |
| Process model | desktop host in-process | same | extra process (about 8 MiB, Linux); stop and orphan cleanup moved into a small Go host |

## Reading

- **One-file is not a single-file story for App Control.** It extracts the same native images at each launch, into a user-writable folder. Signing the EXE does not by itself make those images acceptable. This is untested on the policy machine because the EXE is blocked first, and it is the most important comparison unknown. If the product must also sign or allow every extracted image, the signing burden of the two approaches converges.
- **No performance or size argument** for the experiment: 2.1 to 2.4 times the disk footprint of the one-dir stand-in, about 5 to 6 times more files, equal startup and memory on Linux within noise. Windows file-system and Defender scanning costs for 9,000 files are unmeasured and likely worse than on Linux.
- **The case for the experiment is control and auditability:** every input is pinned and hashed, the tree has a file manifest, the build is reproducible, signing can be applied per file in place, and lifecycle ownership sits in a small, testable program.
- **Costs:** more files for policy, installer and antivirus to handle; a new unsigned native executable (the host) and a new upstream (python-build-standalone) in the trust chain; verifiers and the installer need a signed mode and a file-set mode.
- **Existing verifier restriction:** `scripts/packaging/verify-windows-package.py` rejects any certificate table ("this workflow is for unsigned builds") and expects one EXE. Either approach needs a coordinated signed mode ([SIGNING_CONTRACT](SIGNING_CONTRACT.md)).
- **Not compared (no data):** Windows startup and memory; one-file extraction time; Windows archive and install size of a real installer; one-dir signing of the product; antivirus behaviour.

## Verdict on criterion 5

A defensible benefit over the existing architecture is **not demonstrated**. Possible benefits (auditability, reproducibility, in-place signing, explicit lifecycle ownership) are real but unproven against their cost in files and trust chain, and they are worth a Windows measurement before any decision.
