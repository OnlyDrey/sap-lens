<#
.SYNOPSIS
  Runs the SAP Lens 1 to .NET .slbak migration procedure of docs/migration/V1_MIGRATION.md against the synthetic fixture.
.DESCRIPTION
  Uses only synthetic data (tests/AuthLens.Tests/Fixtures/v1-data, written by the SAP Lens 1 application) and a scratch folder; never a real
  installation. Steps: host key, preview with the recovery key file, refusal of a wrong key, run, activation at the next start, HTTP check, status,
  rollback at the next start. Exits 0 when every step behaves as documented, 1 otherwise.
.EXAMPLE
  pwsh -File scripts/tests/v1-migration-procedure.ps1 -Exe C:\AuthLens-Test\release\server\AuthLens.Api.exe -Root C:\AuthLens-Test\procedure-test
#>
param(
    [Parameter(Mandatory)] [string] $Exe,
    [Parameter(Mandatory)] [string] $Root,
    [int] $Port = 18796
)
$ErrorActionPreference = 'Stop'
$Fixture = Join-Path $PSScriptRoot '../../tests/AuthLens.Tests/Fixtures/v1-data'
$failures = 0
function Check([bool] $ok, [string] $what) { if ($ok) { "ok    $what" } else { "FAIL  $what"; $script:failures++ } }
function Status { (& $Exe --migrate-v1 status --id $Preview.id --data-dir $DataDir | Out-String | ConvertFrom-Json).status }
function Start-Server([string] $log) {
    $p = Start-Process -FilePath $Exe -ArgumentList @('--data-dir', $DataDir, '--port', "$Port", '--auth', 'shared-token') -PassThru -RedirectStandardOutput $log -RedirectStandardError "$log.err"
    for ($i = 0; $i -lt 30; $i++) { try { Invoke-RestMethod "http://127.0.0.1:$Port/health/ready" | Out-Null; return $p } catch { Start-Sleep 1 } }
    throw 'The server did not become ready.'
}
if (Test-Path $Root) { throw "Use a new, empty -Root folder ($Root exists)." }
$DataDir  = Join-Path $Root 'data'
$Work     = Join-Path $Root 'migration'
$Escrow   = Join-Path $Root 'escrow'
$V1Backup = Join-Path $Work 'AuthLens-backup-synthetic.slbak'
New-Item -ItemType Directory -Force $Work, $Escrow, (Join-Path $Root 'keys') | Out-Null
Copy-Item (Join-Path $Fixture 'v1-host.slbak') $V1Backup
$Expected = Get-Content (Join-Path $Fixture 'expected.json') -Raw | ConvertFrom-Json
Set-Content -NoNewline -Path (Join-Path $Escrow 'saplens1-recovery.key') -Value $Expected.recovery_key

& $Exe --backup-key create (Join-Path $Root 'keys/backup.key') --data-dir $DataDir | Out-Null
Check ($LASTEXITCODE -eq 0) 'AuthLens host backup key created'
& $Exe --backup-key export (Join-Path $Escrow 'sap-lens-recovery.key') --data-dir $DataDir | Out-Null
Check ($LASTEXITCODE -eq 0) 'recovery copy exported'

& $Exe --migrate-v1 preview --source $V1Backup --v1-key-file (Join-Path $Escrow 'saplens1-recovery.key') --data-dir $DataDir | Out-File -Encoding utf8 (Join-Path $Work 'preview.json')
Check ($LASTEXITCODE -eq 0) 'preview'
$Preview = Get-Content (Join-Path $Work 'preview.json') -Raw | ConvertFrom-Json
Check ($Preview.status -eq 'previewed' -and $Preview.blockers.Count -eq 0) "preview status $($Preview.status), no blockers"
$sod = ($Preview.stores | Where-Object { $_.store -like 'SoD decision*' }).count
Check ($sod -eq $Expected.sod.events) "SoD decision events in preview: $sod"
$null = & $Exe --migrate-v1 preview --source $V1Backup --v1-key-file (Join-Path $Escrow 'sap-lens-recovery.key') --data-dir $DataDir 2>&1
Check ($LASTEXITCODE -eq 3) 'a wrong recovery key is refused (exit 3)'

& $Exe --migrate-v1 run --id $Preview.id --approve $Preview.digest --data-dir $DataDir | Out-File -Encoding utf8 (Join-Path $Work 'run.json')
$Run = Get-Content (Join-Path $Work 'run.json') -Raw | ConvertFrom-Json
Check ($Run.status -eq 'verified' -and $Run.verification.sod_chain -eq $Expected.sod.events -and $Run.backup.encrypted) "run verified, SoD chain $($Run.verification.sod_chain), encrypted migration backup"

& $Exe --migrate-v1 activate --id $Preview.id --approve $Preview.digest --data-dir $DataDir | Out-Null
Check ($LASTEXITCODE -eq 0) 'activation requested'
$server = Start-Server (Join-Path $Work 'server.log')
try {
    Check ($null -ne (Select-String -Path (Join-Path $Work 'server.log') -Pattern 'SAP Lens 1 migration [0-9a-f]+ activated')) 'activation applied at start (log)'
    $Token = (Get-Content (Join-Path $DataDir 'api-token') -Raw).Trim()
    $Periods = Invoke-RestMethod -Headers @{ 'X-SAP-Lens-Token' = $Token } "http://127.0.0.1:$Port/api/sod/periods"
    $states = ($Periods.items | Sort-Object id | ForEach-Object { $_.state }) -join ','
    $expectedStates = ($Expected.sod.periods.PSObject.Properties | Sort-Object Name | ForEach-Object { $_.Value.state }) -join ','
    Check ($states -eq $expectedStates) "review periods migrated ($states)"
} finally { Stop-Process -Id $server.Id; $server.WaitForExit() }
Check ((Status) -eq 'activated') 'status activated'

& $Exe --migrate-v1 rollback --id $Preview.id --data-dir $DataDir | Out-Null
$server = Start-Server (Join-Path $Work 'server2.log')
Stop-Process -Id $server.Id; $server.WaitForExit()
Check ((Status) -eq 'rolled_back') 'status rolled_back after the next start'
if ($failures) { "$failures check(s) failed"; exit 1 }
'All procedure checks passed.'
