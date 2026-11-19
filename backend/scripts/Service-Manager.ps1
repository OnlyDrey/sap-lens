<#
.SYNOPSIS
  AuthLens local administration. Uses the packaged server executable; no SDK, listener or service restart.
.DESCRIPTION
  Key values never appear in output or process arguments. Export writes a new private file only.
  Administrator codes are shown locally once: do not run code actions under a transcript or redirect them to logs.
#>
[CmdletBinding()]
param(
    [ValidateSet('Menu', 'Status', 'CreateKey', 'ExportKey', 'VerifyKey', 'ActivationCode', 'RecoveryCode')]
    [string]$Action = 'Menu',
    [string]$DataDirectory = 'C:\ProgramData\AuthLens\data',
    [string]$Executable = '',
    [string]$Path = '',
    [string]$Username = '',
    [switch]$Yes
)
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
if (-not $Executable) {
    $Executable = Join-Path $PSScriptRoot 'server\AuthLens.Api.exe'
    if (-not (Test-Path -LiteralPath $Executable)) { $Executable = 'C:\ProgramData\AuthLens\releases\current\server\AuthLens.Api.exe' }
}

function Get-AuthLensAdminArguments([string]$Operation, [string]$Data, [string]$File, [string]$User) {
    if ($Data -notmatch '^([A-Za-z]:[\\/]|\\\\|/)') { throw 'Select an absolute application data directory.' }
    if ($Operation -in @('CreateKey', 'ExportKey', 'VerifyKey') -and $File -notmatch '^([A-Za-z]:[\\/]|\\\\|/)') { throw 'Select an absolute recovery-key file path.' }
    $arguments = switch ($Operation) {
        'Status' { '--backup-key'; 'status' }
        'CreateKey' { '--backup-key'; 'create'; $File }
        'ExportKey' { '--backup-key'; 'export'; $File }
        'VerifyKey' { '--backup-key'; 'verify'; $File }
        'ActivationCode' { '--accounts-code' }
        'RecoveryCode' { if ($User -notmatch '\A[A-Za-z0-9_.@-]{1,100}\z') { throw 'Select the existing administrator username.' }; '--accounts-code'; '--recover-administrator'; $User }
        default { throw 'Unknown local administration action.' }
    }
    @($arguments) + @('--data-dir', $Data)
}

function Test-AuthLensAdminElevation {
    ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-AuthLensLocalAdmin([string]$Operation, [string]$File, [string]$User, [bool]$Confirmed) {
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) { throw 'Packaged AuthLens.Api.exe was not found. Specify -Executable from a verified release.' }
    if ($Operation -ne 'Status') {
        if (-not $Confirmed) { throw 'Repeat with -Yes after reviewing the data directory and operation. Key and code actions are never automatic.' }
        if (-not (Test-AuthLensAdminElevation)) { throw 'Open PowerShell as administrator for this local operation.' }
    }
    $arguments = @(Get-AuthLensAdminArguments $Operation $DataDirectory $File $User)
    if ($Operation -eq 'CreateKey') {
        $directory = Split-Path $File
        $ancestor = [IO.Path]::GetFullPath($directory)
        while ($ancestor) {
            if ((Test-Path -LiteralPath $ancestor) -and ((Get-Item -LiteralPath $ancestor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Recovery-key directories must not traverse reparse points.' }
            $ancestor = [IO.Path]::GetDirectoryName($ancestor)
        }
        if (-not (Test-Path -LiteralPath $directory)) {
            New-Item -ItemType Directory -Path $directory -Force | Out-Null
            $acl = [Security.AccessControl.DirectorySecurity]::new()
            $acl.SetAccessRuleProtection($true, $false)
            foreach ($sid in 'S-1-5-18', 'S-1-5-32-544', [Security.Principal.WindowsIdentity]::GetCurrent().User.Value) {
                $identity = [Security.Principal.SecurityIdentifier]::new($sid)
                $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
            }
            Set-Acl -LiteralPath $directory -AclObject $acl
        }
    }
    # The process receives file paths only; it reads key files itself. Never read or echo the key here.
    $ErrorActionPreference = 'Continue'
    $result = & $Executable @arguments 2>&1
    $code = $LASTEXITCODE
    if ($code -ne 0) { throw ('AuthLens refused the local operation: ' + (($result | ForEach-Object { "$_" }) -join ' ')) }
    $result | ForEach-Object { Write-Host "$_" }
}

if ($Action -eq 'Menu') {
    Write-Host "AuthLens Service Manager`nData: $DataDirectory`nExecutable: $Executable"
    Write-Host 'This tool never stops, starts or migrates services. Key export is local-only.'
    Write-Host "1  Key status and fingerprint`n2  Create initial host key`n3  Export recovery copy`n4  Verify recovery copy`n5  Initial administrator activation code`n6  Existing administrator recovery code`n0  Exit"
    $choice = Read-Host 'Choose action'
    $actions = @{ '1' = 'Status'; '2' = 'CreateKey'; '3' = 'ExportKey'; '4' = 'VerifyKey'; '5' = 'ActivationCode'; '6' = 'RecoveryCode' }
    if (-not $actions.ContainsKey($choice)) { return }
    $Action = $actions[$choice]
    if ($Action -in @('CreateKey', 'ExportKey', 'VerifyKey')) { $Path = Read-Host 'Absolute key file path (create/export never overwrites)' }
    if ($Action -eq 'RecoveryCode') { $Username = Read-Host 'Existing administrator username (all their sessions will end)' }
    if ($Action -ne 'Status') {
        if ($Action -in @('ActivationCode', 'RecoveryCode')) { Write-Host 'The one-use code will be displayed locally. Do not record this session or save its output.' }
        $Yes = (Read-Host "Confirm $Action for $DataDirectory by typing YES") -ceq 'YES'
    }
}
Invoke-AuthLensLocalAdmin $Action $Path $Username ([bool]$Yes)
