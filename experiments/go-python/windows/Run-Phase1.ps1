<#
.SYNOPSIS
  One-command, non-elevated entry point for the Go + Python Phase 1 Windows validation. Orchestrates the existing tools; never changes policy.
.DESCRIPTION
  1. Checks prerequisites (Windows x64, FullLanguage, not elevated, system tar.exe, disk space, no concurrent run).
  2. Verifies the bundle against a SEPARATELY SUPPLIED SHA-256 of SHA256SUMS.txt, copies it into a fresh run folder and verifies the copy.
  3. Validates every archive member before extraction (no traversal, absolute paths, links, streams, device names) and extracts into the run folder only.
  4. Runs the logic self-test, the isolated feasibility harness and (where permitted) the read-only App Control diagnostics IN THIS SESSION (call operator), so
     that PowerShell's own authorization prompt for scripts that carry a Mark-of-the-Web can be answered by the person at the keyboard. A noninteractive child
     process cannot answer it and fails with "AuthorizationManager check failed". Nothing is unblocked, no policy or language mode is changed. Expect up to
     three more 'Run once' prompts (self-test, harness, diagnostics) when the files are marked; avoid them by copying the bundle without the mark (share, USB).
     A script that PowerShell refuses to authorize is reported as NOT EXECUTED (security restriction), not as a failed assertion.
  5. Writes run-summary.json and run-summary.txt to the evidence folder even when a step fails, is blocked or throws, and prints a short summary.
  Nothing is deleted: the run folder, extracted runtime and evidence are kept. It never touches SAP Lens installations, services, databases, the registry,
  Windows security policy, Defender or App Control, and never changes the execution policy or the language mode.
.PARAMETER BundleDir            Bundle folder (saplens-host.exe, runtime.tar.gz, scripts\, SHA256SUMS.txt). This script must run from its scripts folder.
.PARAMETER TrustedSumsSha256    SHA-256 of SHA256SUMS.txt obtained through a separate channel (printed by make_bundle.py). Mandatory.
.PARAMETER WorkRoot             Parent of the run folder (default: %USERPROFILE%\saplens-phase1). A unique run folder is created below it.
.PARAMETER AllowElevated        Permit an elevated session. Requires -ElevationJustification. Not recommended: nothing here needs elevation.
.PARAMETER SkipDiagnostics      Do not run the App Control diagnostics step.
.PARAMETER HostStartTimeoutSeconds  How long the Go host waits for the backend to become ready (default 30). A cold first start on a machine that scans every new file can be slow; raise it to tell
                                    a slow start from a stuck one (the evidence records every startup phase with its time).
.PARAMETER VerifyOnly           Verify the bundle and the archive members, then stop. Executes nothing from the bundle and is NOT a Phase 1 result.
.EXAMPLE
  powershell -NoProfile -File .\bundle\scripts\Run-Phase1.ps1 -BundleDir .\bundle -TrustedSumsSha256 <64 hex characters>
.NOTES
  Exit codes: 0 PASS (or verification passed with -VerifyOnly), 1 FAIL, 2 BLOCKED, 3 NOT EXECUTED (a precondition or integrity check stopped the run),
  4 HARNESS ERROR (missing or inconsistent result, self-test failure, timeout, unexpected error). Raw exit codes of every tool are in run-summary.json.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$BundleDir,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$TrustedSumsSha256,
    [string]$WorkRoot,
    [switch]$AllowElevated,
    [string]$ElevationJustification,
    [switch]$SkipDiagnostics,
    [switch]$VerifyOnly,
    [ValidateRange(5, 600)][int]$HostStartTimeoutSeconds = 30
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Phase1Common.ps1')
$ErrorActionPreference = 'Stop'

# ---- run folder (cmdlets only until the language mode is known) -----------------------------------------------------------------------------------------
$runStart = Get-Date
$runId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + ('{0:00000}' -f (Get-Random -Maximum 99999))
$home0 = $env:USERPROFILE; if (-not $home0) { $home0 = $env:HOME }
if (-not $WorkRoot) { $WorkRoot = Join-Path $home0 'saplens-phase1' }
$work = Join-Path $WorkRoot $runId
$evidence = Join-Path $work 'evidence'
$tempDir = Join-Path $work 'temp'
$steps = @()   # plain arrays only: Constrained Language Mode rejects New-Object ArrayList
$raw = [ordered]@{}
$notes = @()
$stopReason = $null; $selfTest = $null; $harness = $null; $enforced = 0
$errors = @(); $authorization = $null
$onWindows = ($env:OS -eq 'Windows_NT')
$elevatedState = $null; $mutex = $null

