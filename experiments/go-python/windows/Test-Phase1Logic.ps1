# Self-test of the pure logic in Phase1Common.ps1 with synthetic data. Runs on Linux or Windows PowerShell; exits non-zero on the first failed assertion.
# It does not touch Windows policy, registry or any installed application.
# Loaded once by Run-Phase1.ps1 when this runs in-process (a second load would raise another authorization prompt for marked files).
if (-not (Get-Command Get-OverallVerdict -ErrorAction SilentlyContinue)) { . (Join-Path $PSScriptRoot 'Phase1Common.ps1') }
$ErrorActionPreference = 'Stop'
$failures = 0
function Assert-Equal($Actual, $Expected, [string]$Name) {
    if ("$Actual" -ne "$Expected") { Write-Host "FAIL $Name : expected '$Expected' got '$Actual'"; $script:failures++ } else { Write-Host "ok   $Name" }
}
$root = 'C:\Temp\poc-test\runtime'
$t0 = [datetime]'2026-01-01T10:00:00'; $from = $t0; $to = $t0.AddMinutes(5)
$dev = @{ Id = 3077; Time = $t0.AddMinutes(1); File = '\Device\HarddiskVolume3\Temp\poc-test\runtime\python\Lib\site-packages\pydantic_core\_pydantic_core.cp312-win_amd64.pyd'; PolicyId = '{11111111-2222-3333-4444-555555555555}' }
$audit = @{ Id = 3076; Time = $t0.AddMinutes(1); File = 'C:\Temp\poc-test\runtime\python\python.exe'; PolicyId = 'not recorded' }
$other = @{ Id = 3077; Time = $t0.AddMinutes(1); File = 'C:\Program Files\SAP Lens\SAP-Lens.exe'; PolicyId = 'x' }
$late = @{ Id = 3077; Time = $t0.AddHours(2); File = 'C:\Temp\poc-test\runtime\python\python.exe'; PolicyId = 'x' }
$neighbour = @{ Id = 3077; Time = $t0.AddMinutes(1); File = 'C:\Temp\poc-test\runtime-evil\python\python.exe'; PolicyId = 'x' }
$records = @(Select-RuntimeIntegrityRecords @($dev, $audit, $other, $late, $neighbour) $root $from $to)
Assert-Equal $records.Count 2 'only events under the runtime root inside the window are kept (device path, audit; not other app, not late, not sibling dir)'
Assert-Equal (@($records | Where-Object { $_.Enforced }).Count) 1 'audit-only 3076 is not enforced'

$ext = Get-FailureClass 'extension' $null 'ImportError' @($records) @{ ExitCode = 1 }
Assert-Equal $ext.Class 'native_extension_blocked' 'enforced event on a .pyd classifies as native extension blocked'
$noEvidence = Get-FailureClass 'extension' $null 'ImportError' @() @{ ExitCode = 1 }
Assert-Equal $noEvidence.Class 'native_load_failure_unclassified' 'ImportError without event is NOT called a block'
$auditOnly = Get-FailureClass 'extension' $null 'ImportError' @($records | Where-Object { -not $_.Enforced }) @{ ExitCode = 1 }
Assert-Equal $auditOnly.Class 'native_load_failure_unclassified' 'audit-only record is not a block'
Assert-Equal (Get-FailureClass 'extension' $null 'ModuleNotFoundError' @() @{ ExitCode = 1 }).Class 'missing_dependency' 'ModuleNotFoundError is a missing dependency'
Assert-Equal (Get-FailureClass 'extension' $null '' @() @{ ExitCode = 0 }).Class 'ok' 'exit 0 is ok'
Assert-Equal (Get-FailureClass 'host' 4551 '' @() @{}).Class 'executable_blocked_by_policy' 'native code 4551 blocks the host'
Assert-Equal (Get-FailureClass 'host' 1260 '' @() @{}).Class 'executable_blocked_by_policy' 'native code 1260 blocks the host'
Assert-Equal (Get-FailureClass 'host' 193 '' @() @{}).Class 'executable_start_failure_unclassified' 'other native code is not a block'
Assert-Equal (Get-FailureClass 'interpreter' 4551 '' @() @{}).Class 'interpreter_blocked' 'interpreter blocked by code'
Assert-Equal (Get-FailureClass 'interpreter' $null '' @() @{ ExitCode = 3 }).Class 'application_startup_failure' 'interpreter ran but failed'
Assert-Equal (Get-FailureClass 'application' $null '' @() @{}).Class 'application_startup_failure' 'startup failure without event'
Assert-Equal (Get-FailureClass 'installer' $null '' @() @{}).Class 'installer_failure' 'installer stage is reported, not invented'

$names = Get-PydModuleNames @('python/Lib/site-packages/pydantic_core/_pydantic_core.cp312-win_amd64.pyd', 'python/Lib/site-packages/_cffi_backend.cp312-win_amd64.pyd', 'python/DLLs/_ssl.pyd', 'python/Lib/site-packages/x/y.pyd')
Assert-Equal ($names -join ',') '_cffi_backend,pydantic_core._pydantic_core,x.y' 'pyd paths map to importable module names; stdlib DLLs are not probed'

