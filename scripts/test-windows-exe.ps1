param([string]$ExecutablePath='')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$executable = (Resolve-Path $(if ($ExecutablePath) { $ExecutablePath } else { 'backend/dist/SAP-Lens.exe' })).Path
$tempRoot = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [System.IO.Path]::GetTempPath() }
$testRoot = Join-Path $tempRoot ('sap-lens-smoke/' + [guid]::NewGuid())
New-Item -ItemType Directory -Force $testRoot | Out-Null
$owned = @{}
$script:SmokeStart = Get-Date
$script:ScenarioStart = $script:SmokeStart
$script:State = @{ Scenario = ''; Directory = ''; Launcher = 0; Runtime = 0; Condition = 'not started'; Health = $null; HttpError = ''; RecordSeen = $false; OwnedSeen = $false }
# The single-instance guard of the packaged application (backend/instance.py). It is per Windows session and independent of SAP_LENS_CONFIG_DIR, so ANY
# running SAP Lens makes a new launch exit with code 0 without starting a runtime.
$script:InstanceMutexName = 'Local\SAPLensDesktop'

function Test-InstanceHeld {
    $mutex = $null
    if ([System.Threading.Mutex]::TryOpenExisting($script:InstanceMutexName, [ref]$mutex)) { $mutex.Dispose(); return $true }
    return $false
}

function Get-RunningSapLens {
    # Informational only: these processes are never terminated by the smoke test.
    return @(Get-Process -Name 'SAP-Lens' -ErrorAction SilentlyContinue | ForEach-Object { "PID $($_.Id) started $($_.StartTime.ToString('s'))" })
}

function Join-SafePath($directory, [string]$leaf) {
    # Diagnostics can run before any scenario directory exists (preflight) or with a partly initialised state: never pass an empty path to Join-Path.
    if ([string]::IsNullOrWhiteSpace([string]$directory)) { return $null }
    return (Join-Path ([string]$directory) $leaf)
}

function Get-SafeLogTail($directory, [int]$lines = 25) {
    $log = Join-SafePath $directory 'sap-lens.log'
    if (-not $log) { return '(no scenario directory yet, so there is no application log)' }
    if (-not (Test-Path $log)) { return '(sap-lens.log does not exist)' }
    try {
        $tail = @(Get-Content -LiteralPath $log -Tail $lines -ErrorAction Stop)
        return ($tail | ForEach-Object { $_ -replace '(?i)(token|secret|passw\w*|authorization|api[-_ ]?key|credential)(\W{0,3})\S+', '$1$2<redacted>' }) -join "`n"
    } catch { return "(sap-lens.log unreadable: $($_.Exception.GetType().Name))" }
}

function Format-DiagnosticsCore([string]$class, [string]$detail, $application) {
    $state = $script:State
    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.Add("SMOKE FAILURE [$class] $detail")
    $lines.Add("Scenario: $($state.Scenario)    Elapsed: $([int]((Get-Date) - $script:ScenarioStart).TotalSeconds) s in scenario, $([int]((Get-Date) - $script:SmokeStart).TotalSeconds) s in total")
    $lines.Add("Executable: $executable")
    $exit = 'running'
    if ($application) { try { if ($application.HasExited) { $exit = [string]$application.ExitCode } } catch { $exit = 'unavailable' } }
    $lines.Add("Launcher PID: $($state.Launcher)    Runtime PID (runtime.json): $($state.Runtime)    Launcher exit code: $exit")
    try {
        $snapshot = @(Get-CimInstance Win32_Process)
        $rows = foreach ($id in @($owned.Keys)) {
            $entry = $snapshot | Where-Object { [int]$_.ProcessId -eq [int]$id } | Select-Object -First 1
            if ($entry) { "  PID $id (parent $($entry.ParentProcessId)) $($entry.Name)" } else { "  PID $id (exited)" }
        }
        $lines.Add('Owned processes (parent/child):'); foreach ($row in $rows) { $lines.Add($row) }
    } catch { $lines.Add('Owned processes: unavailable') }
    $runtimeFile = Join-SafePath $state.Directory 'runtime.json'
    $present = 'n/a (no scenario directory)'
    if ($runtimeFile) { $present = [string](Test-Path -LiteralPath $runtimeFile) }
    $lines.Add("runtime.json present: $present    seen during scenario: $($state.RecordSeen)    owned by launched tree: $($state.OwnedSeen)")
    $health = $state.Health
    if ($health) {
        $lines.Add("Last health: status=$($health.status) (expected ok), cached_roles=$($health.cached_roles) (expected 2), version=$($health.version), instance_id=$($health.instance_id)")
    } else {
        $lines.Add("Last health: none received. Last HTTP error: $($state.HttpError)")
    }
    $lines.Add("Last readiness condition: $($state.Condition)")
    $lines.Add("Single-instance guard $($script:InstanceMutexName) currently held: $(Test-InstanceHeld). SAP-Lens processes: $((Get-RunningSapLens) -join '; ')")
    $lines.Add('Application log (last lines, secrets redacted):')
    $lines.Add((Get-SafeLogTail $state.Directory))
    return ($lines -join "`n")
}