function Add-Step([string]$Id, [string]$Status, [string]$Detail) {
    $script:steps += , ([ordered]@{ id = $Id; status = $Status; detail = $Detail })
    Write-Host ('{0,-13} {1}  {2}' -f $Status, $Id, $Detail)
}

function Add-StepError([string]$Id, $Run) {
    # The original error is kept as it was: type, id and message (also written in full to evidence).
    if ($Run.ErrorType) { $script:errors += , ([ordered]@{ step = $Id; type = $Run.ErrorType; id = $Run.ErrorId; message = $Run.Error; security_restriction = [bool]$Run.Security; raw_exit_code = $Run.ExitCode }) }
}

function Stop-Run([string]$Id, [string]$Reason) {
    # A precondition or integrity check could not be established: record it and stop. Nothing after this point runs.
    $script:stopReason = $Reason
    Add-Step $Id 'NOT EXECUTED' $Reason
}

function Complete-Run {
    $status = Get-RunStatus $script:stopReason $script:selfTest $script:harness $script:enforced
    if ($VerifyOnly -and -not $script:stopReason -and -not (@($steps | Where-Object { $_.status -notin @('PASS', 'NOT EXECUTED') }).Count)) { $verified = $true } else { $verified = $false }
    $code = Get-RunExitCode $status
    if ($VerifyOnly -and $verified) { $code = 0 }
    $defined = @('R01 prerequisites', 'R02 bundle integrity', 'R03 archive safety and extraction', 'R04 logic self-test', 'R05 isolated feasibility harness', 'R06 App Control diagnostics (read-only)')
    foreach ($id in $defined) {
        if (-not (@($steps | Where-Object { $_.id -eq $id }).Count)) {
            $why = 'not reached'; if ($script:stopReason) { $why = "stopped earlier: $($script:stopReason)" } elseif ($VerifyOnly) { $why = 'verify-only mode' }
            $script:steps += , ([ordered]@{ id = $id; status = 'NOT EXECUTED'; detail = $why })
        }
    }
    $ordered = @($steps | Sort-Object { $_.id })
    $summary = [ordered]@{
        schema = 1; tool = 'run-phase1'; run_id = $runId; recorded_utc = (Get-Date).ToUniversalTime().ToString('o'); platform = $(if ($onWindows) { 'windows' } else { 'not-windows' })
        mode = $(if ($VerifyOnly) { 'verify-only (not a Phase 1 result)' } else { 'phase1' }); overall = $status; exit_code = $code; verified = $verified; stopped_reason = $script:stopReason; authorization = $script:authorization; errors = @($script:errors)
        trusted_sums_sha256 = $TrustedSumsSha256.ToLowerInvariant(); elevated = $script:elevatedState; steps = $ordered; raw_exit_codes = $raw; notes = @($notes)
        locations = [ordered]@{ run_folder = (ConvertTo-SafeMessage $work 260); evidence = 'evidence'; extracted_runtime = 'runtime'; harness_result = 'evidence\harness\phase1-windows-result.json'
                                diagnostics = 'evidence\diagnostics\app-control-diagnostics.json'; signature_inventory = 'evidence\harness\signature-inventory.json' }
        meaning = [ordered]@{ PASS = 'every executed harness stage passed'; FAIL = 'the application ran and a criterion was not met'; BLOCKED = 'the operating system refused a file (documented code or enforced Code Integrity record); nothing about the application was verified'
                              'NOT EXECUTED' = 'a precondition or integrity check stopped the run, or a stage did not run'; 'HARNESS ERROR' = 'the result is missing, inconsistent or the tooling failed; this is neither a pass nor an application failure' }
    }
    if (Test-Path -LiteralPath $evidence) {
        Write-JsonFile (Join-Path $evidence 'run-summary.json') $summary
        $lines = @("SAP Lens Phase 1 run $runId", "Overall: $status (exit code $code)", "Mode: $($summary.mode)", '')
        foreach ($s in $ordered) { $lines += ('{0,-13} {1}  {2}' -f $s.status, $s.id, $s.detail) }
        $lines | Set-Content -LiteralPath (Join-Path $evidence 'run-summary.txt') -Encoding UTF8
    }
    Write-Host ''
    Write-Host "Overall: $status (exit code $code)"
    if ($VerifyOnly -and $verified) { Write-Host 'Verification passed. This is not a Phase 1 result: nothing from the bundle was executed.' }
    if (Test-Path -LiteralPath $evidence) { Write-Host "Evidence : $evidence" } else { Write-Host 'Evidence : (run folder could not be created)' }
    Write-Host 'Nothing was deleted: the run folder, the extracted runtime and the evidence are kept for review.'
    if ($script:mutex) { try { $script:mutex.ReleaseMutex() } catch { } }
    exit $code
}

