# Windows validation runbook (Phase 1)

Status: **NOT EXECUTED.** Nothing here has run on Windows. The runner and harness are validated only on Linux (static checks, logic tests, real-bundle verification, non-Windows and Constrained Language Mode behaviour). A Windows result exists only after someone runs the command below on a Windows machine.

Run it on a disposable or dedicated Windows 10/11 x64 test machine, as a normal (non-elevated) user, **with the machine's real App Control policy enforced**. All data is synthetic. It never installs or replaces SAP Lens and never touches services, databases, the registry, Windows security policy, Defender or App Control.

## Prerequisites (Windows target)

| Item | Requirement |
| --- | --- |
| OS | Windows 10 (1803 or later) or 11, x64. ARM64 is refused |
| PowerShell | Windows PowerShell 5.1 or PowerShell 7, **FullLanguage** mode, normal (non-elevated) session |
| Script execution | Local unsigned `.ps1` must be allowed by IT. Do not change the execution policy. Copy the bundle by share or USB: a browser download adds a Mark-of-the-Web that some policies block. Do not use `Unblock-File` or `-ExecutionPolicy Bypass` without IT approval |
| Tools | the system `System32\tar.exe` only. No Go, Python, Node or Git is needed |
| Disk | at least 700 MB free; keep paths short (longest archive member is 116 characters; the runner refuses a path that would exceed MAX_PATH) |
| Not on | a OneDrive-synced folder. The default run folder is `%USERPROFILE%\saplens-phase1` |
| Do not | add antivirus or App Control exclusions, change policy, or run two runs at once |

## 1. Build the bundle on Linux

Needs Go 1.24.x, Python 3.12 and network access to GitHub releases and PyPI (first build only), from a checkout of the commit you want to test:

```bash
git checkout --detach <commit>
python experiments/go-python/windows/make_bundle.py --out /tmp/p1bundle
```

It cross-compiles `saplens-host.exe` (`CGO_ENABLED=0`, `-trimpath`, `-buildvcs=false`), assembles the hash-locked Windows runtime on Linux and writes `SHA256SUMS.txt`. It prints `sums_sha256` and repeats it on stderr: that value is the **trusted checksum**. Two builds of the same commit produce an identical `SHA256SUMS.txt` (tested). The value changes with the commit (the archive manifest records the source commit) and with the Go toolchain version.

The Windows tree is assembled on Linux and is experimental.

## 2. Transfer safely

- Copy the whole `/tmp/p1bundle` folder to the Windows machine by approved share or USB.
- Send the trusted checksum **through a different channel** than the bundle (message, spoken, ticket). Never store it inside the bundle: a checksum delivered with the files proves nothing.
- Keep the bundle folder read-only for others. The runner verifies it again after copying it into the run folder.

## 3. Optional: verify only (executes nothing from the bundle)

```powershell
$b = Join-Path $env:USERPROFILE 'saplens-bundle'          # where you copied the bundle
powershell -NoProfile -File "$b\scripts\Run-Phase1.ps1" -BundleDir $b -TrustedSumsSha256 '<64 hex characters received separately>' -VerifyOnly
"exit code: $LASTEXITCODE"                                 # 0 = verified; 3 = stopped. This is NOT a Phase 1 result
```

## 4. Run Phase 1 (one command)

```powershell
$b = Join-Path $env:USERPROFILE 'saplens-bundle'
powershell -NoProfile -File "$b\scripts\Run-Phase1.ps1" -BundleDir $b -TrustedSumsSha256 '<64 hex characters received separately>'
"exit code: $LASTEXITCODE"
```

The script must be run from the `scripts` folder of the bundle it verifies. It refuses an elevated session (`-AllowElevated` needs a written `-ElevationJustification`; nothing here needs it).

What it does, in order (each step is recorded even if it fails):

| Step | Action | Stops the run when |
| --- | --- | --- |
| R01 prerequisites | Windows x64, FullLanguage, not elevated, system `tar.exe`, disk space, no overlapping run, script is inside the bundle it verifies, folder is not an SAP Lens install or data path | any condition cannot be established (NOT EXECUTED) |
| R02 bundle integrity | `SHA256SUMS.txt` must equal the trusted checksum; every listed file must match; no extra, missing or linked file; the bundle is copied to the run folder and verified again | any mismatch (NOT EXECUTED) |
| R03 archive safety and extraction | every archive member is validated first (no `..`, absolute or drive paths, backslashes, streams, links, device names, over-long paths); extracted only into the run folder; afterwards no link, nothing outside the folder, file count equals the listing | any problem or tar failure (NOT EXECUTED) |
| R04 logic self-test | `Test-Phase1Logic.ps1`, in this session | PowerShell refuses to authorize it (NOT EXECUTED, security restriction); an assertion fails or the script errors (HARNESS ERROR, harness not run) |
| R05 isolated feasibility harness | `Test-WindowsFeasibility.ps1`, in this session, with `TEMP`/`TMP` pointing into the run folder for its duration; stages W01 to W14 | PowerShell refuses to authorize it (NOT EXECUTED); otherwise its result is classified (see below) |
| R06 App Control diagnostics | `Get-AppControlDiagnostics.ps1` read-only, in this session, where permitted | never stops the run; unreadable log or a refusal to authorize it means NOT EXECUTED for this step |

