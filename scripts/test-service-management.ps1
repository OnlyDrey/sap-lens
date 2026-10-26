# Portable helper regression tests; this does not simulate or certify Windows SCM.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$tokens = $null; $errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $root 'scripts/manage-server-service.ps1'),[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Service management syntax failed.' }
# Load only the actual helper definitions, never the script's service operations.
foreach ($name in @('Assert-NewBundle','Read-ServiceConfiguration')) {
    $definition = $ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name },$false)
    if ($definition.Count -ne 1) { throw 'Missing canonical helper.' }
    . ([scriptblock]::Create($definition[0].Extent.Text))
}
$temporary = Join-Path ([IO.Path]::GetTempPath()) ('sap-lens-service-helpers-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $temporary | Out-Null
function Assert-Rejected([scriptblock]$Operation) {
    $failed = $false
    try { & $Operation | Out-Null } catch { $failed = $true }
    if (-not $failed) { throw 'Invalid service input was accepted.' }
}
try {
    $bundle = Join-Path $temporary 'bundle'; New-Item -ItemType Directory $bundle | Out-Null
    $files = @{}
    foreach ($name in @('SAPLensService.exe','manage-server-service.ps1','README.md','LICENSE-WinSW.txt')) {
        $path = Join-Path $bundle $name; [IO.File]::WriteAllText($path,'synthetic')
        $files[$name] = (Microsoft.PowerShell.Utility\Get-FileHash $path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    # The official wrapper's download/digest belongs to native package verification.
    # Only its digest result is mocked in this filesystem-focused helper test.
    function Get-FileHash {
        param([string]$Path,[string]$Algorithm)
        if ([IO.Path]::GetFileName($Path) -eq 'SAPLensService.exe') { return @{Hash='05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da'} }
        Microsoft.PowerShell.Utility\Get-FileHash $Path -Algorithm $Algorithm
    }
    $files['SAPLensService.exe']='05b82d46ad331cc16bdc00de5c6332c1ef818df8ceefcd49c726553209b3a0da'
    $report = @{verification='passed';signing='disabled';format='onedir-console-service';identity=@{version='0.1.0'};files=$files}
    [IO.File]::WriteAllText((Join-Path $bundle 'verification-report.json'),($report | ConvertTo-Json -Depth 5))
    if ((Assert-NewBundle $bundle).identity.version -ne '0.1.0') { throw 'Valid bundle identity was lost.' }
    [IO.File]::WriteAllText((Join-Path $bundle 'unexpected.csv'),'synthetic')
    Assert-Rejected { Assert-NewBundle $bundle }
    Remove-Item (Join-Path $bundle 'unexpected.csv')
    [IO.File]::WriteAllText((Join-Path $bundle 'README.md'),'tampered')
    Assert-Rejected { Assert-NewBundle $bundle }
    $InstallDirectory = $bundle; $wrapper = Join-Path $bundle 'SAPLensService.exe'
    function Get-CimInstance { return @{PathName=('"'+$wrapper+'"')} }
    $configuration = Join-Path $bundle 'SAPLensService.xml'
    $data = Join-Path $temporary 'private-data'
    [IO.File]::WriteAllText($configuration,('<service><env name="SAP_LENS_DEPLOYMENT_MODE" value="server"/><env name="SAP_LENS_DATA_DIR" value="'+[Security.SecurityElement]::Escape($data)+'"/></service>'))
    $before = [IO.File]::ReadAllText($configuration)
    if ((Read-ServiceConfiguration).SAP_LENS_DATA_DIR -ne $data) { throw 'Configured data directory was not preserved.' }
    if ([IO.File]::ReadAllText($configuration) -ne $before) { throw 'Reading configuration modified administrator XML.' }
    [IO.File]::WriteAllText($configuration,'<!DOCTYPE service [<!ENTITY x SYSTEM "file:///not-read">]><service>&x;</service>')
    Assert-Rejected { Read-ServiceConfiguration }
    Write-Output 'Service helper regressions passed: exact contents, checksums, configuration preservation and external-entity rejection. No SCM operations executed.'
} finally { Remove-Item $temporary -Recurse -Force }
