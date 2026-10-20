$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$executable = (Resolve-Path backend/dist/SAP-Lens.exe).Path
$testRoot = Join-Path $env:RUNNER_TEMP ('sap-lens-smoke/' + [guid]::NewGuid())
New-Item -ItemType Directory -Force $testRoot | Out-Null
$owned = @{}

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
    do {
        if ($application.HasExited) { throw 'Packaged application exited before readiness.' }
        $record = $null
        $path = Join-Path $directory 'runtime.json'
        if (Test-Path $path) {
            try { $record = Get-Content -Raw $path | ConvertFrom-Json } catch { $record = $null }
        }
        if ($record) {
            $ids = Track-Owned $application.Id
            if (-not $ids.Contains([int]$record.pid)) { throw 'Runtime record is not owned by the launched process tree.' }
            # The origin is discovered only from this owned instance, never assumed from a busy port.
            $address = [uri]$record.origin
            if ($address.Host -ne '127.0.0.1' -or $address.Scheme -ne 'http') { throw 'Runtime escaped loopback.' }
            try { $health = Invoke-RestMethod "$($record.origin)/health" -TimeoutSec 2 } catch { $health = $null }
            if ($health -and $health.instance_id -eq $record.instance_id -and $health.status -eq 'ok') {
                if ($health.cached_roles -ne 2) { throw 'Configured synthetic data was not loaded.' }
                return $record
            }
        }
        Start-Sleep -Milliseconds 250
    } until ((Get-Date) -gt $deadline)
    throw 'Packaged application failed readiness.'
}

try {
    $version = (Get-Item $executable).VersionInfo
    $expectedVersion = [regex]::Match((Get-Content -Raw backend/version.py), "VERSION = '([^']+)'").Groups[1].Value
    if ($version.ProductName -ne 'SAP Lens' -or $version.FileVersion -ne $expectedVersion) { throw 'Windows version metadata missing.' }
    $bytes = [System.IO.File]::ReadAllBytes($executable)
    $peOffset = [BitConverter]::ToInt32($bytes, 0x3c)
    if ([BitConverter]::ToUInt16($bytes, $peOffset + 24 + 68) -ne 2) { throw 'EXE is not a console-free Windows GUI application.' }
    $bytes = $null

    foreach ($scenario in @('first-launch', 'relaunch', 'port-conflict')) {
        $directory = Join-Path $testRoot $scenario
        New-Item -ItemType Directory -Force $directory | Out-Null
        # Reuse the first launch's saved configuration to check persistence.
        if ($scenario -eq 'relaunch') { $directory = Join-Path $testRoot 'first-launch' }
        $csvPath = Join-Path $directory 'synthetic.csv'
@'
FUNCTION_KEY,AGR_NAME,TEXT,CHILD_AGR,CHILD_AGR_TEXT,TCODE,TTEXT
FI,DEMO:A,Synthetic A,SHARED,Shared,DEMO,Demo
MM,DEMO:B,Synthetic B,SHARED,Shared,DEMO,Demo
'@ | Set-Content $csvPath -Encoding utf8
        if ($scenario -ne 'relaunch') {
            @{ data_csv_path = $csvPath } | ConvertTo-Json | Set-Content (Join-Path $directory 'settings.json') -Encoding utf8NoBOM
        }
        $busy = $null
        if ($scenario -eq 'port-conflict') {
            $busy = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 18743)
            $busy.Start()
        }
        try {
            $application = Start-Application $directory
            $owned[$application.Id] = $application
            $record = Wait-Ready $application $directory
            if ($busy -and ([uri]$record.origin).Port -eq 18743) { throw 'Port conflict did not select a new controlled port.' }
            if ($busy -and $busy.Pending()) { throw 'The conflicting listener was contacted.' }
            $html = Invoke-WebRequest "$($record.origin)/"
            if ($html.Content -notmatch 'id="root"') { throw 'Bundled production frontend is missing.' }
            $icon = Invoke-WebRequest "$($record.origin)/sap-lens.png"
            if ($icon.StatusCode -ne 200) { throw 'Bundled branding is missing.' }
            $blocked = Invoke-WebRequest "$($record.origin)/api/settings" -SkipHttpErrorCheck
            if ($blocked.StatusCode -ne 403) { throw 'Desktop session capability was not enforced.' }
            $cors = Invoke-WebRequest "$($record.origin)/api/settings" -Method Options -Headers @{
                Origin = $record.origin; 'Access-Control-Request-Method' = 'GET'; 'Access-Control-Request-Headers' = 'X-SAP-Lens'
            }
            if ($cors.Headers['Access-Control-Allow-Origin'] -ne $record.origin) { throw 'CORS is not restricted to the actual origin.' }
            $windowDeadline = (Get-Date).AddSeconds(20)
            do {
                $window = Get-Process -Id $record.pid -ErrorAction Stop
                if ($window.MainWindowHandle -eq 0) { Start-Sleep -Milliseconds 250 }
            } until ($window.MainWindowHandle -ne 0 -or (Get-Date) -gt $windowDeadline)
            if ($window.MainWindowHandle -eq 0 -or $window.MainWindowTitle -ne 'SAP Lens') { throw 'Branded desktop window did not open.' }
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