Isolation by construction: each run has its own folder `%USERPROFILE%\saplens-phase1\<run id>\` (bundle copy, extracted runtime, evidence, temp). The host starts the backend with `TEMP`, `TMP`, `USERPROFILE`, `APPDATA`, `LOCALAPPDATA` and `PROGRAMDATA` redirected into the isolated data directory, so no library fallback reaches `C:\TEMP`, the real profile or `C:\ProgramData`. The backend configuration directory is set explicitly. Isolation is not "proved" by scanning system folders.

Process cleanup: only processes this run created are stopped (recorded PID and start time, parent chain, running from the run's runtime tree or the run's host file). Nothing is matched by name, so another run, another user or an installed SAP Lens is never touched. No secret appears in command lines, environment or logs: the capability exists only between the host, the backend and the harness's HTTP requests, and the harness searches command lines, stderr and data files for it.

Nothing is deleted. The run folder, the extracted runtime and the evidence stay for review.

### Script authorization and Mark-of-the-Web

A bundle copied from a downloaded ZIP can carry a Mark-of-the-Web (`Zone.Identifier`) on every script. With an effective execution policy of `Unrestricted`, PowerShell then asks "Do you want to run software from this untrusted publisher?" for each such script it loads; with `RemoteSigned` or stricter it refuses them.

- **First Windows run (observed):** R01 to R03 passed; R04 failed with `AuthorizationManager check failed.` and exit code 1. The run used a separate `powershell -NonInteractive` child for the self-test, which cannot answer that prompt. This explanation fits the evidence (policy `Unrestricted` for the current user, prompts shown for the runner and `Phase1Common.ps1`, the child started noninteractively) and the code, but it could not be reproduced here: Linux has no Mark-of-the-Web or execution policy. Only the mechanism is tested (see the limitations).
- **Fix:** the runner now runs the self-test, harness and diagnostics in its own interactive session, where the standard prompt is shown to the person at the keyboard. The shared helpers are loaded once, so expect at most three additional prompts (self-test, harness, diagnostics) on top of those for the runner and `Phase1Common.ps1`. Answer `R` (Run once) for each, or avoid the prompts by copying the bundle without the mark (network share, USB).
- **Not done, on purpose:** the runner never unblocks files, never removes `Zone.Identifier`, never changes the execution policy or language mode, never uses `-ExecutionPolicy Bypass` and never starts a bundle script in a noninteractive child.
- **R01 records** the effective policy, every scope, which scripts carry the mark and whether the session is interactive (`run-summary.json`, section `authorization`). If the policy is `Restricted`, `AllSigned`, or `RemoteSigned` with marked scripts, or a prompt would be needed in a noninteractive session, the run stops there as NOT EXECUTED with the reason.
- **If PowerShell refuses a script later,** the result is NOT EXECUTED with the original error type, id and message preserved (`errors` in `run-summary.json`, plus `*-error.txt`). The classification uses the error type (`PSSecurityException` / `SecurityError`), never the wording. A failing assertion is a different result: HARNESS ERROR.

## 5. Where the reports are

`%USERPROFILE%\saplens-phase1\<run id>\evidence\`

| File | Content |
| --- | --- |
| `run-summary.txt`, `run-summary.json` | overall result, exit code, every step, raw exit codes of tar and each tool, stop reason |
| `harness\phase1-windows-result.json` | stages W01 to W14 with evidence |
| `harness\signature-inventory.json` | SHA-256 and Authenticode state of every exe, dll, pyd |
| `harness-console.txt`, `logic-selftest.txt`, `tar-extract.txt`, `diagnostics-console.txt` | captured output of each tool |
| `logic-selftest-error.txt`, `harness-error.txt`, `diagnostics-error.txt` | the original terminating error, if a script ended with one (only then) |
| `diagnostics\app-control-diagnostics.json` | policies and Code Integrity records, file hashes, assigned stage |

Find the latest run and read the summary:

```powershell
$run = Get-ChildItem (Join-Path $env:USERPROFILE 'saplens-phase1') -Directory | Sort-Object Name | Select-Object -Last 1
Get-Content "$($run.FullName)\evidence\run-summary.txt"
```

Review the files before sharing: they contain policy IDs and names, certificate subjects and relative file paths, not user or host names (the profile folder is abbreviated).

## 6. Exit codes and results

| Result | Exit | Meaning |
| --- | --- | --- |
| **PASS** | 0 | every executed harness stage passed |
| **FAIL** | 1 | the application ran and a criterion was not met |
| **BLOCKED** | 2 | the OS refused a file: a documented native code (1260, 4551) or an enforced Code Integrity record (3077, 3033). Nothing about the application was verified. A missing signature alone is not a block |
| **NOT EXECUTED** | 3 | a precondition or integrity check stopped the run, or a stage did not run. Never counts as a pass. Includes Constrained Language Mode, a failed checksum, a refused archive, a non-Windows host |
| **HARNESS ERROR** | 4 | the tooling failed: result file missing, unreadable or inconsistent with the exit code, self-test failure, timeout, unexpected error, or conflicting evidence (harness PASS but enforced block records found). Neither a pass nor an application failure |

Raw exit codes of tar and every tool are recorded in `run-summary.json` and never remapped. `-VerifyOnly` returns 0 when verification passed and is not a Phase 1 result. A missing `phase1-windows-result.json` is always HARNESS ERROR, never FAIL or PASS.

Harness stages: W01 preflight, W02 manifest integrity, W03 signature inventory, W04 host starts, W05 CPython initialises, W06 each native extension loads, W07 backend, frontend, capability and boundary checks (including the issued capability returning 200 and a wrong one 403), W08 graceful shutdown, W09 forced host kill, W10 start-timeout cleanup, W11 foreign data directory refused, W12 no orphans, W13 measurements, W14 Code Integrity correlation. Where a block can occur: see [APP_CONTROL](APP_CONTROL.md).

## 7. Optional elevated read-only diagnostics (separate from the main test)

Only if the Code Integrity log or `CiTool --list-policies` was not readable and IT permits it. Run the main test first, non-elevated; then, in a separate elevated window (read-only, changes nothing):

```powershell
$run = Get-ChildItem (Join-Path $env:USERPROFILE 'saplens-phase1') -Directory | Sort-Object Name | Select-Object -Last 1
powershell -NoProfile -File "$($run.FullName)\bundle\scripts\Get-AppControlDiagnostics.ps1" -RuntimeDir "$($run.FullName)\runtime" -HostExe "$($run.FullName)\bundle\saplens-host.exe" -SinceMinutes 120 -OutDir "$($run.FullName)\evidence\diagnostics-elevated"
"exit code: $LASTEXITCODE"       # 0 no enforced block found, 2 enforced block(s), 3 not Windows
```

## 8. Known limitations

- **No hard timeout for the harness.** It runs in the runner's session, so it is bounded only by its own per-stage timeouts (import 30 s, backend ready 40 s, graceful stop 60 s). Close the window to stop a hung run; processes it created are stopped by the harness's own cleanup when it ends.
- **Authorization is tested by mechanism only.** Typed detection of `PSSecurityException`, in-session execution, exit-code handling and environment restore are tested on Linux with simulated errors; the real `AuthorizationManager` prompt, `Zone.Identifier`, execution policy precedence and PowerShell 5.1 behaviour are NOT EXECUTED here. A PowerShell 5.1 syntax lint (no ternary, `??`, pipeline chains, `-Parallel`, three-argument `Join-Path` and similar) runs on every script.
- **Nothing has run on Windows.** The runner's Windows paths (R03 to R06) and the harness stages are checked only by parsing, a static lint (every command resolves, helper functions are called with a plausible argument count), unit tests of the helpers they call (bundle verification, archive validation, outcome classification, process ownership, child-process and in-session script handling) and Linux runs of the entry points. Expect to find defects on first Windows execution; a HARNESS ERROR is a result, not a surprise.
- Constrained Language Mode (for example under an enforcing App Control policy for unsigned scripts) stops the run with NOT EXECUTED and a report. Do not work around it.
- W06 probes only site-packages `.pyd` files one by one; the standard-library `.pyd` and DLL files load for the first time in W07, so a block there appears as "no READY line" and is classified from Code Integrity records, not from the file name.
- Job Object cleanup and the backend's stdin watchdog both end the backend when the host is killed and cannot be told apart here.
- Process environment blocks are not readable without debug rights, so "no secret in the environment" is checked on Linux only.
- Python on Windows may read `Software\Python\PythonCore` registry keys when building `sys.path` (read-only). Optional check: `& "$($run.FullName)\runtime\python\python.exe" -I -c "import sys; print('\n'.join(sys.path))"` and confirm every line is inside the run's runtime folder.
- `Get-AuthenticodeSignature` on Microsoft-signed DLLs may make revocation lookups over the network.
- Stopping a leftover process re-checks identity just before the call; a PID reused inside that millisecond window is theoretically possible and accepted.
- The mutex prevents overlapping runs only within one logon session; separate sessions are kept apart by ownership checks and separate run folders.
- The bundle cannot be built on Windows (the Windows tree is compiled with a Linux interpreter). The host hash depends on the Go version; the trusted checksum depends on the commit.
- `govulncheck` was not run (database unreachable from the build environment).