Assert-Equal (Get-OverallVerdict @(@{ status = 'PASS' }, @{ status = 'PASS' })) 'PASS' 'all pass'
Assert-Equal (Get-OverallVerdict @(@{ status = 'PASS' }, @{ status = 'NOT EXECUTED' })) 'INCOMPLETE' 'a not-executed stage prevents PASS'
Assert-Equal (Get-OverallVerdict @(@{ status = 'FAIL' }, @{ status = 'BLOCKED' })) 'BLOCKED' 'BLOCKED outranks FAIL'
Assert-Equal (Get-OverallVerdict @()) 'NOT EXECUTED' 'no stages'
Assert-Equal (Get-OverallVerdict @(@{ status = 'NOT EXECUTED' }, @{ status = 'NOT EXECUTED' })) 'NOT EXECUTED' 'all not executed is not INCOMPLETE'

$secret = 'abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG'
Assert-Equal ((Find-Secret $secret @('cmd --x', "token=$secret", '')) -join ',') '1' 'secret located by index, never echoed'
Assert-Equal (Find-Secret 'short' @('short')).Count 0 'short strings are not treated as secrets'

# ---- runner support: bundle verification against a separately supplied checksum -------------------------------------------------------------------
function New-TestDir { $d = Join-Path ([System.IO.Path]::GetTempPath()) ('p1logic-' + [guid]::NewGuid().ToString('N').Substring(0, 10)); New-Item -ItemType Directory -Force $d | Out-Null; return $d }
function New-TestBundle {
    $d = New-TestDir; New-Item -ItemType Directory -Force (Join-Path $d 'scripts') | Out-Null
    foreach ($f in (Get-RequiredBundleFiles)) { Set-Content -LiteralPath (Join-Path $d ($f -replace '/', [System.IO.Path]::DirectorySeparatorChar)) -Value "synthetic $f" -Encoding ASCII }
    $lines = foreach ($f in ((Get-RequiredBundleFiles) | Sort-Object)) { '{0}  {1}' -f (Get-FileHash -LiteralPath (Join-Path $d ($f -replace '/', [System.IO.Path]::DirectorySeparatorChar)) -Algorithm SHA256).Hash.ToLower(), $f }
    ($lines -join "`n") + "`n" | Set-Content -LiteralPath (Join-Path $d 'SHA256SUMS.txt') -Encoding ASCII -NoNewline
    return @{ Dir = $d; Trusted = (Get-FileHash -LiteralPath (Join-Path $d 'SHA256SUMS.txt') -Algorithm SHA256).Hash.ToLower() }
}
$b = New-TestBundle
Assert-Equal @(Test-BundleSums $b.Dir $b.Trusted).Count 0 'intact bundle verifies against the trusted checksum'
Assert-Equal (@(Test-BundleSums $b.Dir ('0' * 64)) -join '|') 'SHA256SUMS.txt does not match the trusted checksum' 'wrong trusted checksum stops before anything is parsed'
Assert-Equal (@(Test-BundleSums $b.Dir 'not-hex')) 'the trusted checksum is not a SHA-256 hex string' 'malformed trusted checksum is refused'
Add-Content -LiteralPath (Join-Path $b.Dir 'runtime.tar.gz') -Value 'tampered'
Assert-Equal (@(Test-BundleSums $b.Dir $b.Trusted) -join '|') 'changed: runtime.tar.gz' 'a changed file is detected'
$b = New-TestBundle; Set-Content -LiteralPath (Join-Path $b.Dir 'scripts/extra.ps1') -Value 'x'
Assert-Equal (@(Test-BundleSums $b.Dir $b.Trusted) -join '|') 'unexpected file: scripts/extra.ps1' 'an extra file is detected'
$b = New-TestBundle; Remove-Item -LiteralPath (Join-Path $b.Dir 'saplens-host.exe')
Assert-Equal (@(Test-BundleSums $b.Dir $b.Trusted) -join '|') 'missing: saplens-host.exe' 'a missing file is detected'
$b = New-TestBundle; Add-Content -LiteralPath (Join-Path $b.Dir 'SHA256SUMS.txt') -Value ('{0}  ../outside' -f ('a' * 64)) -Encoding ASCII
Assert-Equal (@(Test-BundleSums $b.Dir $b.Trusted)).Count 1 'a tampered sums file fails the trusted checksum (not parsed)'
# a sums file that matches its own trusted hash but lists an unsafe path
$b = New-TestBundle
$unsafe = ((Get-Content -LiteralPath (Join-Path $b.Dir 'SHA256SUMS.txt')) + ('{0}  ../outside' -f ('a' * 64))) -join "`n"
Set-Content -LiteralPath (Join-Path $b.Dir 'SHA256SUMS.txt') -Value $unsafe -Encoding ASCII
$trusted = (Get-FileHash -LiteralPath (Join-Path $b.Dir 'SHA256SUMS.txt') -Algorithm SHA256).Hash.ToLower()
Assert-Equal (@(Test-BundleSums $b.Dir $trusted | Where-Object { $_ -like 'malformed or unsafe*' })).Count 1 'a listed path with .. is refused even when the sums file is trusted'
$b = New-TestBundle; Set-Content -LiteralPath (Join-Path $b.Dir 'SHA256SUMS.txt') -Value ((Get-Content -LiteralPath (Join-Path $b.Dir 'SHA256SUMS.txt') | Select-Object -Skip 1) -join "`n") -Encoding ASCII
$trusted = (Get-FileHash -LiteralPath (Join-Path $b.Dir 'SHA256SUMS.txt') -Algorithm SHA256).Hash.ToLower()
Assert-Equal (@(Test-BundleSums $b.Dir $trusted | Where-Object { $_ -like 'required file not listed*' })).Count 1 'a required file that is not listed is refused'

