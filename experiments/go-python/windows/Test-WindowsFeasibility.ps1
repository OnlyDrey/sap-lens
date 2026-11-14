<#
.SYNOPSIS
  Phase 1 Windows feasibility harness for the Go + bundled Python experiment. Read-mostly, isolated, bounded.
.DESCRIPTION
  Runs the Phase 0 host and bundled runtime from an extracted tree under a unique temporary identity, with synthetic data only, and records a
  PASS / FAIL / BLOCKED / NOT EXECUTED result per stage in phase1-windows-result.json. It never installs or replaces SAP Lens, never touches
  services, the registry or production directories, and never changes, disables or weakens App Control. On non-Windows hosts every stage is
  NOT EXECUTED and the exit code is 3.
.PARAMETER HostExe     Path of saplens-host.exe (cross-compiled Phase 0 artifact).
.PARAMETER RuntimeDir  Extracted Windows runtime tree (python\python.exe, app\, manifest.json).
.PARAMETER OutDir      Evidence directory (default: a unique folder below the temp directory).
.EXAMPLE
  powershell -NoProfile -File .\Test-WindowsFeasibility.ps1 -HostExe C:\poc\saplens-host.exe -RuntimeDir C:\poc\runtime -OutDir C:\poc\evidence
.NOTES
  Exit codes: 0 all stages PASS, 1 at least one FAIL, 2 at least one BLOCKED (and no FAIL), 3 not executed or incomplete.
#>
param(
    [Parameter(Mandatory = $true)][string]$HostExe,
    [Parameter(Mandatory = $true)][string]$RuntimeDir,
    [string]$OutDir,
    [int]$ImportTimeoutSeconds = 30,
    [int]$ReadyTimeoutSeconds = 40,
    [switch]$KeepTemp
)
. (Join-Path $PSScriptRoot 'Phase1Common.ps1')

$stages = New-Object System.Collections.ArrayList
function Add-Stage($Result) { [void]$stages.Add($Result); Write-Host ("{0,-13} {1} {2}" -f $Result.status, $Result.id, $Result.detail) }
$stageIds = @('W01 preflight', 'W02 runtime integrity (manifest)', 'W03 signature inventory', 'W04 Go host starts', 'W05 bundled CPython initialises',
              'W06 native extensions load', 'W07 backend, frontend, capability and boundary', 'W08 graceful shutdown', 'W09 forced host kill: Job Object cleanup',
              'W10 start-timeout cleanup', 'W11 foreign data directory refused', 'W12 no orphan processes', 'W13 Windows measurements', 'W14 Code Integrity correlation')
$started = Get-Date
$onWindows = ($env:OS -eq 'Windows_NT')

