# Parse active scripts without invoking any deployment or SCM operation. Runs with PowerShell 7 on Linux or Windows.
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$files = @(Get-ChildItem (Join-Path $root 'scripts') -Recurse -File | Where-Object { $_.Extension -in '.ps1', '.psm1' })
$failures = 0
foreach ($file in $files) {
    $tokens = $null; $errors = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$errors)
    foreach ($problem in $errors) {
        Write-Error -Message ('{0}:{1}: {2}' -f $file.Name, $problem.Extent.StartLineNumber, $problem.Message) -ErrorAction Continue
        $failures++
    }
}
Write-Host ('PowerShell syntax: {0} active scripts, {1} errors. No native operations executed.' -f $files.Count, $failures)
if ($failures) { exit 1 }