# ---- runner support: archive member safety ------------------------------------------------------------------------------------------------------
$dest = 'C:\Users\x\saplens-phase1\run1\runtime'
Assert-Equal @(Test-ArchiveMembers @('python/', 'python/python.exe', 'manifest.json') @('d', '-', '-') $dest).Count 0 'ordinary members are accepted'
Assert-Equal @(Test-ArchiveMembers @('../evil.dll') @('-') $dest).Count 1 'path traversal is refused'
Assert-Equal @(Test-ArchiveMembers @('a/../../evil.dll') @('-') $dest).Count 1 'embedded traversal is refused'
Assert-Equal @(Test-ArchiveMembers @('/etc/passwd') @('-') $dest).Count 1 'absolute path is refused'
Assert-Equal @(Test-ArchiveMembers @('C:/Windows/evil.dll') @('-') $dest).Count 1 'drive path is refused'
Assert-Equal @(Test-ArchiveMembers @('a\b.dll') @('-') $dest).Count 1 'backslash is refused'
Assert-Equal @(Test-ArchiveMembers @('a.txt:stream') @('-') $dest).Count 1 'alternate data stream is refused'
Assert-Equal @(Test-ArchiveMembers @('python/link') @('l') $dest).Count 1 'symbolic link member is refused'
Assert-Equal @(Test-ArchiveMembers @('python/hard') @('h') $dest).Count 1 'hard link member is refused'
Assert-Equal @(Test-ArchiveMembers @('python/NUL.txt') @('-') $dest).Count 1 'reserved device name is refused'
Assert-Equal @(Test-ArchiveMembers @('python/file. ') @('-') $dest).Count 1 'trailing space or dot is refused'
Assert-Equal @(Test-ArchiveMembers @('python/' + ('a' * 260)) @('-') $dest).Count 1 'a path that would exceed MAX_PATH is refused'
Assert-Equal @(Test-ArchiveMembers @() @() $dest).Count 1 'an empty archive is refused'
Assert-Equal @(Test-ArchiveMembers @('a', 'b') @('-') $dest).Count 1 'misaligned listing is refused'

# ---- runner support: only processes created by this run are ever selected -------------------------------------------------------------------------------
$t = [datetime]'2026-01-01T10:00:00'
$rt = 'C:\run1\runtime'; $hostExe = 'C:\run1\bundle\saplens-host.exe'
function P($id, $parent, $secs, $path) { [pscustomobject]@{ ProcessId = $id; ParentProcessId = $parent; CreationDate = $t.AddSeconds($secs); ExecutablePath = $path } }
$table = @(
    (P 100 1 0 $hostExe),                                  # our host, still alive
    (P 101 100 1 "$rt\python\python.exe"),                 # our backend, child of the host
    (P 102 101 2 "$rt\python\python.exe"),                 # our grandchild
    (P 103 101 2 'C:\Windows\System32\conhost.exe'),       # helper below our process but not ours to stop
    (P 200 1 0 $hostExe),                                  # ANOTHER run's host: same path, not recorded
    (P 201 200 1 "$rt\python\python.exe"),                 # ANOTHER run's backend below the other host
    (P 300 100 -5 "$rt\python\python.exe"),                # claims our host as parent but started before it (PID reuse)
    (P 400 999 3 "$rt\python\python.exe"))                 # same runtime path, unrelated parent
$owned = @(@{ Pid = 100; Start = $t })
$ids = @(Get-OwnedLeftovers $table $owned $rt $hostExe | ForEach-Object { [int]$_.ProcessId } | Sort-Object)
Assert-Equal ($ids -join ',') '100,101,102' 'only the owned host and its descendants from the runtime tree are selected'
$gone = @(Get-OwnedLeftovers $table @(@{ Pid = 100; Start = $t.AddSeconds(50) }) $rt $hostExe)
Assert-Equal $gone.Count 0 'a recycled PID (different start time) is not treated as ours'
$exited = @(Get-OwnedLeftovers @((P 101 100 1 "$rt\python\python.exe")) @(@{ Pid = 100; Start = $t }) $rt $hostExe | ForEach-Object { [int]$_.ProcessId })
Assert-Equal ($exited -join ',') '101' 'a child of an exited owned process is still found (Windows does not reparent)'