function Finish([int]$Code) {
    $missing = @($stageIds | Where-Object { $id = $_; -not (@($stages | Where-Object { $_.id -eq $id }).Count) })
    foreach ($id in $missing) { [void]$stages.Add((New-StageResult $id 'NOT EXECUTED' $reason $null)) }
    $verdict = Get-OverallVerdict $stages
    $result = [ordered]@{ schema = 1; phase = 'go-python-phase1'; recorded_utc = (Get-Date).ToUniversalTime().ToString('o'); platform = $(if ($onWindows) { 'windows' } else { 'not-windows' });
                          os = $(if ($onWindows) { [System.Environment]::OSVersion.Version.ToString() } else { 'n/a' }); powershell = $PSVersionTable.PSVersion.ToString(); overall = $verdict; stages = $stages }
    $target = $OutDir; if (-not $target) { $target = Join-Path ([System.IO.Path]::GetTempPath()) ('saplens-poc-evidence-' + [guid]::NewGuid().ToString('N').Substring(0, 8)) }
    New-Item -ItemType Directory -Force $target | Out-Null
    [System.IO.File]::WriteAllText((Join-Path $target 'phase1-windows-result.json'), ($result | ConvertTo-Json -Depth 8), (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "Overall: $verdict (evidence: $target)"
    if ($verdict -eq 'PASS') { exit 0 } elseif ($verdict -eq 'FAIL') { exit 1 } elseif ($verdict -eq 'BLOCKED') { exit 2 } else { exit 3 }
}

$reason = 'not executed'
if (-not $onWindows) { $reason = 'not a Windows host: nothing was executed and no result may be reported as Windows validation'; Finish 3 }

# ---- W01 preflight and isolation -------------------------------------------------------------------------------------------------------------
$identity = 'poc-' + [guid]::NewGuid().ToString('N').Substring(0, 12)
$temp = Join-Path ([System.IO.Path]::GetTempPath()) ('saplens-' + $identity)
$HostExe = (Resolve-Path -LiteralPath $HostExe).Path; $RuntimeDir = (Resolve-Path -LiteralPath $RuntimeDir).Path.TrimEnd('\')
$forbidden = @($env:ProgramData, $env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA, $env:APPDATA) | Where-Object { $_ } | ForEach-Object { Join-Path $_ 'SAP Lens' }
$unsafe = @($forbidden | Where-Object { $HostExe.StartsWith($_, 'OrdinalIgnoreCase') -or $RuntimeDir.StartsWith($_, 'OrdinalIgnoreCase') })
if ($unsafe.Count -gt 0) { $reason = 'refused: input path is inside an SAP Lens installation or data directory'; Add-Stage (New-StageResult 'W01 preflight' 'FAIL' $reason $null); Finish 1 }
New-Item -ItemType Directory -Force $temp | Out-Null
$language = $ExecutionContext.SessionState.LanguageMode.ToString()
$elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$policy = Get-ActivePolicyListing
Add-Stage (New-StageResult 'W01 preflight' 'PASS' "isolated identity $identity; language mode $language; elevated=$elevated" ([ordered]@{ identity = $identity; language_mode = $language; elevated = $elevated; app_control_policies = $policy }))
$python = Join-Path $RuntimeDir 'python\python.exe'
$hostStage = $null

try {
    # ---- W02 / W03 --------------------------------------------------------------------------------------------------------------------------
    $problems = @(Test-ManifestIntegrity $RuntimeDir)
    $status = 'PASS'; if ($problems.Count -gt 0) { $status = 'FAIL' }
    Add-Stage (New-StageResult 'W02 runtime integrity (manifest)' $status "$($problems.Count) problem(s)" ([ordered]@{ problems = @($problems | Select-Object -First 20) }))
    $hostRow = Get-ImageRecord $HostExe 'saplens-host.exe'; $hostRow.kind = 'host'
    $inventory = @(Get-SignatureInventory $RuntimeDir) + @($hostRow)
    $summary = @($inventory | Group-Object kind, signature | ForEach-Object { [ordered]@{ group = $_.Name; count = $_.Count } })
    if ($OutDir) { New-Item -ItemType Directory -Force $OutDir | Out-Null; [System.IO.File]::WriteAllText((Join-Path $OutDir 'signature-inventory.json'), ($inventory | ConvertTo-Json -Depth 4), (New-Object System.Text.UTF8Encoding($false))) }
    Add-Stage (New-StageResult 'W03 signature inventory' 'PASS' "$($inventory.Count) executable images inventoried (state recorded, not judged)" ([ordered]@{ by_kind_and_state = $summary; host_signature = $hostRow.signature }))

    # ---- helpers for process launching ---------------------------------------------------------------------------------------------------
    function Start-Probe([string]$Exe, [string[]]$Arguments, [int]$TimeoutSeconds, [string]$WorkingDirectory) {
        $info = New-Object System.Diagnostics.ProcessStartInfo
        $info.FileName = $Exe; $info.UseShellExecute = $false; $info.RedirectStandardOutput = $true; $info.RedirectStandardError = $true; $info.RedirectStandardInput = $true; $info.CreateNoWindow = $true
        $info.Arguments = ($Arguments | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }) -join ' '
        if ($WorkingDirectory) { $info.WorkingDirectory = $WorkingDirectory }
        $info.EnvironmentVariables['PYTHONDONTWRITEBYTECODE'] = '1'
        $result = @{ Started = $false; NativeError = $null; ExitCode = $null; Stdout = ''; Stderr = ''; TimedOut = $false; Process = $null }
        try { $p = [System.Diagnostics.Process]::Start($info) } catch {
            $e = $_.Exception; while ($e -and -not ($e -is [System.ComponentModel.Win32Exception])) { $e = $e.InnerException }
            if ($e) { $result.NativeError = [int]$e.NativeErrorCode } else { $result.NativeError = -1 }
            return $result
        }
        $result.Started = $true; $result.Process = $p
        $outTask = $p.StandardOutput.ReadToEndAsync(); $errTask = $p.StandardError.ReadToEndAsync()
        try { $p.StandardInput.Close() } catch { }
        if (-not $p.WaitForExit($TimeoutSeconds * 1000)) { $result.TimedOut = $true; try { $p.Kill() } catch { }; [void]$p.WaitForExit(5000) }
        $result.ExitCode = $p.ExitCode; $result.Stdout = $outTask.Result; $result.Stderr = $errTask.Result
        return $result
    }
    function Get-ExceptionName([string]$Text) { $m = [regex]::Matches($Text, '(?m)^([A-Za-z]+(?:Error|Exception)):'); if ($m.Count -gt 0) { return $m[$m.Count - 1].Groups[1].Value }; return '' }
    function Get-RecentIntegrity([datetime]$From) {
        Start-Sleep -Seconds 2
        $q = Get-CodeIntegrityRecords $From.AddSeconds(-2) (Get-Date).AddSeconds(5)
        return @{ Records = @(Select-RuntimeIntegrityRecords $q.Records $RuntimeDir $From.AddSeconds(-2) (Get-Date).AddSeconds(5)); Limitations = $q.Limitations }
    }

    # ---- W04 host starts -------------------------------------------------------------------------------------------------------------------
    $t = Get-Date
    $probe = Start-Probe $HostExe @() 20 $temp
    if (-not $probe.Started) {
        $class = Get-FailureClass 'host' $probe.NativeError '' @() @{}
        Start-Sleep -Seconds 2
        $hq = Get-CodeIntegrityRecords $t.AddSeconds(-2) (Get-Date).AddSeconds(5)
        $ci = @{ Records = @(Select-RuntimeIntegrityRecords $hq.Records (Split-Path $HostExe -Parent) $t.AddSeconds(-2) (Get-Date).AddSeconds(5) | Where-Object { $_.Relative -eq (Split-Path $HostExe -Leaf) }) }
        if (@($ci.Records | Where-Object { $_.Enforced }).Count -gt 0) { $class = @{ Class = 'executable_blocked_by_policy'; Evidence = 'enforced Code Integrity record for the host file' } }
        $st = 'FAIL'; if ($class.Class -eq 'executable_blocked_by_policy') { $st = 'BLOCKED' }
        $hostStage = New-StageResult 'W04 Go host starts' $st "process not created: $($class.Class)" ([ordered]@{ native_error = $probe.NativeError; classification = $class; integrity = $ci.Records })
    } elseif ($probe.ExitCode -eq 1) {
        $hostStage = New-StageResult 'W04 Go host starts' 'PASS' 'host executed and returned its documented usage exit code (1)' ([ordered]@{ exit_code = 1 })
    } else {
        $hostStage = New-StageResult 'W04 Go host starts' 'FAIL' "unexpected exit code $($probe.ExitCode)" ([ordered]@{ exit_code = $probe.ExitCode })
    }
    Add-Stage $hostStage
    if ($hostStage.status -ne 'PASS') { $reason = 'skipped: the Go host did not start'; Finish 2 }

    # ---- W05 interpreter -------------------------------------------------------------------------------------------------------------------
    $t = Get-Date
    $probe = Start-Probe $python @('-I', '-c', 'import sys; print(sys.version.split()[0]); print(sys.flags.isolated); print(sys.prefix)') 30 $temp
    if (-not $probe.Started) {
        $ci = Get-RecentIntegrity $t; $class = Get-FailureClass 'interpreter' $probe.NativeError '' $ci.Records @{}
        $st = 'FAIL'; if ($class.Class -eq 'interpreter_blocked') { $st = 'BLOCKED' }
        Add-Stage (New-StageResult 'W05 bundled CPython initialises' $st "process not created: $($class.Class)" ([ordered]@{ native_error = $probe.NativeError; classification = $class; integrity = $ci.Records }))
    } else {
        $lines = @($probe.Stdout -split "`r?`n" | Where-Object { $_ })
        $ok = ($probe.ExitCode -eq 0 -and $lines.Count -ge 3 -and $lines[0] -eq '3.12.11' -and $lines[1] -eq '1' -and $lines[2].StartsWith("$RuntimeDir\python", 'OrdinalIgnoreCase'))
        $st = 'FAIL'; if ($ok) { $st = 'PASS' }
        Add-Stage (New-StageResult 'W05 bundled CPython initialises' $st "exit $($probe.ExitCode); version/isolated/prefix checked" ([ordered]@{ version = $lines[0]; isolated = $lines[1]; exit_code = $probe.ExitCode; stderr_exception = (Get-ExceptionName $probe.Stderr) }))
    }
    if ($stages[$stages.Count - 1].status -ne 'PASS') { $reason = 'skipped: the interpreter did not start'; Finish 2 }

    # ---- W06 native extensions (one import per module so a block names its file) -------------------------------------------------------
    $relative = @(Get-ChildItem -LiteralPath (Join-Path $RuntimeDir 'python\Lib\site-packages') -Recurse -File -Filter *.pyd | ForEach-Object { $_.FullName.Substring($RuntimeDir.Length + 1).Replace('\', '/') })
    $modules = @(Get-PydModuleNames $relative)
    $rows = @(); $blocked = 0; $failed = 0
    foreach ($module in $modules) {
        $t = Get-Date
        $probe = Start-Probe $python @('-I', '-c', "import $module") $ImportTimeoutSeconds $temp
        $class = @{ Class = 'ok'; Evidence = 'import_succeeded' }; $ci = @{ Records = @() }
        if (-not $probe.Started) { $class = Get-FailureClass 'interpreter' $probe.NativeError '' @() @{} }
        elseif ($probe.ExitCode -ne 0 -or $probe.TimedOut) {
            $ci = Get-RecentIntegrity $t
            $class = Get-FailureClass 'extension' $null (Get-ExceptionName $probe.Stderr) $ci.Records @{ ExitCode = $probe.ExitCode }
        }
        if ($class.Class -eq 'native_extension_blocked') { $blocked++ } elseif ($class.Class -ne 'ok') { $failed++ }
        $rows += [ordered]@{ module = $module; class = $class.Class; evidence = $class.Evidence }
    }
    $st = 'PASS'; if ($blocked -gt 0) { $st = 'BLOCKED' } elseif ($failed -gt 0) { $st = 'FAIL' }
    Add-Stage (New-StageResult 'W06 native extensions load' $st "$($modules.Count) modules probed; $blocked blocked, $failed failed" ([ordered]@{ results = $rows }))
    if ($st -ne 'PASS') { $reason = 'skipped: native extensions did not load'; Finish 2 }

    # ---- host run helper -------------------------------------------------------------------------------------------------------------------
    function Start-HostRun([string]$DataDir, [string[]]$Extra) {
        $info = New-Object System.Diagnostics.ProcessStartInfo
        $info.FileName = $HostExe; $info.UseShellExecute = $false; $info.RedirectStandardOutput = $true; $info.RedirectStandardError = $true; $info.CreateNoWindow = $true
        $info.Arguments = ((@('--runtime', $RuntimeDir, '--data', $DataDir) + $Extra) | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' '
        $p = [System.Diagnostics.Process]::Start($info)
        return @{ Process = $p; Out = $p.StandardOutput.ReadLineAsync(); Err = $p.StandardError.ReadToEndAsync(); Begun = Get-Date }
    }
    function Wait-Ready($Run, [int]$Seconds) {
        if (-not $Run.Out.Wait($Seconds * 1000)) { return $null }
        $m = [regex]::Match([string]$Run.Out.Result, '^READY url=(\S+) pid=(\d+) ms=(\d+)')
        if (-not $m.Success) { return $null }
        return @{ Url = $m.Groups[1].Value.TrimEnd('/'); BackendPid = [int]$m.Groups[2].Value; Ms = [int]$m.Groups[3].Value }
    }
    function Test-PidGone([int]$ProcessId, [int]$Seconds) { $end = (Get-Date).AddSeconds($Seconds); while ((Get-Date) -lt $end) { if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) { return $true }; Start-Sleep -Milliseconds 100 }; return -not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) }
    $nav = @{ 'Sec-Fetch-Mode' = 'navigate'; 'Sec-Fetch-Dest' = 'document'; 'Sec-Fetch-Site' = 'none' }

    # ---- W07 / W08 functional run with graceful stop via --hold ----------------------------------------------------------------------------
    $data = Join-Path $temp 'data-main'
    $run = Start-HostRun $data @('--hold', '25s')
    $ready = Wait-Ready $run $ReadyTimeoutSeconds
    if (-not $ready) {
        try { $run.Process.Kill() } catch { }
        $ci = Get-RecentIntegrity $run.Begun
        $class = Get-FailureClass 'application' $null '' $ci.Records @{}
        $st = 'FAIL'; if ($class.Class -eq 'blocked_component_during_startup') { $st = 'BLOCKED' }
        Add-Stage (New-StageResult 'W07 backend, frontend, capability and boundary' $st "no READY line: $($class.Class)" ([ordered]@{ classification = $class; host_exit = $run.Process.ExitCode; integrity = $ci.Records }))
        $reason = 'skipped: the backend did not become ready'; Finish 1
    }
    $checks = [ordered]@{}
    $health = Invoke-LoopbackRequest "$($ready.Url)/health" @{} $null
    $checks.health_200 = ($health.Status -eq 200 -and $health.Body -match '"app"\s*:\s*"sap-lens"')
    $page = Invoke-LoopbackRequest "$($ready.Url)/" $nav $null
    $checks.frontend_served = ($page.Status -eq 200 -and $page.Body.Contains('<div id="root"'))
    $capture = [regex]::Match($page.Body, "sap-lens-session',""([A-Za-z0-9_-]+)""")
    $capability = ''; if ($capture.Success) { $capability = $capture.Groups[1].Value }
    $checks.capability_handed_to_page = ($capability.Length -ge 32)
    $checks.api_without_capability_403 = ((Invoke-LoopbackRequest "$($ready.Url)/api/settings" @{} $null).Status -eq 403)
    $checks.api_wrong_capability_403 = ((Invoke-LoopbackRequest "$($ready.Url)/api/settings" @{ 'X-SAP-Lens' = ('A' * 43) } $null).Status -eq 403)
    $checks.api_issued_capability_200 = ((Invoke-LoopbackRequest "$($ready.Url)/api/settings" @{ 'X-SAP-Lens' = $capability } $null).Status -eq 200)
    $checks.foreign_host_403 = ((Invoke-LoopbackRequest "$($ready.Url)/health" @{} 'evil.example').Status -eq 403)
    $checks.foreign_origin_403 = ((Invoke-LoopbackRequest "$($ready.Url)/api/settings" @{ Origin = 'http://evil.example' } $null).Status -eq 403)
    $table = Get-ProcessTable; $tree = Get-Descendants $table $run.Process.Id
    $listeners = @(Get-NetTCPConnection -State Listen -OwningProcess $tree -ErrorAction SilentlyContinue)
    $checks.listener_loopback_only = ($listeners.Count -ge 1 -and @($listeners | Where-Object { $_.LocalAddress -ne '127.0.0.1' }).Count -eq 0)
    $cmdlines = @($table | Where-Object { $tree -contains [int]$_.ProcessId } | ForEach-Object { [string]$_.CommandLine })
    $dataText = @(Get-ChildItem -LiteralPath $data -Recurse -File -Force -ErrorAction SilentlyContinue | ForEach-Object { try { [System.Text.Encoding]::GetEncoding(28591).GetString([System.IO.File]::ReadAllBytes($_.FullName)) } catch { '' } })
    $peak = 0; foreach ($id in $tree) { $q = Get-Process -Id $id -ErrorAction SilentlyContinue; if ($q) { $peak += $q.PeakWorkingSet64 } }
    $exited = $run.Process.WaitForExit(60000)
    $stderrText = ''; if ($exited) { $stderrText = $run.Err.Result }
    $found = @(Find-Secret $capability (@($cmdlines) + @($stderrText) + @($dataText)))
    $checks.no_secret_in_cmdline_stderr_or_data = ($found.Count -eq 0 -and $capability.Length -ge 32)
    $failedChecks = @($checks.Keys | Where-Object { -not $checks[$_] })
    $st = 'PASS'; if ($failedChecks.Count -gt 0) { $st = 'FAIL' }
    Add-Stage (New-StageResult 'W07 backend, frontend, capability and boundary' $st "$($failedChecks.Count) failed check(s)" ([ordered]@{ checks = $checks; failed = $failedChecks; not_checked = 'process environment blocks (not readable without debug rights)' }))
    $graceful = ($exited -and $run.Process.ExitCode -eq 0 -and (Test-PidGone $ready.BackendPid 10))
    $st = 'FAIL'; if ($graceful) { $st = 'PASS' }
    Add-Stage (New-StageResult 'W08 graceful shutdown' $st "host exit code $($run.Process.ExitCode); backend gone=$(Test-PidGone $ready.BackendPid 1)" $null)
    $readyMs = $ready.Ms; $peakMiB = [math]::Round($peak / 1MB, 1)

    # ---- W09 forced host kill (Job Object; stdin-EOF watchdog is a second, indistinguishable defence on Windows) ----------------------------
    $run = Start-HostRun (Join-Path $temp 'data-kill') @()
    $ready = Wait-Ready $run $ReadyTimeoutSeconds
    if (-not $ready) { try { $run.Process.Kill() } catch { }; Add-Stage (New-StageResult 'W09 forced host kill: Job Object cleanup' 'FAIL' 'backend not ready' $null) }
    else {
        $table = Get-ProcessTable; $tree = Get-Descendants $table $run.Process.Id
        $run.Process.Kill(); [void]$run.Process.WaitForExit(10000)
        $gone = @($tree | Where-Object { $_ -ne $run.Process.Id } | ForEach-Object { Test-PidGone $_ 10 })
        $st = 'FAIL'; if ($gone.Count -gt 0 -and @($gone | Where-Object { -not $_ }).Count -eq 0) { $st = 'PASS' }
        Add-Stage (New-StageResult 'W09 forced host kill: Job Object cleanup' $st "$($gone.Count) child process(es) checked after TerminateProcess of the host" ([ordered]@{ attribution = 'Job Object (KILL_ON_JOB_CLOSE) and the backend stdin-EOF watchdog both apply; they are not separable here' }))
    }

    # ---- W10 start timeout, W11 foreign data dir -------------------------------------------------------------------------------------------
    $run = Start-HostRun (Join-Path $temp 'data-timeout') @('--start-timeout', '50ms')
    $exited = $run.Process.WaitForExit(30000); $code = $null; if ($exited) { $code = $run.Process.ExitCode }
    Start-Sleep -Seconds 1
    $left = @(Get-ProcessTable | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($RuntimeDir, 'OrdinalIgnoreCase') })
    $st = 'FAIL'; if ($code -eq 3 -and $left.Count -eq 0) { $st = 'PASS' }
    Add-Stage (New-StageResult 'W10 start-timeout cleanup' $st "exit code $code (expected 3); leftover processes $($left.Count)" $null)
    $foreign = Join-Path $temp 'foreign'; New-Item -ItemType Directory -Force $foreign | Out-Null; Set-Content -LiteralPath (Join-Path $foreign 'x.txt') -Value 'synthetic'
    $probe = Start-Probe $HostExe @('--runtime', $RuntimeDir, '--data', $foreign) 30 $temp
    $st = 'FAIL'; if ($probe.Started -and $probe.ExitCode -eq 2 -and (Test-Path -LiteralPath (Join-Path $foreign 'x.txt'))) { $st = 'PASS' }
    Add-Stage (New-StageResult 'W11 foreign data directory refused' $st "exit code $($probe.ExitCode) (expected 2); foreign file untouched" $null)

    # ---- W12 orphans, W13 measurements, W14 correlation ------------------------------------------------------------------------------------
    Start-Sleep -Seconds 1
    $orphans = @(Get-ProcessTable | Where-Object { $_.ExecutablePath -and ($_.ExecutablePath.StartsWith($RuntimeDir, 'OrdinalIgnoreCase') -or $_.ExecutablePath -eq $HostExe) -and $_.CreationDate -ge $started })
    foreach ($o in $orphans) { try { Stop-Process -Id $o.ProcessId -Force } catch { } }
    $st = 'PASS'; if ($orphans.Count -gt 0) { $st = 'FAIL' }
    Add-Stage (New-StageResult 'W12 no orphan processes' $st "$($orphans.Count) process(es) from the isolated runtime outlived the test (stopped by the harness)" $null)
    $fileCount = @(Get-ChildItem -LiteralPath $RuntimeDir -Recurse -File -Force).Count
    $bytes = (Get-ChildItem -LiteralPath $RuntimeDir -Recurse -File -Force | Measure-Object Length -Sum).Sum
    Add-Stage (New-StageResult 'W13 Windows measurements' 'PASS' 'single run, one machine; not comparable with Linux numbers' ([ordered]@{ host_reported_ready_ms = $readyMs; peak_working_set_mib_process_tree = $peakMiB; runtime_files = $fileCount; runtime_bytes = $bytes; runs = 1 }))
    $q = Get-CodeIntegrityRecords $started.AddSeconds(-2) (Get-Date).AddSeconds(5)
    $mine = @(Select-RuntimeIntegrityRecords $q.Records $RuntimeDir $started.AddSeconds(-2) (Get-Date).AddSeconds(5))
    $enforcedHits = @($mine | Where-Object { $_.Enforced })
    if ($q.Limitations.Count -gt 0 -and $mine.Count -eq 0) { Add-Stage (New-StageResult 'W14 Code Integrity correlation' 'NOT EXECUTED' ($q.Limitations -join ' ') $null) }
    else {
        $st = 'PASS'; if ($enforcedHits.Count -gt 0) { $st = 'BLOCKED' }
        Add-Stage (New-StageResult 'W14 Code Integrity correlation' $st "$($enforcedHits.Count) enforced and $($mine.Count - $enforcedHits.Count) audit-only record(s) below the runtime root" ([ordered]@{ records = $mine; limitations = $q.Limitations }))
    }
    $reason = 'completed'
} finally {
    if (-not $KeepTemp -and $temp -and (Test-Path -LiteralPath $temp) -and $temp.Contains('saplens-poc-')) { Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue }
}
Finish 0
