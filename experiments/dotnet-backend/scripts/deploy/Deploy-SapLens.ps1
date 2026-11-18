<#
.SYNOPSIS
  TEMPORARY compatibility wrapper. The deployment tooling moved to backend\scripts\deploy\Deploy-SapLens.ps1 when the .NET backend became the
  primary implementation. This file only forwards every argument there and returns its exit code; it contains no deployment logic.
  Use the new path; this wrapper will be removed once operators have switched (docs/deployment/WINDOWS_DEPLOYMENT.md).
#>
$target = [System.IO.Path]::Combine($PSScriptRoot, '..', '..', '..', '..', 'backend', 'scripts', 'deploy', 'Deploy-SapLens.ps1')
if (-not (Test-Path -LiteralPath $target)) { Write-Error "Deployment script not found at $target."; exit 2 }
Write-Warning 'experiments\dotnet-backend\scripts\deploy\Deploy-SapLens.ps1 moved to backend\scripts\deploy\Deploy-SapLens.ps1; forwarding.'
& $target @args
exit $LASTEXITCODE
