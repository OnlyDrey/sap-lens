# Phase 1 assessment and decision: Go supervisor + bundled CPython

Status: decision support. Based on commit `7b4464d` and the evidence listed below. No new Windows run, build or package was made for this document, no product code was touched, and nothing here changes Windows security settings.

Evidence tags: **[W]** Windows result reported by the person who ran the bundle (the evidence files are not stored in this repository), **[M]** measured on Linux in this environment (not a Windows result), **[C]** read from code or repository documentation, **[U]** not measured or not known.

## 1. Executive summary

- **Recommendation: STOP the Go + bundled CPython direction as a migration candidate. Do not start Phase 2.** Keep the branch as a reference. This is a decision about demonstrated value, not a claim that the idea cannot work.
- **The experiment's central question is answered "no advantage demonstrated".** Windows App Control evaluates the file, not the language it was written in. An unsigned Go host was blocked [W] exactly as the unsigned PyInstaller EXE was earlier [C]. Everything that makes deployment work in a managed environment (signing, a publisher or equivalent rule from IT, an approved distribution channel) is the same for every option and is not advanced by Go.
- **Go adds a component instead of removing one.** The Python backend, the frontend and about 50 native images stay; the host is one more unsigned PE to sign and authorize, on a footprint 2.1 to 2.4 times that of a one-dir PyInstaller stand-in [M], with no measured startup or memory benefit [M] and no Windows measurement at all.
- **The one result that looked positive does not hold.** The earlier W04 PASS (host executed, interpreter and 21 native modules loaded [W]) is a single observation; the same experiment's later runs and a manual launch were blocked [W]. A one-time execution of an unsigned binary does not establish deployment compatibility.
- **What would change the recommendation** is listed in section 8; none of it exists today.
- **Independent of packaging:** the session-capability exposure (F1), the missing evidence-integrity and audit design, and the need for a signed, IT-authorized distribution path. These should be handled in the product whichever packaging is kept (section 7).

## 2. Confirmed Windows findings

| # | Finding | Tag |
| --- | --- | --- |
| 1 | Bundle `88b8047`: host SHA-256 `38b9c719...581e5e`. W04 host started (documented usage exit code), W05 bundled CPython initialised, W06 21 native modules imported, R06 diagnostics reported no enforced block. | [W] |
| 2 | Same bundle: W07 failed. The host exited with code 3 (`ExitStartTimeout`): the backend was still running but no valid READY within 30 s. No enforced Code Integrity record for that run. The cause was not recorded. | [W], [C] for the meaning of code 3 |
| 3 | Bundle `7b4464d`: host SHA-256 `27d654ca...cf05` (a different file: the host source changed). R01 to R04 and W01 to W03 passed. W04 BLOCKED: Code Integrity event 3077 for `saplens-host.exe`, signature `NotSigned`, classified `executable_blocked_by_policy`. W05 to W14 NOT EXECUTED. | [W] |
| 4 | A manual Explorer launch of "the original unsigned Go host" was blocked. The hash and the time of that launch relative to finding 1 are not recorded in the repository. | [W], hash unknown |
| 5 | The runner's scripts carried a Mark-of-the-Web (PowerShell prompts and an `AuthorizationManager` failure in a noninteractive child). Whether `saplens-host.exe` itself carried one was not recorded: the signature inventory does not capture `Zone.Identifier` for the executables. | [W] |
| 6 | Earlier product evidence: an enforcing signed platform policy (`VerifiedAndReputableDesktop` plus a supplemental policy) blocked the unsigned Desktop EXE and the installer's extracted payload (events 3077 and 3033). | [C] `docs/deployment/CODE_SIGNING.md` |

## 3. What the evidence supports about the two outcomes

The operator saw "executed" (finding 1) and "blocked" (findings 3, 4) for unsigned Go hosts. The questions you asked, with what can and cannot be concluded:

| Question | Can be concluded | Cannot be concluded |
| --- | --- | --- |
| Did the hash change? | Yes: `38b9...` to `27d6...`; any change to host source or toolchain changes the file. Both builds are unsigned. | That the hash change caused the different outcome. |
| Does the changed hash explain "blocked now"? | It is one plausible factor: a rule or reputation lookup keyed to file identity treats a new file as new. | That it is the reason. The earlier hash was also unknown to any reputation service as far as the repository can tell, and it ran. |
| Does `NotSigned` matter? | An unsigned file has no publisher for a publisher rule to match. Enforced event 3077 for an unsigned file is what a policy that requires a signature or reputation would produce. | That signing alone would have changed the outcome (a signature is necessary, not sufficient). |
| Is it Smart App Control or administrator-managed WDAC? | Event 3077 and the earlier policy name show an enforcing App Control policy. The earlier evidence names `VerifiedAndReputableDesktop` plus a supplemental policy, which is more consistent with an administrator-managed policy than with Smart App Control (which takes no custom rules); this is an inference. | Which one applies on the test machine, its mode (evaluation, enforced, audit), or whether the mode changed between runs. Not recorded. |
| Mark-of-the-Web and extraction | The scripts carried it (finding 5). A launch through Explorer can add shell checks (SmartScreen) before App Control; a launch by a child process does not. | Whether the host had it, and whether Explorer versus PowerShell launch is the cause. Not recorded. |
| File reputation and execution context | These are plausible inputs to an authorization decision (reputation lookup, launching process, location, time since first seen, policy refresh). | Which of them applied. No evidence isolates one. |
| Does the earlier W04 PASS show reliable execution? | **No.** It shows that once, in one context and at one time, the policy let that file start, and that the interpreter and 21 unsigned native modules loaded. | That it will run again, on another machine, after a rebuild, after a policy refresh, or from another launch path. The same experiment later saw a block. |

Plausible hypotheses for the inconsistency (none confirmed, none preferred): (H1) policy state differed between the times (audit versus enforced, evaluation versus on, policy refresh); (H2) reputation or cloud authorization outcome differs per file and over time; (H3) launch context or process lineage differed (Explorer, harness child, installer-managed); (H4) the files differed in Mark-of-the-Web or location; (H5) something not observed. Do not use any of these as a finding.

Two consequences hold either way: every rebuild of an unsigned file is a new file for any hash- or reputation-based mechanism, so those cannot be a release strategy for either Go or PyInstaller; and acceptance results from a machine where the file was blocked (BLOCKED) or allowed once (PASS) are evidence about that machine's policy at that moment only.

## 4. Architecture comparison

A is the existing architecture (PyInstaller Desktop one-file with pywebview, Windows Server on PyInstaller one-dir with WinSW and the Service Manager, Linux systemd and Docker). B is the experiment. C is A with improved distribution: sign everything, install under an admin-writable folder, obtain an IT-approved policy rule, deploy through an approved channel. The C Desktop could use the one-dir layout the Server already uses [C].