try {
    # ---- R01 prerequisites -----------------------------------------------------------------------------------------------------------------------
    New-Item -ItemType Directory -Force -Path $evidence | Out-Null
    New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
    $languageMode = $ExecutionContext.SessionState.LanguageMode.ToString()
    $problems = @()
    $forbiddenRoots = @($env:ProgramData, $env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA, $env:APPDATA) | Where-Object { $_ } | ForEach-Object { Join-Path $_ 'SAP Lens' }
    if (@($forbiddenRoots | Where-Object { $work.StartsWith($_, 'OrdinalIgnoreCase') -or "$BundleDir".StartsWith($_, 'OrdinalIgnoreCase') }).Count -gt 0) { $problems += 'the work or bundle folder is inside an SAP Lens installation or data directory' }
    if (-not $VerifyOnly -and -not $onWindows) { $problems += 'not a Windows host: nothing was executed and no result may be reported as Windows validation' }
    if ($languageMode -ne 'FullLanguage') { $problems += "PowerShell language mode is $languageMode (needs FullLanguage). Do not work around this: ask IT" }
    elseif ($PSVersionTable.PSVersion -lt [version]'5.1') { $problems += 'PowerShell 5.1 or later is required' }
    $tarPath = $null
    if ($problems.Count -eq 0) {
        $isElevated = $false
        if ($onWindows) {
            $isElevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
            $architecture = $env:PROCESSOR_ARCHITEW6432; if (-not $architecture) { $architecture = $env:PROCESSOR_ARCHITECTURE }
            if ($architecture -ne 'AMD64') { $problems += "processor architecture ${architecture}: the bundle is x64 only" }
            $tarPath = Join-Path $env:SystemRoot 'System32\tar.exe'
            if (-not (Test-Path -LiteralPath $tarPath -PathType Leaf)) { $problems += 'System32\tar.exe is not available (needs Windows 10 1803 or later)' }
        } else {
            $found = Get-Command tar -ErrorAction SilentlyContinue; if ($found) { $tarPath = $found.Source } else { $problems += 'tar is not available' }
        }
        $script:elevatedState = [ordered]@{ elevated = $isElevated; allowed = [bool]$AllowElevated; justification = $(if ($isElevated -and $AllowElevated) { ConvertTo-SafeMessage $ElevationJustification 200 } else { $null }) }
        if ($isElevated -and -not ($AllowElevated -and $ElevationJustification -and $ElevationJustification.Trim().Length -ge 15)) { $problems += 'this session is elevated. Run from a normal, non-elevated PowerShell. (Elevation is only for the optional read-only diagnostics, run separately; -AllowElevated needs a written -ElevationJustification of at least 15 characters)' }
        $drive = [System.IO.Path]::GetPathRoot((Resolve-Path -LiteralPath $WorkRoot).Path)
        $free = (New-Object System.IO.DriveInfo($drive)).AvailableFreeSpace
        if ($free -lt 700MB) { $problems += "less than 700 MB free on $drive" }
        $script:mutex = New-Object System.Threading.Mutex($false, 'Local\SAPLensPhase1Runner')
        if (-not $script:mutex.WaitOne(0)) { $script:mutex = $null; $problems += 'another Phase 1 run is active in this session (runs must not overlap)' }
    }
    if ($problems.Count -eq 0) {
        $bundleFull = (Resolve-Path -LiteralPath $BundleDir).Path.TrimEnd('\', '/')
        $self = (Resolve-Path -LiteralPath $PSCommandPath).Path
        $expectedSelf = Join-Path $bundleFull 'scripts' | Join-Path -ChildPath 'Run-Phase1.ps1'
        if ($self -ne $expectedSelf) { $problems += 'this script must be run from the scripts folder of the bundle it verifies' }
    }
    if ($problems.Count -eq 0) {
        # Script authorization (read-only): effective policy and Mark-of-the-Web on the bundle's own scripts. Nothing is changed or unblocked.
        $effectivePolicy = [string](Get-ExecutionPolicy)
        $policyScopes = @(Get-ExecutionPolicy -List | ForEach-Object { [ordered]@{ scope = [string]$_.Scope; policy = [string]$_.ExecutionPolicy } })
        $marked = @()
        foreach ($name in @('Run-Phase1.ps1', 'Phase1Common.ps1', 'Test-Phase1Logic.ps1', 'Test-WindowsFeasibility.ps1', 'Get-AppControlDiagnostics.ps1')) {
            if ((Get-ZoneIdentifierState (Join-Path (Join-Path $bundleFull 'scripts') $name)).Present -eq $true) { $marked += $name }
        }
        $interactive = ([System.Environment]::UserInteractive -and -not ([System.Environment]::GetCommandLineArgs() -contains '-NonInteractive'))
        $advice = Get-ScriptAuthorizationAdvice $effectivePolicy $marked.Count $interactive
        $script:authorization = [ordered]@{ effective_policy = $effectivePolicy; scopes = $policyScopes; marked_scripts = $marked; interactive_session = $interactive; expectation = $advice.Expectation; advice = $advice.Message; execution = 'in this session (no child PowerShell for bundle scripts)' }
        if (@('refused', 'prompt-impossible') -contains $advice.Expectation) { $problems += $advice.Message }
        elseif ($advice.Expectation -eq 'prompt') { Write-Host $advice.Message }
    }
    if ($problems.Count -gt 0) { Stop-Run 'R01 prerequisites' ($problems -join '; '); Complete-Run }
    Add-Step 'R01 prerequisites' 'PASS' "language mode $languageMode; elevated=$($script:elevatedState.elevated); run $runId"

    # ---- R02 bundle integrity (trusted checksum supplied separately) ---------------------------------------------------------------------------------
    $bundleProblems = @(Test-BundleSums $bundleFull $TrustedSumsSha256)
    if ($bundleProblems.Count -gt 0) { Stop-Run 'R02 bundle integrity' ("bundle does not match the trusted checksum: " + (($bundleProblems | Select-Object -First 5) -join '; ')); Complete-Run }
    $copy = Join-Path $work 'bundle'
    Copy-Item -LiteralPath $bundleFull -Destination $copy -Recurse -Force
    $copyProblems = @(Test-BundleSums $copy $TrustedSumsSha256)
    if ($copyProblems.Count -gt 0) { Stop-Run 'R02 bundle integrity' ("the run copy does not match the trusted checksum: " + (($copyProblems | Select-Object -First 5) -join '; ')); Complete-Run }
    Add-Step 'R02 bundle integrity' 'PASS' 'bundle and run copy match the separately supplied checksum; no extra or missing files'

    # ---- R03 archive safety and extraction ---------------------------------------------------------------------------------------------------------
    $archive = Join-Path $copy 'runtime.tar.gz'
    $runtime = Join-Path $work 'runtime'
    $listing = Get-ArchiveListing $tarPath $archive
    $raw['tar_list_names'] = $listing.NamesExit; $raw['tar_list_types'] = $listing.VerboseExit
    if ($listing.NamesExit -ne 0 -or $listing.VerboseExit -ne 0) { Stop-Run 'R03 archive safety and extraction' "tar could not list the archive (exit codes $($listing.NamesExit), $($listing.VerboseExit))"; Complete-Run }
    $memberProblems = @(Test-ArchiveMembers $listing.Names $listing.Types $runtime)
    if ($memberProblems.Count -gt 0) { Stop-Run 'R03 archive safety and extraction' ("unsafe archive members: " + (($memberProblems | Select-Object -First 5) -join '; ')); Complete-Run }
    $expectedFiles = @($listing.Types | Where-Object { $_ -eq '-' }).Count
    if ($VerifyOnly) { Add-Step 'R03 archive safety and extraction' 'PASS' "$($listing.Names.Count) members validated ($expectedFiles files); extraction skipped (verify-only)"; Complete-Run }
    New-Item -ItemType Directory -Path $runtime | Out-Null
    $extract = Invoke-Native $tarPath @('-xzf', $archive, '-C', $runtime) 600 @{} (Join-Path $evidence 'tar-extract.txt') $work $runtime (Join-Path $copy 'saplens-host.exe')
    $raw['tar_extract'] = $extract.ExitCode
    if (-not $extract.Started -or $extract.TimedOut -or $extract.ExitCode -ne 0) { Stop-Run 'R03 archive safety and extraction' "extraction did not complete (exit code $($extract.ExitCode), timed out: $($extract.TimedOut)). If files were removed by security software, record that; do not add exclusions"; Complete-Run }
    $runtimeFull = (Resolve-Path -LiteralPath $runtime).Path.TrimEnd('\')
    $items = @(Get-ChildItem -LiteralPath $runtimeFull -Recurse -Force)
    $links = @($items | Where-Object { $_.Attributes -band [System.IO.FileAttributes]::ReparsePoint })
    $outside = @($items | Where-Object { -not $_.FullName.StartsWith($runtimeFull + '\', [System.StringComparison]::OrdinalIgnoreCase) })
    $fileCount = @($items | Where-Object { -not $_.PSIsContainer }).Count
    if ($links.Count -gt 0 -or $outside.Count -gt 0) { Stop-Run 'R03 archive safety and extraction' "extraction check failed: $($links.Count) link(s), $($outside.Count) item(s) outside the run folder"; Complete-Run }
    if ($fileCount -ne $expectedFiles) { Stop-Run 'R03 archive safety and extraction' "extracted $fileCount files, the archive lists $expectedFiles (files may have been removed by security software)"; Complete-Run }
    Add-Step 'R03 archive safety and extraction' 'PASS' "$($listing.Names.Count) members validated; $fileCount files extracted below the run folder; no links"

    # ---- R04 logic self-test (in this session; see the help text for why) ------------------------------------------------------------------------------
    $scripts = Join-Path $copy 'scripts'
    $childEnv = @{ TEMP = $tempDir; TMP = $tempDir }
    $host0 = Join-Path $copy 'saplens-host.exe'
    $test = Invoke-PhaseScript (Join-Path $scripts 'Test-Phase1Logic.ps1') @{} $childEnv (Join-Path $evidence 'logic-selftest.txt') (Join-Path $evidence 'logic-selftest-error.txt')
    $raw['logic_selftest'] = $test.ExitCode
    Add-StepError 'R04 logic self-test' $test
    $step = Resolve-ScriptStep $test 'Test-Phase1Logic.ps1'
    if ($step.Kind -eq 'security') { Stop-Run 'R04 logic self-test' $step.Reason; Complete-Run }
    if ($step.Status -eq 'HARNESS ERROR') { $selfTest = 'FAIL'; Add-Step 'R04 logic self-test' 'HARNESS ERROR' "$($step.Reason). The harness was not run. See evidence\logic-selftest-error.txt"; Complete-Run }
    if ($test.ExitCode -eq 0 -and $test.Output -match 'all assertions passed') { $selfTest = 'PASS'; Add-Step 'R04 logic self-test' 'PASS' 'all assertions passed' }
    else {
        $failedLines = @(($test.Output -split "`r?`n") | Where-Object { $_ -match '^FAIL ' })
        $selfTest = 'FAIL'
        Add-Step 'R04 logic self-test' 'HARNESS ERROR' "self-test returned exit code $($test.ExitCode) with $($failedLines.Count) failed assertion(s); the harness was not run. First: $(ConvertTo-SafeMessage ($failedLines | Select-Object -First 1) 160). See logic-selftest.txt"
        Complete-Run
    }

    # ---- R05 isolated feasibility harness (in this session; TEMP and TMP point into the run folder for its duration) --------------------------------------------
    $harnessOut = Join-Path $evidence 'harness'
    $harnessArguments = @{ HostExe = $host0; RuntimeDir = $runtimeFull; OutDir = $harnessOut; HostStartTimeoutSeconds = $HostStartTimeoutSeconds }
    if ($AllowElevated) { $harnessArguments['AllowElevated'] = $true }
    $run = Invoke-PhaseScript (Join-Path $scripts 'Test-WindowsFeasibility.ps1') $harnessArguments $childEnv (Join-Path $evidence 'harness-console.txt') (Join-Path $evidence 'harness-error.txt')
    $raw['harness'] = $run.ExitCode
    Add-StepError 'R05 isolated feasibility harness' $run
    $step = Resolve-ScriptStep $run 'Test-WindowsFeasibility.ps1'
    if ($step.Kind -eq 'security') { Stop-Run 'R05 isolated feasibility harness' $step.Reason; Complete-Run }
    if ($step.Status -eq 'HARNESS ERROR') { $harness = 'HARNESS ERROR'; Add-Step 'R05 isolated feasibility harness' 'HARNESS ERROR' $step.Reason }
    else {
        $outcome = Resolve-HarnessOutcome $run.ExitCode (Join-Path $harnessOut 'phase1-windows-result.json')
        $harness = $outcome.Status
        Add-Step 'R05 isolated feasibility harness' $harness "$($outcome.Reason); raw exit code $($run.ExitCode)"
    }

    # ---- R06 App Control diagnostics (read-only, where permitted) --------------------------------------------------------------------------------------
    if ($SkipDiagnostics) { Add-Step 'R06 App Control diagnostics (read-only)' 'NOT EXECUTED' 'skipped by request' }
    else {
        $minutes = [int][math]::Min(1440, [math]::Max(5, [math]::Ceiling(((Get-Date) - $runStart).TotalMinutes) + 2))
        $diagArguments = @{ RuntimeDir = $runtimeFull; HostExe = $host0; SinceMinutes = $minutes; OutDir = (Join-Path $evidence 'diagnostics') }
        $diag = Invoke-PhaseScript (Join-Path $scripts 'Get-AppControlDiagnostics.ps1') $diagArguments $childEnv (Join-Path $evidence 'diagnostics-console.txt') (Join-Path $evidence 'diagnostics-error.txt')
        $raw['diagnostics'] = $diag.ExitCode
        Add-StepError 'R06 App Control diagnostics (read-only)' $diag
        $diagStep = Resolve-ScriptStep $diag 'Get-AppControlDiagnostics.ps1'
        $diagJson = Join-Path $evidence 'diagnostics\app-control-diagnostics.json'
        if ($diagStep.Kind -ne 'exit') { Add-Step 'R06 App Control diagnostics (read-only)' 'NOT EXECUTED' "$($diagStep.Reason) (informational step; it does not change the overall result)" }
        elseif (Test-Path -LiteralPath $diagJson) {
            try {
                $d = Get-Content -LiteralPath $diagJson -Raw -Encoding UTF8 | ConvertFrom-Json
                $enforced = [int]$d.enforced_blocks
                $limits = @($d.limitations).Count
                $st = 'PASS'; if ($enforced -gt 0) { $st = 'BLOCKED' }
                Add-Step 'R06 App Control diagnostics (read-only)' $st "$enforced enforced block record(s), $($d.audit_only) audit-only; $limits limitation(s) (an unreadable log is not proof of no block); raw exit code $($diag.ExitCode)"
            } catch { Add-Step 'R06 App Control diagnostics (read-only)' 'NOT EXECUTED' "report unreadable (raw exit code $($diag.ExitCode))" }
        } else { Add-Step 'R06 App Control diagnostics (read-only)' 'NOT EXECUTED' "not available without elevation or log access (raw exit code $($diag.ExitCode)); run it separately elevated if IT permits" }
    }
    if ($harness -eq 'PASS' -and $enforced -gt 0) { $script:notes += 'Evidence conflict: the harness passed but the diagnostics found enforced Code Integrity records below the runtime tree. Reported as HARNESS ERROR for review.' }
}
catch {
    $where = $_.InvocationInfo.ScriptLineNumber
    Add-Step 'HARNESS ERROR' 'HARNESS ERROR' ("unexpected terminating error at line ${where}: " + (ConvertTo-SafeMessage ("$($_.Exception.GetType().Name): $($_.Exception.Message)")))
    $script:errors += , ([ordered]@{ step = 'runner'; type = $_.Exception.GetType().FullName; id = [string]$_.FullyQualifiedErrorId; message = (ConvertTo-SafeMessage ([string]$_.Exception.Message) 1000); security_restriction = (Test-SecurityRecord $_); raw_exit_code = $null })
    $script:selfTest = 'FAIL'
}
Complete-Run
