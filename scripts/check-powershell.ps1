# Parse without executing the Windows build or requiring a Windows GUI.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
foreach ($relative in @('scripts/build-local.ps1', 'scripts/build-windows.ps1', 'scripts/test-windows-exe.ps1', 'scripts/check-powershell.ps1')) {
    $tokens = $null
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $root $relative), [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw ($errors.Message -join '; ') }
    # These scripts must stop on PowerShell errors; native exit codes have explicit guards.
    if ($ast.Extent.Text -notmatch "(?m)^\`$ErrorActionPreference = 'Stop'") {
        throw "Missing fail-fast policy: $relative"
    }
    $dynamicExecution = $ast.FindAll({ param($node)
        $node -is [System.Management.Automation.Language.CommandAst] -and
        $node.GetCommandName() -in @('Invoke-Expression', 'iex')
    }, $true)
    if ($dynamicExecution.Count) { throw "Unexpected dynamic expression execution: $relative" }
    Write-Output "$relative syntax and static guards passed"
}
