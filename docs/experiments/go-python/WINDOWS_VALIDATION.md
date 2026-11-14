# Windows validation: instructions and evidence template

Run on a disposable or dedicated Windows 10/11 x64 test machine, as a normal (non-elevated) user, **with the machine's real App Control policy enforced**. Do not add exclusions, change policy, disable Defender or use `-ExecutionPolicy Bypass`. If PowerShell script execution is itself restricted, stop and record the stage as BLOCKED; ask IT.

Never run on a machine with SAP Lens installed in production, and never point the harness at an SAP Lens installation or data directory (it refuses paths inside `...\SAP Lens`). All data is synthetic and lives in a unique temp folder `saplens-poc-<id>`, removed afterwards.

## 1. Build the bundle (Linux, once)

```
python experiments/go-python/windows/make_bundle.py --out /tmp/p1bundle        # add --prune for the smaller tree
```

Output: `saplens-host.exe`, `runtime.tar.gz`, `scripts\`, `SHA256SUMS.txt`. Two builds give identical hashes (checked). The Windows tree is assembled on Linux and has never been run on Windows (experimental).

## 2. Verify and extract (Windows PowerShell 5.1 or 7)

```powershell
$b = 'C:\poc'                                   # folder you copied the bundle to; use a short path (deep site-packages)
Set-Location $b
Get-Content .\SHA256SUMS.txt | ForEach-Object { $h,$f = $_ -split '\s+',2; if ((Get-FileHash -Algorithm SHA256 $f).Hash.ToLower() -ne $h) { "MISMATCH $f" } }
New-Item -ItemType Directory -Force .\runtime | Out-Null
tar.exe -xzf .\runtime.tar.gz -C .\runtime       # built-in bsdtar (Windows 10 1803+)
powershell -NoProfile -File .\scripts\Test-Phase1Logic.ps1      # pure logic self-test, expect: all assertions passed
```

Record whether the extraction itself triggered any policy or Defender action (the extracted `python.exe` and `.pyd` files may be blocked or quarantined: that is evidence, record it).

## 3. Run the harness

```powershell
powershell -NoProfile -File .\scripts\Test-WindowsFeasibility.ps1 -HostExe .\saplens-host.exe -RuntimeDir .\runtime -OutDir .\evidence
```

Exit code: 0 all PASS, 1 any FAIL, 2 any BLOCKED, 3 not executed or incomplete. Result: `evidence\phase1-windows-result.json`, plus `evidence\signature-inventory.json`.

## 4. App Control diagnostics (read-only; run right after any BLOCKED or FAIL)

```powershell
powershell -NoProfile -File .\scripts\Get-AppControlDiagnostics.ps1 -RuntimeDir .\runtime -HostExe .\saplens-host.exe -SinceMinutes 30 -OutDir .\evidence
```

Reading the Code Integrity log and `CiTool.exe --list-policies` may need elevation. If not permitted, the result says so as a limitation: an empty result without log access is not proof of no block. Also state the policy name and whether it is the organization's or a Microsoft default.

## 5. Stages

| Stage | What it proves | A failure means |
| --- | --- | --- |
| W01 preflight | isolated identity, language mode, policy listing | refused unsafe paths |
| W02 manifest integrity | extracted tree equals the assembled tree (SHA-256 of every file) | extraction or AV changed files |
| W03 signature inventory | Authenticode state and hash of every exe, dll, pyd (recorded, not judged) | n/a |
| W04 Go host starts | the host executes (usage exit 1) | BLOCKED if a documented policy code (1260, 4551) or an enforced event names the host |
| W05 CPython initialises | `python.exe -I` runs, version 3.12.11, isolated, prefix inside the tree | BLOCKED if the interpreter is refused |
| W06 native extensions | each `.pyd` imports in its own process, so a block names the file | BLOCKED only with an enforced event for that file; an ImportError alone is `native_load_failure_unclassified` |
| W07 backend, frontend, capability, boundary | READY, `/health`, React served, capability on page, 403 without or with a wrong capability, 200 with the issued one, foreign Host and Origin 403, loopback-only listener, no secret in command lines, stderr or data files | FAIL names the failed checks |
| W08 graceful shutdown | host exit 0 after its hold, backend gone | |
| W09 forced host kill | `TerminateProcess` of the host leaves no child. Job Object and the backend's stdin watchdog both apply and cannot be separated here | |
| W10 start timeout | exit 3, no leftover process | |
| W11 foreign data directory | exit 2, foreign file untouched | |
| W12 no orphans | no process from the runtime or host path outlived the test | |
| W13 measurements | one-run ready time and peak working set. Windows-only numbers; do not compare with Linux | |
| W14 Code Integrity correlation | enforced (3077, 3033) and audit-only (3076) records below the runtime root | BLOCKED if enforced; NOT EXECUTED if the log is unreadable |

Not checked even on Windows: process environment blocks (unreadable without debug rights) and the installer (none exists).

## 6. Evidence report (current state)

Environment: Linux only. Windows host: none.

| Stage | Status | Reason |
| --- | --- | --- |
| W01 to W14 | NOT EXECUTED | no Windows host available in this session |
| Harness parse, logic self-test, non-Windows path, forbidden-operation scan | PASSED (Linux) | not Windows validation |

Fill in after a Windows run: OS build, PowerShell version, policy names (not machine or user names), overall result, per-stage status and the evidence JSON. Report a policy block as BLOCKED, never as FAIL or as an application defect.