function Format-Diagnostics([string]$class, [string]$detail, $application) {
    # The report must never replace the real failure with a secondary exception: any problem while gathering details degrades to the plain message.
    try { return (Format-DiagnosticsCore $class $detail $application) }
    catch { return "SMOKE FAILURE [$class] $detail`n(additional diagnostics unavailable: $($_.Exception.GetType().Name))" }
}

function New-SmokeException([string]$class, [string]$detail, $application, $inner = $null) {
    $message = Format-Diagnostics $class $detail $application
    if ($inner) { $exception = New-Object System.Exception($message, $inner) } else { $exception = New-Object System.Exception($message) }
    $exception.Data['SmokeClass'] = $class
    return $exception
}

function Assert-DesktopSessionDenied([string]$Origin) {
    $status = $null
    try {
        $status = [int](Invoke-WebRequest "$Origin/api/settings" -UseBasicParsing -TimeoutSec 5).StatusCode
    } catch {
        # Windows PowerShell 5.1 throws WebException; PowerShell 7 throws
        # HttpResponseException. Both expose Response.StatusCode. Transport
        # failures have no response and must still fail the smoke test.
        if ($null -eq $_.Exception.Response) { throw }
        $status = [int]$_.Exception.Response.StatusCode
    }
    if ($status -ne 403) { throw 'Desktop session capability was not enforced.' }
}

function Track-Owned([int]$rootId) {
    $snapshot = @(Get-CimInstance Win32_Process)
    $ids = [System.Collections.Generic.HashSet[int]]::new()
    $ids.Add($rootId) | Out-Null
    do {
        $added = $false
        foreach ($entry in $snapshot) {
            if ($ids.Contains([int]$entry.ParentProcessId) -and $ids.Add([int]$entry.ProcessId)) { $added = $true }
        }
    } while ($added)
    foreach ($processId in $ids) {
        if (-not $owned.ContainsKey($processId)) {
            $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
            if ($process) {
                # Force creation of the process handle now, preserving this exact identity.
                $null = $process.Handle
                $owned[$processId] = $process
            }
        }
    }
    return ,$ids
}

function Start-Application([string]$directory) {
    $originalPath = $env:PATH
    $originalConfig = $env:SAP_LENS_CONFIG_DIR
    try {
        # The packaged app must work without Python, Node or build tools on PATH.
        $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
        $env:SAP_LENS_CONFIG_DIR = $directory
        return Start-Process -FilePath $executable -PassThru
    } finally {
        $env:PATH = $originalPath
        $env:SAP_LENS_CONFIG_DIR = $originalConfig
    }
}