# ---- runner support: harness outcome classification -----------------------------------------------------------------------------------------------
function New-ResultFile([string]$Overall, $Statuses) {
    $d = New-TestDir
    $stages = foreach ($s in $Statuses) { [ordered]@{ id = 'x'; status = $s; detail = ''; evidence = $null } }
    Write-JsonFile (Join-Path $d 'r.json') ([ordered]@{ schema = 1; phase = 'x'; overall = $Overall; stages = @($stages) })
    return (Join-Path $d 'r.json')
}
Assert-Equal (Resolve-HarnessOutcome 0 (New-ResultFile 'PASS' @('PASS', 'PASS'))).Status 'PASS' 'consistent PASS'
Assert-Equal (Resolve-HarnessOutcome 1 (New-ResultFile 'FAIL' @('PASS', 'FAIL'))).Status 'FAIL' 'consistent FAIL'
Assert-Equal (Resolve-HarnessOutcome 2 (New-ResultFile 'BLOCKED' @('PASS', 'BLOCKED'))).Status 'BLOCKED' 'consistent BLOCKED'
Assert-Equal (Resolve-HarnessOutcome 3 (New-ResultFile 'INCOMPLETE' @('PASS', 'NOT EXECUTED'))).Status 'NOT EXECUTED' 'INCOMPLETE is NOT EXECUTED'
Assert-Equal (Resolve-HarnessOutcome 4 (New-ResultFile 'HARNESS ERROR' @('PASS', 'HARNESS ERROR'))).Status 'HARNESS ERROR' 'harness reported its own error'
Assert-Equal (Resolve-HarnessOutcome 1 (Join-Path (New-TestDir) 'missing.json')).Status 'HARNESS ERROR' 'exit 1 without a result file is a HARNESS ERROR, not a FAIL'
Assert-Equal (Resolve-HarnessOutcome 0 (Join-Path (New-TestDir) 'missing.json')).Status 'HARNESS ERROR' 'exit 0 without a result file is a HARNESS ERROR, not a PASS'
Assert-Equal (Resolve-HarnessOutcome $null (New-ResultFile 'PASS' @('PASS'))).Status 'HARNESS ERROR' 'no exit code is a HARNESS ERROR'
Assert-Equal (Resolve-HarnessOutcome 0 (New-ResultFile 'FAIL' @('PASS', 'FAIL'))).Status 'HARNESS ERROR' 'exit code contradicting the result is a HARNESS ERROR'
Assert-Equal (Resolve-HarnessOutcome 0 (New-ResultFile 'PASS' @('PASS', 'FAIL'))).Status 'HARNESS ERROR' 'overall contradicting the stages is a HARNESS ERROR'
$garbage = Join-Path (New-TestDir) 'g.json'; Set-Content -LiteralPath $garbage -Value '{ not json'
Assert-Equal (Resolve-HarnessOutcome 0 $garbage).Status 'HARNESS ERROR' 'unparsable result is a HARNESS ERROR'
Assert-Equal (Resolve-HarnessOutcome 0 (New-ResultFile 'PASS' @('MAYBE'))).Status 'HARNESS ERROR' 'unknown stage status is a HARNESS ERROR'

Assert-Equal (Get-RunStatus 'integrity' $null $null 0) 'NOT EXECUTED' 'a stop reason means nothing was verified'
Assert-Equal (Get-RunStatus $null 'FAIL' $null 0) 'HARNESS ERROR' 'a failing logic self-test is a harness problem'
Assert-Equal (Get-RunStatus $null 'PASS' 'PASS' 0) 'PASS' 'pass'
Assert-Equal (Get-RunStatus $null 'PASS' 'PASS' 2) 'HARNESS ERROR' 'PASS with enforced blocks is conflicting evidence'
Assert-Equal (Get-RunStatus $null 'PASS' 'BLOCKED' 2) 'BLOCKED' 'blocked stays blocked'
Assert-Equal (Get-RunExitCode 'PASS') 0 'exit code PASS'
Assert-Equal (Get-RunExitCode 'FAIL') 1 'exit code FAIL'
Assert-Equal (Get-RunExitCode 'BLOCKED') 2 'exit code BLOCKED'
Assert-Equal (Get-RunExitCode 'NOT EXECUTED') 3 'exit code NOT EXECUTED'
Assert-Equal (Get-RunExitCode 'HARNESS ERROR') 4 'exit code HARNESS ERROR'
Assert-Equal (Get-OverallVerdict @(@{ status = 'PASS' }, @{ status = 'HARNESS ERROR' }, @{ status = 'BLOCKED' })) 'HARNESS ERROR' 'HARNESS ERROR outranks BLOCKED'
Assert-Equal (ConvertTo-SafeMessage 'x token=abcdef secret: hunter2 y') 'x token=<redacted> secret: <redacted> y' 'credential-looking values are redacted in messages'


