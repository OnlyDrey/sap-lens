# Self-test of the pure logic in Phase1Common.ps1 with synthetic data. Runs on Linux or Windows PowerShell; exits non-zero on the first failed assertion.
# It does not touch Windows policy, registry or any installed application.
. (Join-Path $PSScriptRoot 'Phase1Common.ps1')
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
if ($failures -gt 0) { Write-Host "$failures assertion(s) failed"; exit 1 }
Write-Host 'all assertions passed'
