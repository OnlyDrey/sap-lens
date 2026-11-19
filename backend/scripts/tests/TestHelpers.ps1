# Shared Pester infrastructure. Child scripts use the current PowerShell edition by absolute path;
# a missing executable is an infrastructure failure, never a reason to skip a test.
function Get-TestPowerShellExecutable {
    $path = $env:AUTHLENS_TEST_POWERSHELL
    if (-not $path) {
        $name = if ($PSVersionTable.PSEdition -eq 'Desktop') { 'powershell.exe' }
            elseif ([IO.Path]::DirectorySeparatorChar -eq '\') { 'pwsh.exe' } else { 'pwsh' }
        $path = Join-Path $PSHOME $name
    }
    if (-not [IO.Path]::IsPathRooted($path) -or -not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "PowerShell test executable must be an existing absolute path: $path"
    }
    (Get-Item -LiteralPath $path).FullName
}

function Invoke-TestPowerShell([string[]]$Arguments) {
    $executable = Get-TestPowerShellExecutable
    # PS 5.1 wraps native stderr in ErrorRecords. Expected refusals must retain the raw text and exit code.
    $ErrorActionPreference = 'Continue'
    $output = & $executable -NoProfile -NonInteractive @Arguments 2>&1
    $code = $LASTEXITCODE
    [pscustomobject]@{ Code = $code; Output = (($output | ForEach-Object { $_.ToString() }) -join "`n") }
}

function Import-TestDeploymentModule {
    $path = (Resolve-Path (Join-Path $PSScriptRoot '../deploy/AuthLens.Deploy.psm1')).ProviderPath
    # -Force reloads a path; it does not unload same-named modules imported from other checkouts.
    # Pester resolves Mock/InModuleScope by name and rejects those distinct module identities.
    Get-Module AuthLens.Deploy -All | Remove-Module -Force
    Import-Module $path -Force -Global
}
