<#
.SYNOPSIS
  Repeatable release build of SAP Lens (.NET server and Desktop) with the production React UI. Windows PowerShell 5.1 and PowerShell 7.

.DESCRIPTION
  1. Builds the React UI from frontend/ (npm ci + npm run build; Node.js 24 or 25, as frontend/package.json requires).
  2. Builds the .NET solution (Release) and runs the test suite (unless -SkipTests; -SkipPublishTests skips only the slow publish tests).
  3. Publishes self-contained packages: server-win-x64 (SapLens.Api.exe, Windows service capable) and desktop-win-x64 (SapLens2Prototype.exe).
  The UI is embedded in SapLens.Api.dll; nothing is copied after publishing. Output defaults to experiments\dotnet-backend\artifacts\release
  (git-ignored). Nothing is installed, started or changed on this machine.
#>
param(
    [string]$Output = '',
    [switch]$SkipTests,
    [switch]$SkipPublishTests
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$frontend = (Resolve-Path (Join-Path $root '..\..\frontend')).Path
if (-not $Output) { $Output = Join-Path $root 'artifacts\release' }

function Invoke-Step([string]$Name, [scriptblock]$Action) {
    Write-Host "==> $Name"
    & $Action
    if ($LASTEXITCODE -ne 0) { throw "$Name failed (exit code $LASTEXITCODE)." }
}

$nodeVersion = (& node --version) 2>$null
if (-not $nodeVersion) { throw 'Node.js is required to build the UI (24 or 25). Install it, for example: winget install OpenJS.NodeJS.LTS' }
$major = [int]($nodeVersion.TrimStart('v').Split('.')[0])
if ($major -lt 24 -or $major -gt 25) { throw "Node.js $nodeVersion is not supported by frontend/package.json (24 or 25 required)." }
Write-Host "Node.js $nodeVersion, .NET SDK $(& dotnet --version)"

Push-Location $frontend
try {
    Invoke-Step 'Install frontend dependencies (npm ci)' { & npm ci --no-audit --no-fund }
    Invoke-Step 'Build the React UI' { & npm run build }
} finally { Pop-Location }

Invoke-Step 'Build the .NET solution' { & dotnet build (Join-Path $root 'SapLens.slnx') -c Release }
if (-not $SkipTests) {
    $filter = if ($SkipPublishTests) { 'Category!=Publish' } else { '' }
    if ($filter) { Invoke-Step 'Run tests' { & dotnet test (Join-Path $root 'tests\SapLens.Tests') -c Release --no-build --filter $filter } }
    else { Invoke-Step 'Run tests' { & dotnet test (Join-Path $root 'tests\SapLens.Tests') -c Release --no-build } }
}
Invoke-Step 'Publish server (win-x64)' { & dotnet publish (Join-Path $root 'src\SapLens.Api') -c Release -r win-x64 --self-contained true -o (Join-Path $Output 'server-win-x64') }
Invoke-Step 'Publish desktop (win-x64)' { & dotnet publish (Join-Path $root 'src\SapLens.Desktop') -c Release -o (Join-Path $Output 'desktop-win-x64') }

foreach ($package in 'server-win-x64', 'desktop-win-x64') {
    $folder = Join-Path $Output $package
    $bytes = (Get-ChildItem $folder -Recurse -File | Measure-Object Length -Sum).Sum
    Write-Host ('{0}: {1:N0} MB in {2}' -f $package, ($bytes / 1MB), $folder)
}
Write-Host 'Release build complete. Nothing was installed or started.'