| # | Criterion | A existing | B Go + bundled CPython | C improved distribution |
| --- | --- | --- | --- | --- |
| 1 | App Control | Unsigned EXE blocked [C]. One-file extracts native images to a user-writable temp folder at each start: policy treatment unknown [U]. | Unsigned host blocked, then and now [W]. Python and native images ran once [W], current status unknown [U]. About 50 unsigned images plus the host [M, static]. | Same policy mechanics as A and B; only a signed, authorized set can pass. Not tested [U]. |
| 2 | Signing | EXE, installer, Server EXEs; the one-file's embedded images are not covered by the EXE signature. | Host, interpreter, wheel `.pyd`, DLLs, manifest or catalog: about 52 images plus host [M, static]; re-signing third-party files needs a hash-pair record ([SIGNING_CONTRACT](SIGNING_CONTRACT.md)). | Installer plus the one-dir image set (Windows count not measured [U]). |
| 3 | Install and update | Inno Setup installer exists [C]. | No installer; about 9,000 files; upgrade, rollback and locked-file behaviour unknown [U]. | Existing installer pattern with a file set; Server already works this way [C]. |
| 4 | Footprint | One-file not measured [U]. One-dir stand-in 82.5 MB, 1,575 files [M]. | 171 to 198 MB, 7,700 to 9,343 files [M]; Windows tree 144 MB, 8,411 files [M, static]. | About the one-dir stand-in [M]. |
| 5 | Cold start | One-file not measured; one-dir stand-in 1.29 s [M]. No Windows number [U]. | 0.98 to 1.08 s [M]. Windows: not ready within 30 s, cause unknown [W]. | As A one-dir [M]; no Windows number [U]. |
| 6 | Memory and CPU | 86.0 MiB (one-dir stand-in) [M]; CPU not measured. | 78.8 MiB direct, 87.0 MiB with the host (about 8 MiB for the host) [M]; CPU not measured. | As A. |
| 7 | Reliability and supervision | Desktop is one process with the backend in a thread, no child to supervise [C]; Server supervised by the service manager. | Job Object cleanup and stdin-EOF watchdog: Linux tested [M], Windows never executed [U]. | As A. |
| 8 | Windows service | WinSW wrapper plus a .NET Framework 4.8 Service Manager exist [C]. | Not implemented. A Go service needs `golang.org/x/sys/windows/svc` (outside the standard library) or the same wrapper again. | As A. |
| 9 | Linux | systemd unit and Docker exist [C]. | Host works on Linux [M] but duplicates what systemd already supervises in Server mode. | As A. |
| 10 | Security boundary and attack surface | One process; loopback token boundary with finding F1 [M]. | Adds a process boundary and stdin handoff (tested [M]); adds an unsigned binary and a 9,000-file writable-tree integrity problem; F1 unchanged. | As A, with signed images and an admin-only install folder (reduces tampering). |
| 11 | Dependencies and vulnerabilities | Pinned requirements, PyInstaller and its hooks [C]. | Hash-locked wheels and interpreter [M] (stronger pinning); adds the Go toolchain (`govulncheck` NOT EXECUTED) and python-build-standalone (hash from a TLS-delivered list, not a signature). | As A; can adopt hash-locking. |
| 12 | Development and maintenance | Known. | New language, toolchain, assemble and lock pipeline, PowerShell harness. Highest. | Low to medium. |
| 13 | Testability and release engineering | Existing CI, verifiers (which reject signed files today [C]). | Reproducible bundle and per-file manifest [M] are real strengths; no CI, installer or verifier path exists. | Verifier needs a signed mode ([SIGNING_CONTRACT](SIGNING_CONTRACT.md)). |
| 14 | Migration risk | None. | High: Desktop, Server, installers, verifiers, upgrade path. | Low to medium. |
| 15 | Long-term value | Baseline. | Auditability and reproducibility, which are transferable to A and C without Go. A native host for the Desktop shell is a separate question; a .NET host is already under review ([ADR 0001](../../architecture/decisions/0001-dotnet-desktop-host.md)) and matches the existing Windows tooling. | Incremental, reversible. |

Not claimed anywhere above: any Windows performance figure, any startup or memory improvement of B over A (Linux figures are equal within noise), or any App Control advantage.

## 5. Security and deployment assessment