function Wait-Ready($application, [string]$directory) {
    $deadline = (Get-Date).AddSeconds(60)
    $state = $script:State
    do {
        if ($application.HasExited) {
            $why = 'The launcher exited before the runtime reported ready.'
            if (-not (Test-Path (Join-Path $directory 'runtime.json')) -and $application.ExitCode -eq 0 -and (Test-InstanceHeld)) {
                $why = 'The launcher exited with code 0 without starting a runtime because another SAP Lens instance in this Windows session holds the single-instance guard. Close it (the smoke test never terminates processes it did not start).'
            }
            throw (New-SmokeException 'process_exited_before_readiness' $why $application)
        }
        $record = $null
        $path = Join-Path $directory 'runtime.json'
        if (Test-Path $path) {
            try { $record = Get-Content -Raw $path | ConvertFrom-Json } catch { $record = $null }
        }
        if (-not $record) { $state.Condition = 'runtime.json missing or unreadable' }
        if ($record) {
            $state.RecordSeen = $true
            $state.Runtime = [int]$record.pid
            $ids = Track-Owned $application.Id
            if (-not $ids.Contains([int]$record.pid)) { throw (New-SmokeException 'runtime_not_owned' 'Runtime record is not owned by the launched process tree.' $application) }
            $state.OwnedSeen = $true
            # The origin is discovered only from this owned instance, never assumed from a busy port.
            $address = [uri]$record.origin
            if ($address.Host -ne '127.0.0.1' -or $address.Scheme -ne 'http') { throw (New-SmokeException 'runtime_escaped_loopback' "Runtime origin $($record.origin) is not http://127.0.0.1." $application) }
            $health = $null
            try { $health = Invoke-RestMethod "$($record.origin)/health" -TimeoutSec 2; $state.HttpError = '' } catch { $state.HttpError = $_.Exception.GetType().Name + ': ' + $_.Exception.Message }
            if (-not $health) {
                $state.Health = $null
                $state.Condition = "HTTP endpoint unavailable ($($state.HttpError))"
            } else {
                $state.Health = $health
                if ($health.instance_id -ne $record.instance_id) {
                    $state.Condition = "instance_id mismatch (health $($health.instance_id), runtime.json $($record.instance_id))"
                } elseif ($health.status -ne 'ok') {
                    $state.Condition = "health status is '$($health.status)', expected 'ok'"
                } else {
                    if ($health.cached_roles -ne 2) { throw (New-SmokeException 'cached_roles_incorrect' "Configured synthetic data was not loaded: cached_roles is $($health.cached_roles), expected 2." $application) }
                    $state.Condition = 'ready'
                    return $record
                }
            }
        }
        Start-Sleep -Milliseconds 250
    } until ((Get-Date) -gt $deadline)
    $class = 'readiness_timeout'
    if (-not $state.RecordSeen) { $class = 'runtime_record_missing' }
    elseif (-not $state.Health) { $class = 'http_unavailable' }
    elseif ($state.Health.instance_id -ne $record.instance_id -and $state.Condition -like 'instance_id mismatch*') { $class = 'instance_id_mismatch' }
    elseif ($state.Condition -like "health status*") { $class = 'health_status_incorrect' }
    throw (New-SmokeException $class "Not ready within 60 s: $($state.Condition)" $application)
}