# ---- runner support: native child processes keep their raw exit code and timeouts (inline -Command only: no script file, so no authorization involved) ----
$shell = (Get-Process -Id $PID).Path
$td = New-TestDir
$r = Invoke-Native $shell @('-NoProfile', '-NonInteractive', '-Command', '"tempvar=[$($env:P1_PROBE)]"; exit 7') 60 @{ P1_PROBE = 'redirected' } (Join-Path $td 'log.txt') $td $null $null
Assert-Equal $r.ExitCode 7 'the raw native exit code is returned unchanged'
Assert-Equal ($r.Output -match 'tempvar=\[redirected\]') $true 'environment overrides reach the child only'
Assert-Equal ([string]$env:P1_PROBE) '' 'the parent environment is not changed'
Assert-Equal (Test-Path -LiteralPath (Join-Path $td 'log.txt')) $true 'the child output is preserved in a log file'
Assert-Equal (ConvertTo-ArgumentString @('a b')) '"a b"' 'quoting: spaces'
Assert-Equal (ConvertTo-ArgumentString @('c"d')) '"c\"d"' 'quoting: embedded quote'
Assert-Equal (ConvertTo-ArgumentString @('e\')) 'e\' 'quoting: trailing backslash without whitespace is left alone'
Assert-Equal (ConvertTo-ArgumentString @('a b\')) '"a b\\"' 'quoting: trailing backslash inside quotes is doubled'
Assert-Equal (ConvertTo-ArgumentString @('')) '""' 'quoting: empty argument'
$started = Get-Date
$t = Invoke-Native $shell @('-NoProfile', '-NonInteractive', '-Command', 'Start-Sleep -Seconds 60') 2 @{} $null $td $null $null
Assert-Equal $t.TimedOut $true 'a hung child is reported as timed out'
Assert-Equal (((Get-Date) - $started).TotalSeconds -lt 30) $true 'a hung child is stopped promptly'
Assert-Equal ($null -ne (Get-Process -Id $t.Pid -ErrorAction SilentlyContinue)) $false 'the timed-out child is gone'
$missing = Invoke-Native $shell.Replace('pwsh', 'no-such-binary').Replace('powershell', 'no-such-binary') @() 5 @{} $null $td $null $null
Assert-Equal $missing.Started $false 'a missing executable is reported, not thrown'

# ---- script authorization: in-process execution, typed security classification, Mark-of-the-Web advice -----------------------------------------------------
function Invoke-Quiet($Script, $Arguments, $Environment, $LogPath, $ErrorLogPath) { return (Invoke-PhaseScript $Script $Arguments $Environment $LogPath $ErrorLogPath $false) }   # keeps the nested test runs quiet
function New-TestScript([string]$Body) { $f = Join-Path (New-TestDir) 'step.ps1'; Set-Content -LiteralPath $f -Value $Body -Encoding ASCII; return $f }
$ok = Invoke-Quiet (New-TestScript 'param([string]$Name = "x", [switch]$Flag) "hello $Name flag=$Flag"; Write-Host "to-host"; exit 7') @{ Name = 'world'; Flag = $true } @{ P1_ENV = 'set' } (Join-Path $td 'phase.log') (Join-Path $td 'phase.err')
Assert-Equal $ok.ExitCode 7 'in-process: the script''s own exit code is returned raw'
Assert-Equal ($ok.Output -match 'hello world flag=True') $true 'in-process: named parameters and switches are passed'
Assert-Equal ($ok.Output -match 'to-host') $true 'in-process: Write-Host output is captured'
Assert-Equal ($null -eq $env:P1_ENV) $true 'in-process: environment overrides are restored afterwards (a variable that did not exist is removed again)'
Assert-Equal (Test-Path -LiteralPath (Join-Path $td 'phase.log')) $true 'in-process: output is preserved in a log'
$envSeen = Invoke-Quiet (New-TestScript '"seen=[$($env:P1_ENV)]"; exit 0') @{} @{ P1_ENV = 'inside' } $null $null
Assert-Equal ($envSeen.Output -match 'seen=\[inside\]') $true 'in-process: the child sees the override'
$tryFinally = Invoke-Quiet (New-TestScript 'try { exit 3 } finally { Write-Host "cleanup-ran" }') @{} @{} $null $null
Assert-Equal $tryFinally.ExitCode 3 'in-process: exit inside try/finally returns control with the exit code'
Assert-Equal ($tryFinally.Output -match 'cleanup-ran') $true 'in-process: finally blocks of the script still run'
$noExit = Invoke-Quiet (New-TestScript '"no exit here"') @{} @{} $null $null
Assert-Equal ($null -eq $noExit.ExitCode) $true 'in-process: a script that ends without exit has no exit code (not a stale one)'
Assert-Equal (Resolve-ScriptStep $noExit 'step').Status 'HARNESS ERROR' 'a missing exit code is a HARNESS ERROR'
$scoped = Invoke-Quiet (New-TestScript '(New-StageResult "x" "PASS" "d" $null).status; (Get-OverallVerdict @(@{ status = "PASS" })); (Get-RequiredBundleFiles).Count; exit 0') @{} @{} $null $null
Assert-Equal ((($scoped.Output -split "`r?`n") | Where-Object { $_ }) -join ',') 'PASS,PASS,7' 'in-process: shared helpers and constants work in a script that does not load them itself'

$thrown = Invoke-Quiet (New-TestScript 'throw "original failure text"') @{} @{} $null (Join-Path $td 'thrown.err')
Assert-Equal $thrown.Security $false 'a generic terminating error is not a security restriction'
Assert-Equal ($thrown.Error -match 'original failure text') $true 'the original error message is preserved'
Assert-Equal (Resolve-ScriptStep $thrown 'step').Status 'HARNESS ERROR' 'a generic terminating error is a HARNESS ERROR'
Assert-Equal (Test-Path -LiteralPath (Join-Path $td 'thrown.err')) $true 'the original error is written to an error log'
$sec = Invoke-Quiet (New-TestScript 'throw (New-Object System.Management.Automation.PSSecurityException "AuthorizationManager check failed.")') @{} @{} $null $null
Assert-Equal $sec.Security $true 'a PSSecurityException is recognized as a security restriction (typed, not by text)'
Assert-Equal $sec.ErrorType 'System.Management.Automation.PSSecurityException' 'the original error type is preserved'
$secStep = Resolve-ScriptStep $sec 'Test-Phase1Logic.ps1'
Assert-Equal $secStep.Status 'NOT EXECUTED' 'an authorization failure is NOT EXECUTED, not a failed assertion'
Assert-Equal ($secStep.Reason -match 'AuthorizationManager check failed') $true 'the original message appears in the explanation'
Assert-Equal ($secStep.Reason -match 'not a failed assertion') $true 'the explanation distinguishes a restriction from an assertion failure'
$lookalike = Invoke-Quiet (New-TestScript 'throw "AuthorizationManager check failed."') @{} @{} $null $null
Assert-Equal $lookalike.Security $false 'the same words in an ordinary error are NOT treated as a security restriction'
$missingScript = Invoke-Quiet (Join-Path $td 'does-not-exist.ps1') @{} @{} $null $null
Assert-Equal $missingScript.Started $false 'a missing script is reported, not thrown'
Assert-Equal $missingScript.Security $false 'a missing script is not a security restriction'
$assertFail = Invoke-Quiet (New-TestScript 'Write-Host "assertion text"; exit 1') @{} @{} $null $null
Assert-Equal (Resolve-ScriptStep $assertFail 'step').Kind 'exit' 'a failing assertion run ends with a normal exit code, kept raw'
Assert-Equal $assertFail.ExitCode 1 'the failing exit code is preserved'
Assert-Equal $assertFail.Security $false 'a failing assertion is not a security restriction'

Assert-Equal (Get-ScriptAuthorizationAdvice 'Unrestricted' 3 $true).Expectation 'prompt' 'Unrestricted + Mark-of-the-Web, interactive: prompts expected, answerable'
Assert-Equal (Get-ScriptAuthorizationAdvice 'Unrestricted' 3 $false).Expectation 'prompt-impossible' 'Unrestricted + Mark-of-the-Web, non-interactive: the prompt cannot be answered'
Assert-Equal (Get-ScriptAuthorizationAdvice 'Unrestricted' 0 $false).Expectation 'none' 'no Mark-of-the-Web: no prompt even when non-interactive'
Assert-Equal (Get-ScriptAuthorizationAdvice 'RemoteSigned' 2 $true).Expectation 'refused' 'RemoteSigned + Mark-of-the-Web: refused (needs a signature), not prompted'
Assert-Equal (Get-ScriptAuthorizationAdvice 'RemoteSigned' 0 $true).Expectation 'none' 'RemoteSigned without Mark-of-the-Web: local scripts run'
Assert-Equal (Get-ScriptAuthorizationAdvice 'AllSigned' 0 $true).Expectation 'refused' 'AllSigned refuses unsigned scripts'
Assert-Equal (Get-ScriptAuthorizationAdvice 'Restricted' 0 $true).Expectation 'refused' 'Restricted refuses scripts'
Assert-Equal (Get-ScriptAuthorizationAdvice 'Bypass' 5 $false).Expectation 'none' 'an organization-set Bypass policy needs no prompt (nothing here sets it)'
Assert-Equal (@(Get-ScriptAuthorizationAdvice 'Unrestricted' 3 $true).Message -match 'Nothing is unblocked') $true 'the advice states that nothing is unblocked'
$zone = Get-ZoneIdentifierState (New-TestScript 'x')
Assert-Equal ($zone.Present -ne $true) $true 'a freshly created local script has no Mark-of-the-Web'

# ---- Windows PowerShell 5.1 compatibility (syntax and features that exist only in PowerShell 7) --------------------------------------------------------------
# The two hosts behave differently on the SAME source, and the lint must hold on both:
#   * PowerShell 7 parses PS7-only syntax (ternary, ??, &&, ?.) into AST nodes, so the AST names every construct.
#   * Windows PowerShell 5.1 cannot parse that syntax at all: Parser.ParseFile returns parse errors (and a partial AST), so an AST-only lint reports
#     "one problem" for a file with many. Those parse errors ARE the 5.1 detection of PS7-only syntax; they are reported one by one with their line.
#   * Cmdlet parameters and variables that merely do not exist in 5.1 (-Parallel, -AsByteStream, a third Join-Path argument, $IsWindows) parse fine
#     in BOTH hosts, so the AST finds them in both.
# A fixture that mixes both kinds therefore cannot give the same COUNT on both hosts. Each construct has its own fixture and must be detected (at least one
# problem) on whichever host runs the test; on PowerShell 7 the exact construct is asserted as well.
function Get-Ps51ParseProblems($Errors) {
    # Pure: one entry per parse error, with its line. Used for the Windows PowerShell 5.1 path, where PS7-only syntax is a parse error.
    $items = @()
    foreach ($e in @($Errors)) { if ($null -ne $e) { $items += "parse error at line $($e.Extent.StartLineNumber): $(ConvertTo-SafeMessage ([string]$e.Message) 120)" } }
    return $items
}
function Get-Ps51TokenProblems($Tokens) {
    # Pure over a token list (objects with Kind, Text, Extent.StartLineNumber), so the Windows PowerShell 5.1 tokenization can be tested without that host.
    # Strings and comments never match: their token text includes the quotes or the leading hash.
    $problems = @(); $previous = ''
    foreach ($token in @($Tokens)) {
        $kind = [string]$token.Kind; $text = [string]$token.Text; $line = $token.Extent.StartLineNumber
        if (@('QuestionMark', 'QuestionQuestion', 'QuestionQuestionEquals', 'QuestionDot', 'QuestionLBracket', 'AndAnd', 'OrOr') -contains $kind) { $problems += "PowerShell 7 operator '$text' at line $line" }
        elseif (@('&&', '||', '??', '??=', '?.', '?[') -contains $text) { $problems += "PowerShell 7 operator '$text' at line $line" }
        elseif ($text -eq '?' -and @('Variable', 'Number', 'StringLiteral', 'StringExpandable', 'RParen', 'RBracket') -contains $previous) { $problems += "PowerShell 7 ternary operator '?' at line $line" }
        if ($kind -ne 'Comment') { $previous = $kind }
    }
    return $problems
}
function Test-Ps51Syntax([string]$ScriptPath) {
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($ScriptPath, [ref]$tokens, [ref]$errors)
    $problems = @(Get-Ps51ParseProblems $errors)
    # Token scan: independent of whether the whole file parsed (PowerShell 7 names these token kinds; 5.1 produces generic tokens with the same text).
    $problems += @(Get-Ps51TokenProblems $tokens)
    if ($null -eq $ast) { return $problems }
    foreach ($node in $ast.FindAll({ param($n) $true }, $true)) {
        $type = $node.GetType().Name
        if ($type -match 'Ternary|PipelineChain|NullConditional|NullCoalesc') { $problems += "$type at line $($node.Extent.StartLineNumber)" }
        if ($node -is [System.Management.Automation.Language.BinaryExpressionAst] -and [string]$node.Operator -match 'QuestionQuestion') { $problems += "null-coalescing at line $($node.Extent.StartLineNumber)" }
        if ($node -is [System.Management.Automation.Language.CommandParameterAst] -and $node.ParameterName -in @('Parallel', 'AsHashtable', 'AsByteStream', 'SkipLast', 'AsUTC', 'AdditionalChildPath', 'NoEmphasis', 'ThrottleLimit')) { $problems += "-$($node.ParameterName) at line $($node.Extent.StartLineNumber)" }
        if ($node -is [System.Management.Automation.Language.VariableExpressionAst] -and $node.VariablePath.UserPath -in @('IsWindows', 'IsLinux', 'IsMacOS', 'IsCoreCLR', 'PSStyle', 'PSNativeCommandUseErrorActionPreference')) { $problems += "`$$($node.VariablePath.UserPath) at line $($node.Extent.StartLineNumber)" }
        # Windows PowerShell 5.1 reads a null-conditional access as the variable named with a trailing ? followed by .member: valid syntax with a different meaning.
        if ($node -is [System.Management.Automation.Language.VariableExpressionAst] -and $node.VariablePath.UserPath -match '\?$') { $problems += "variable name ending in '?' (null-conditional access in PowerShell 7) at line $($node.Extent.StartLineNumber)" }
        if ($node -is [System.Management.Automation.Language.CommandAst] -and $node.GetCommandName() -eq 'Join-Path') {
            $positional = @($node.CommandElements | Select-Object -Skip 1 | Where-Object { $_ -isnot [System.Management.Automation.Language.CommandParameterAst] }).Count
            $named = @($node.CommandElements | Where-Object { $_ -is [System.Management.Automation.Language.CommandParameterAst] }).Count
            if ($positional - $named -gt 2 -and $positional -gt 2) { $problems += "Join-Path with more than two positional arguments at line $($node.Extent.StartLineNumber)" }
        }
        if ($node -is [System.Management.Automation.Language.StringConstantExpressionAst] -and $node.Value -match '^(?i)utf8NoBOM$') { $problems += "UTF8NoBOM encoding at line $($node.Extent.StartLineNumber)" }
    }
    return @($problems | Select-Object -Unique)
}
foreach ($name in @('Run-Phase1.ps1', 'Test-WindowsFeasibility.ps1', 'Get-AppControlDiagnostics.ps1', 'Phase1Common.ps1', 'Test-Phase1Logic.ps1')) {
    Assert-Equal ((Test-Ps51Syntax (Join-Path $PSScriptRoot $name)) -join '; ') '' "PowerShell 5.1 compatibility: $name uses no PowerShell 7 only syntax or parameters (and parses without errors)"
}
$isSeven = ($PSVersionTable.PSVersion.Major -ge 6)
$fixtures = [ordered]@{
    'ternary operator'              = @{ Code = '$x = $true ? 1 : 2'; Seven = "operator '\?'|Ternary" }
    'null-coalescing operator'      = @{ Code = '$y = $null ?? 3'; Seven = "operator '\?\?'|null-coalescing|NullCoalesc" }
    'pipeline chain operator'       = @{ Code = 'Get-Item . && Get-Item .'; Seven = "operator '&&'|PipelineChain" }
    'ForEach-Object -Parallel'      = @{ Code = '1..3 | ForEach-Object -Parallel { $_ }'; Seven = '-Parallel' }
    'three-argument Join-Path'      = @{ Code = 'Join-Path a b c'; Seven = 'Join-Path with more than two' }
    'Get-Content -AsByteStream'     = @{ Code = 'Get-Content f -AsByteStream'; Seven = '-AsByteStream' }
    'IsWindows automatic variable'  = @{ Code = 'if ($IsWindows) { }'; Seven = 'IsWindows' }
}
foreach ($key in $fixtures.Keys) {
    $found = @(Test-Ps51Syntax (New-TestScript $fixtures[$key].Code))
    Assert-Equal ($found.Count -ge 1) $true "the lint detects: $key (host: PowerShell $($PSVersionTable.PSVersion.Major))"
    if ($isSeven) { Assert-Equal (@($found | Where-Object { $_ -match $fixtures[$key].Seven }).Count -ge 1) $true "on PowerShell 7 the lint names the construct: $key" }
}
$combined = @(Test-Ps51Syntax (New-TestScript (($fixtures.Values | ForEach-Object { $_.Code }) -join "`n")))
Assert-Equal ($combined.Count -ge 1) $true 'a file mixing every unsupported construct is reported (the count differs by host: parse errors on 5.1, named constructs on 7)'
$benignCode = '1..3 | ? { $_ -gt 1 } | Where-Object { $_ -ne "a ?? b && c || d" }; $t = "x ? y : z"; Join-Path (Join-Path a b) c; Join-Path -Path a -ChildPath b'
$benign = @(Test-Ps51Syntax (New-TestScript $benignCode))
Assert-Equal ($benign -join '; ') '' 'no false positives: the ? alias, operators inside strings and nested two-argument Join-Path are accepted'
$parseFail = @(Test-Ps51Syntax (New-TestScript 'if ($true) { '))
Assert-Equal ($parseFail.Count -ge 1 -and $parseFail[0] -like 'parse error at line*') $true 'a genuine parse error is reported with its line (the Windows PowerShell 5.1 path for PS7-only syntax)'
# The 5.1 path, deterministically: what the lint reports when the host returns parse errors for a file it cannot read.
$synthetic = @(
    [pscustomobject]@{ Message = 'Unexpected token in expression or statement.'; Extent = [pscustomobject]@{ StartLineNumber = 4 } },
    [pscustomobject]@{ Message = 'The token is not a valid statement separator in this version.'; Extent = [pscustomobject]@{ StartLineNumber = 9 } })
$simulated = @(Get-Ps51ParseProblems $synthetic)
Assert-Equal $simulated.Count 2 'Windows PowerShell 5.1 path: every parse error is its own problem (not collapsed into one)'
Assert-Equal ($simulated[1] -like 'parse error at line 9:*') $true 'Windows PowerShell 5.1 path: the line number of each parse error is kept'
Assert-Equal @(Get-Ps51ParseProblems $null).Count 0 'Windows PowerShell 5.1 path: no errors, no problems'
function New-TestToken($Kind, $Text, $Line = 1) { return [pscustomobject]@{ Kind = $Kind; Text = $Text; Extent = [pscustomobject]@{ StartLineNumber = $Line } } }
# Windows PowerShell 5.1 hands the lint generic tokens (no QuestionMark/AndAnd kinds). Same text, different kind:
$generic = @((New-TestToken 'Variable' '$x'), (New-TestToken 'Generic' '?' 1), (New-TestToken 'Number' '1'), (New-TestToken 'Generic' '??' 2), (New-TestToken 'Generic' '&&' 3), (New-TestToken 'Generic' '||' 4))
Assert-Equal @(Get-Ps51TokenProblems $generic).Count 4 'Windows PowerShell 5.1 tokenization: generic ?, ??, && and || tokens are all detected by their text'
$alias = @((New-TestToken 'Number' '1'), (New-TestToken 'Pipe' '|'), (New-TestToken 'Generic' '?'), (New-TestToken 'LCurly' '{'), (New-TestToken 'StringExpandable' '"a ?? b && c"'), (New-TestToken 'Comment' '# a ?? b'))
Assert-Equal @(Get-Ps51TokenProblems $alias).Count 0 'Windows PowerShell 5.1 tokenization: the ? alias after a pipe, strings and comments are not flagged'
$afterNewline = @((New-TestToken 'Variable' '$x'), (New-TestToken 'NewLine' ''), (New-TestToken 'Generic' '?'))
Assert-Equal @(Get-Ps51TokenProblems $afterNewline).Count 0 'Windows PowerShell 5.1 tokenization: a ? that starts a new statement is the Where-Object alias'

# ---- static lint of the Windows-only scripts: every command resolves and our own functions are called with a plausible number of positional arguments ------------
# (the Windows code paths cannot run on Linux; this catches typos and signature drift between the scripts and Phase1Common.ps1)
function Test-ScriptCommands([string]$ScriptPath) {
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($ScriptPath, [ref]$null, [ref]$errors)
    if ($errors.Count -gt 0) { return @("parse errors: $($errors.Count)") }
    $windowsOnly = @('Get-NetTCPConnection', 'Get-CimInstance', 'Get-WinEvent', 'Get-AuthenticodeSignature', 'Get-PSDrive')
    $local = @{}
    foreach ($fn in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
        $count = 0
        if ($fn.Parameters) { $count = $fn.Parameters.Count } elseif ($fn.Body.ParamBlock) { $count = $fn.Body.ParamBlock.Parameters.Count }
        $local[$fn.Name] = $count
    }
    $problems = @()
    foreach ($call in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] }, $true)) {
        $first = $call.CommandElements[0]
        if ($first -isnot [System.Management.Automation.Language.StringConstantExpressionAst]) { continue }
        $name = $first.Value
        if ($local.ContainsKey($name)) { $max = $local[$name] }
        else {
            $known = Get-Command $name -ErrorAction SilentlyContinue
            if (-not $known -and $windowsOnly -notcontains $name -and $name -notin @('exit', 'return', 'throw', 'break', 'continue')) { $problems += "unresolved command '$name' at line $($call.Extent.StartLineNumber)"; continue }
            if ($known -and $known.CommandType -eq 'Function' -and $known.ScriptBlock.Ast -is [System.Management.Automation.Language.FunctionDefinitionAst]) { $max = $known.Parameters.Count } else { continue }
        }
        $named = @($call.CommandElements | Where-Object { $_ -is [System.Management.Automation.Language.CommandParameterAst] }).Count
        if ($named -gt 0) { continue }
        $positional = $call.CommandElements.Count - 1
        if ($positional -gt $max) { $problems += "'$name' called with $positional positional arguments but declares $max (line $($call.Extent.StartLineNumber))" }
    }
    return $problems
}
foreach ($name in @('Run-Phase1.ps1', 'Test-WindowsFeasibility.ps1', 'Get-AppControlDiagnostics.ps1')) {
    $found = @(Test-ScriptCommands (Join-Path $PSScriptRoot $name))
    Assert-Equal ($found -join '; ') '' "static lint: $name calls only resolvable commands with a plausible argument count"
}


$bad = Join-Path (New-TestDir) 'bad.ps1'
Set-Content -LiteralPath $bad -Value 'function Local-One($a) { }; Local-One 1 2; Get-FileHashh x; Resolve-HarnessOutcome 1 2 3; Test-BundleSums a b c'
$lint = @(Test-ScriptCommands $bad)
Assert-Equal $lint.Count 4 'the lint reports an unresolved command and three calls with too many arguments'

if ($failures -gt 0) { Write-Host "$failures assertion(s) failed"; exit 1 }
Write-Host 'all assertions passed'
exit 0   # explicit: a script that ends without exit would leave a stale $LASTEXITCODE from the nested runs above