**Realistic options in a managed Windows environment** (all are decisions for the organization's security administrators; none was created, installed or tested here):

| Mechanism | What it gives | Limits |
| --- | --- | --- |
| Authenticode signing (organization certificate or a cloud signing service) | Proves origin and integrity; gives a publisher identity for rules and for reputation. | Does not authorize anything by itself. Needs key custody, a trusted timestamp, and a signing step for every shipped image. |
| Publisher (signer) rule in an administrator-managed WDAC / App Control policy, usually a supplemental policy | Survives rebuilds and updates as long as the publisher (and optionally product name and version) match. The sustainable option. | Needs IT to add the publisher; the base policy must permit supplemental policies. |
| Deployment through Intune or Configuration Manager, optionally with a managed installer | Approved distribution and update channel; a managed installer can establish trust for what it installs. | Needs IT onboarding and packaging for that channel. |
| File-hash rule | Works for one exact file. | Changes with every build; not maintainable for releases. Signing a file does not change its Authenticode hash, rebuilding does. |
| Path rule | Can authorize an install location. | Honoured only for admin-writable locations; a user-writable extraction folder (the one-file's temp folder, the user profile) does not qualify. |
| Smart App Control | None for enterprise rollout: it is a consumer feature without administrator exceptions. | Cannot be configured to allow a specific application; verify which feature is active on a target machine. |
| Reputation (Intelligent Security Graph, SmartScreen) | May allow widely seen files. | Not controllable, slow for new files, and not a release process. |

Signing an executable and obtaining policy authorization are different steps: the first creates something a policy can recognise, the second is the organization's decision.

**Does Go give a meaningful advantage over PyInstaller here? No, on the evidence.** The policy sees PE files. A Go host is one more PE; the interpreter and native images must be authorized in both designs. The only structural difference that matters is where files live: an installed, admin-writable tree (B, or PyInstaller one-dir) can be covered by publisher and path rules, whereas the one-file EXE extracts into a user-writable folder. That advantage belongs to the one-dir layout, which PyInstaller already provides (the Server uses it) and which needs no Go.

## 6. Outstanding risks and unknowns

| Item | Applies to | Status |
| --- | --- | --- |
| W07: backend not ready within 30 s | B (host path); a slow cold start is conceivable for any packaging | Cause unknown. The instrumentation (phases, stack dump, W07a direct start) has never run on Windows [U]. |
| Diagnostic harness code | B tooling | Linux-tested only; the W07 branch and W07a have not executed on Windows [U]. |
| F1: session capability obtainable by any local HTTP client sending `Sec-Fetch-*` headers | **All options** (existing backend behaviour) | Open; reproduced [M]; remediation design in [CAPABILITY_BOOTSTRAP](CAPABILITY_BOOTSTRAP.md). Not caused or fixed by packaging. |
| Runtime extraction and integrity | A one-file: re-extracted each launch; B: 9,000-file tree; C: install folder | Needs install-time verification, start-time verification of the executable set, and an admin-only folder. `unchecked-hash` `.pyc` files are not checked against source. Applies to every layout, largest in B. |
| Process isolation and cleanup | A single process; B Job Object; C as A | B's Windows cleanup never executed [U]; the stdin watchdog and Job Object cannot be told apart. |
| Windows service requirements | A and C exist; B none | B would need a service wrapper or a new service implementation. |
| SQLite persistence and upgrade safety | **All options** | Not examined by this experiment. B changes the upgrade mechanics (replacing a large tree, locked files, rollback) and has no verified path [U]. |
| Evidence integrity and audit | **All options** | The harness evidence is plain JSON and text: no signing, no hash chain, and the operator-reported results are not in the repository. Acceptance evidence for a managed environment needs a defined, tamper-evident record. |
| Whether the organization's policy would accept any publisher for this product | **All options** | Unknown; decides everything in section 5. |

## 7. Decision

**STOP** (Go + bundled CPython as a migration candidate). Reasons, each from evidence:

1. The hypothesis that a different packaging technology improves App Control compatibility is not supported: a new unsigned binary was blocked [W]; the earlier pass was not repeatable [W]; an enforcing policy needs signing and authorization for every option.
2. No benefit was measured: startup and memory are equal within noise [M]; footprint is 2.1 to 2.4 times and files 5 to 6 times larger [M].
3. The benefits that exist (hash-locked inputs, reproducible bundle, per-file manifest) do not require Go and can be applied to the current build.
4. B duplicates supervision that the service manager and systemd already provide in Server mode, and has no service, installer, upgrade or verifier path.

STOP is not PAUSE because pausing would wait for evidence (W07, Windows measurements) that cannot change reasons 1 to 4: even a perfect W07 would leave B equal to C on App Control and larger on footprint.

**Smallest practical next step (not started):** obtain, read-only and with the administrators' agreement, the facts the repository lacks: the active policy names, IDs and mode behind event 3077 on the test machine, whether the policy allows supplemental policies or a managed installer, whether Smart App Control is on, and whether the host carried a Mark-of-the-Web. Then ask one question that decides every option: would IT authorize a publisher rule for a signed SAP Lens (installer, EXEs, one-dir image set)? Until that is answered, no packaging choice can be validated.

**Worth doing regardless of packaging** (separate work, not started): remediate F1; add a defined install-time and start-time integrity check; define tamper-evident acceptance evidence; evaluate Option C (signed one-dir Desktop under an admin-writable folder) once a test certificate and policy path exist.

## 8. Phase 2 go/no-go criteria (if the direction is ever reopened)

All must hold. Numeric thresholds are proposals for the decision-makers to confirm or change, not measured requirements. "Reference" means the improved existing packaging (option C one-dir) measured on the same machines in the same session.

| Area | Go only if | No-go if |
| --- | --- | --- |
| Enterprise App Control compatibility | The organization's policy (named, with mode) is documented; IT has approved a concrete mechanism (publisher rule or equivalent) for the host and every image; a signed bundle runs W04 to W14 with zero enforced 3077 or 3033 events on at least two managed machines, repeated after a reboot and on a later day. | Any enforced block on a signed, authorized set; reliance on a hash rule, a one-off pass, an exclusion, or a policy change by the tester. |
| Successful backend startup | W07 passes in at least 10 consecutive runs on a managed machine, cold and warm; the cause of the 30 s timeout is identified and fixed. | W07 still intermittent or unexplained. |
| Security | F1 remediated in the product with its regression tests; install-time and start-time integrity verification implemented and tested; W09 and W12 pass on Windows (no orphans); no secret in arguments, environment, logs or evidence on Windows; evidence record is tamper-evident. | Any open High finding, or integrity checks only on Linux. |
| Performance | Windows cold and warm time-to-ready, memory and install time measured for B and the reference, at least 10 runs each; B within 15% of the reference on each. | Any metric materially worse without a compensating, demonstrated benefit. |
| Packaging footprint | Installed size and file count no more than 1.5 times the reference (today 2.1 to 2.4 times and 5 to 6 times [M]); AV scan and install time measured. | Footprint above that without justification. |
| Maintenance complexity | A named owner and a written process for CPython security releases, wheel and Go toolchain updates (including `govulncheck` actually running), signing and re-signing, and a count of removed PyInstaller-specific workarounds at least equal to the added Go, assemble and harness code. | Net increase in release steps or tooling with no offsetting removal. |

## 9. Historical decisions (kept for the record)

- **Phase 0 (`843c005`, Linux only):** conditional GO to a Windows-gated Phase 1; NO-GO for any migration. See [DECISION](DECISION.md).
- **Phase 1 (`e9a0680`, Linux preparation):** INCOMPLETE; NO-GO for Phase 2 until Windows evidence existed. That evidence now exists (section 2) and leads to the recommendation above.
- **Windows runs:** `4a30de3` stopped at R04 (script authorization in a noninteractive child), `55bce78` at a Windows PowerShell 5.1 lint assertion (both tooling defects, fixed), `88b8047` reached W07 and timed out, `7b4464d` was blocked at W04. See [PHASE1](PHASE1.md).
- The earlier assessment that the Go-versus-.NET question for a Desktop shell is separate still stands: [ADR 0001](../../architecture/decisions/0001-dotnet-desktop-host.md) is Proposed and is not decided by this document.

### Earlier decision text (superseded by sections 1 to 8, unchanged)

#### Result: INCOMPLETE. The Windows gate was not passed.

Windows execution was unavailable, so criteria 1, 2 and 4 cannot be assessed and the phase is not a success. Nothing in this repository reports a Windows pass.

#### Recommendation: NO-GO for Phase 2. Re-run Phase 1 on Windows first.

This is **not** a verdict against the architecture. It is a gate that has not been tested:

- **What is established (Linux and static analysis):** lifecycle, loopback boundary and secret handling work; the build is reproducible; the bundle for Windows builds reproducibly; about 50 unsigned images from three origins plus the host would have to pass App Control; the benefit over the existing packaging is auditability, not size or speed, and the one-file product has its own unsolved extraction problem under App Control.
- **What decides it, and only Windows can answer:** whether the organization's policy accepts a signer (or any other IT-approved rule) for roughly 50 images in an install folder, and how the existing one-file product behaves under the same policy once signed.
- **Independent of the outcome:** finding F1 (capability handed to any local HTTP client) should be addressed in the product itself, whichever packaging wins ([CAPABILITY_BOOTSTRAP](CAPABILITY_BOOTSTRAP.md)).

#### What would turn this into a GO

All of these on a Windows machine with the real policy enforced, evidence in the format of [WINDOWS_VALIDATION](WINDOWS_VALIDATION.md):

1. Harness stages W01 to W13 PASS, or the BLOCKED stages are traced to specific files with enforced Code Integrity events.
2. A concrete, IT-approved path for those files (for example a signer rule for one publisher), stated by the security administrator, not inferred.
3. A measured Windows comparison with the one-dir and one-file builds (startup, memory, size, files, install time, antivirus scan).
4. A decision on class C re-signing versus an upstream-signed interpreter ([SIGNING_CONTRACT](SIGNING_CONTRACT.md)).

#### Stop criteria

Stop the experiment if App Control blocks the unsigned third-party images and IT offers no acceptable signing or allow-list path, or if the measured Windows cost in files and scan time outweighs the auditability gain. Then the existing packaging stays, and the host would be considered only as a separate Desktop-shell question.

#### Not done, by instruction

No installer, no application functionality migrated, no CI, version, signing or verifier change, no merge into `work` or `main`.