try {
    $version = (Get-Item $executable).VersionInfo
    $buildIdentity = Get-Content -Raw backend/build/build-version.json | ConvertFrom-Json
    $expectedVersion = $buildIdentity.version
    $numericVersion = $buildIdentity.file_version -join '.'
    if ($version.ProductName -ne 'SAP Lens' -or $version.FileVersion -ne $numericVersion -or $version.ProductVersion -ne $expectedVersion) { throw 'Windows version metadata missing.' }
    $bytes = [System.IO.File]::ReadAllBytes($executable)
    $peOffset = [BitConverter]::ToInt32($bytes, 0x3c)
    if ([BitConverter]::ToUInt16($bytes, $peOffset + 24 + 68) -ne 2) { throw 'EXE is not a console-free Windows GUI application.' }
    $bytes = $null

    # Prerequisite: the packaged application allows one instance per Windows session. A running SAP Lens (for example the installed application or a
    # window left open by an earlier manual run) makes every launch below exit with code 0 and no runtime. Report it instead of a misleading timeout.
    if (Test-InstanceHeld) {
        throw (New-SmokeException 'prerequisite_existing_instance' 'Another SAP Lens instance already runs in this Windows session. Close it and run the smoke test again. Nothing was started or terminated.' $null)
    }
    foreach ($scenario in @('first-launch', 'relaunch', 'port-conflict')) {
        $script:ScenarioStart = Get-Date
        $script:State = @{ Scenario = $scenario; Directory = ''; Launcher = 0; Runtime = 0; Condition = 'not started'; Health = $null; HttpError = ''; RecordSeen = $false; OwnedSeen = $false }
        if (Test-InstanceHeld) { throw (New-SmokeException 'instance_not_released' 'The previous scenario left the single-instance guard held; a launch would exit immediately.' $null) }
        $directory = Join-Path $testRoot $scenario
        New-Item -ItemType Directory -Force $directory | Out-Null
        # Reuse the first launch's saved configuration to check persistence.
        if ($scenario -eq 'relaunch') { $directory = Join-Path $testRoot 'first-launch' }
        $script:State.Directory = $directory
        $application = $null
        $csvPath = Join-Path $directory 'role-catalogue.csv'
@'
FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT
FI,DEMO:A,Synthetic A,SHARED,Shared,DEMO,Demo
MM,DEMO:B,Synthetic B,SHARED,Shared,DEMO,Demo
'@ | Set-Content $csvPath -Encoding utf8
        if ($scenario -ne 'relaunch') {
            $settingsPath = Join-Path $directory 'settings.json'
            $settingsJson = @{ data_csv_path = $csvPath } | ConvertTo-Json
            [System.IO.File]::WriteAllText($settingsPath, $settingsJson, (New-Object System.Text.UTF8Encoding($false)))
        }
        $busy = $null
        if ($scenario -eq 'port-conflict') {
            $busy = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 18743)
            $busy.Start()
        }
        try {
            $application = Start-Application $directory
            $owned[$application.Id] = $application
            $script:State.Launcher = $application.Id
            $record = Wait-Ready $application $directory
            $health = Invoke-RestMethod "$($record.origin)/health"
            if ($health.version -ne $expectedVersion) { throw 'Runtime version differs from packaged build identity.' }
            if ($busy -and ([uri]$record.origin).Port -eq 18743) { throw 'Port conflict did not select a new controlled port.' }
            if ($busy -and $busy.Pending()) { throw 'The conflicting listener was contacted.' }
            $html = Invoke-WebRequest "$($record.origin)/" -UseBasicParsing
            if ($html.Content -notmatch 'id="root"') { throw 'Bundled production frontend is missing.' }
            $icon = Invoke-WebRequest "$($record.origin)/sap-lens.png" -UseBasicParsing
            if ($icon.StatusCode -ne 200) { throw 'Bundled branding is missing.' }
            Assert-DesktopSessionDenied $record.origin
            $cors = Invoke-WebRequest "$($record.origin)/api/settings" -UseBasicParsing -Method Options -Headers @{
                Origin = $record.origin; 'Access-Control-Request-Method' = 'GET'; 'Access-Control-Request-Headers' = 'X-SAP-Lens'
            }
            if ($cors.Headers['Access-Control-Allow-Origin'] -ne $record.origin) { throw 'CORS is not restricted to the actual origin.' }
            $windowDeadline = (Get-Date).AddSeconds(20)
            do {
                $window = Get-Process -Id $record.pid -ErrorAction Stop
                if ($window.MainWindowHandle -eq 0) { Start-Sleep -Milliseconds 250 }
            } until ($window.MainWindowHandle -ne 0 -or (Get-Date) -gt $windowDeadline)
            if ($window.MainWindowHandle -eq 0 -or $window.MainWindowTitle -ne 'SAP Lens') {
                $windows = @($owned.Values | ForEach-Object { try { $_.Refresh(); "PID $($_.Id) handle=$($_.MainWindowHandle) title='$($_.MainWindowTitle)'" } catch { "PID $($_.Id) unavailable" } })
                throw (New-SmokeException 'window_initialization_failed' "Branded desktop window did not open within 20 s (runtime PID $($record.pid); expected title 'SAP Lens'). Owned windows: $($windows -join '; ')" $application)
            }
            if ($scenario -eq 'first-launch') {
                $duplicate = Start-Application $directory
                $owned[$duplicate.Id] = $duplicate
                if (-not $duplicate.WaitForExit(15000)) { Track-Owned $duplicate.Id | Out-Null; throw 'Duplicate launch did not return to the existing app.' }
                if ($duplicate.ExitCode -ne 0) { throw 'Duplicate launch returned an error.' }
                $after = Get-Content -Raw (Join-Path $directory 'runtime.json') | ConvertFrom-Json
                if ($after.instance_id -ne $record.instance_id) { throw 'Duplicate launch replaced the owned instance.' }
            }
            Track-Owned $application.Id | Out-Null
            if (-not $window.CloseMainWindow()) { throw 'Cannot close the owned desktop window.' }
            if (-not $application.WaitForExit(15000)) { throw 'Closing the window did not stop the application.' }
            if ($application.ExitCode -ne 0) { throw 'Application reported an unsuccessful shutdown.' }
            if (Test-Path (Join-Path $directory 'runtime.json')) { throw 'Runtime discovery was not cleaned up.' }
            $probe = [System.Net.Sockets.TcpClient]::new()
            try {
                $connected = $false
                try { $probe.Connect('127.0.0.1', ([uri]$record.origin).Port); $connected = $true } catch [System.Net.Sockets.SocketException] { }
                if ($connected) { throw 'Backend remains after the application closed.' }
            } finally { $probe.Dispose() }
            Write-Host "PASS $scenario : owned API, bundled frontend, branding, CORS, GUI window, no dev tools, clean shutdown"
        } catch {
            # Keep the original exception (as the inner exception) and add the scenario diagnostics once.
            if ($_.Exception.Data['SmokeClass']) { throw }
            throw (New-SmokeException 'assertion_failed' $_.Exception.Message $application $_.Exception)
        } finally {
            if ($busy) { $busy.Stop() }
        }
    }
} finally {
    # Never terminate processes by name: only handles captured from our own launches.
    foreach ($process in $owned.Values) {
        try { if (-not $process.HasExited) { $process.Kill(); $process.WaitForExit(5000) | Out-Null } } catch { }
    }
}
