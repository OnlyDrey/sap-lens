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

$sha = (& git -C $root rev-parse HEAD).Trim()
$dirty = [bool](& git -C $root status --porcelain -- . ..\..\frontend)
if ($dirty) { Write-Warning 'The working tree has uncommitted changes; the manifest records source_dirty=true.' }
$identity = "-p:SourceRevisionId=$sha"

Push-Location $frontend
try {
    Invoke-Step 'Install frontend dependencies (npm ci)' { & npm ci --no-audit --no-fund }
    Invoke-Step 'Build the React UI' { & npm run build }
} finally { Pop-Location }

# The solution contains every project, the test project included, so `dotnet test --no-build` runs exactly what this build produced (with the UI
# embedded from the dist just built), never older binaries left in tests\*\bin.
Invoke-Step 'Build the .NET solution' { & dotnet build (Join-Path $root 'SapLens.slnx') -c Release $identity }
if (-not $SkipTests) {
    $filter = if ($SkipPublishTests) { 'Category!=Publish' } else { '' }
    if ($filter) { Invoke-Step 'Run tests' { & dotnet test (Join-Path $root 'tests\SapLens.Tests') -c Release --no-build --filter $filter } }
    else { Invoke-Step 'Run tests' { & dotnet test (Join-Path $root 'tests\SapLens.Tests') -c Release --no-build } }
}
if (Test-Path -LiteralPath $Output) { throw "Output folder $Output exists. Choose a new folder; an existing release is never overwritten." }
Invoke-Step 'Publish server (win-x64)' { & dotnet publish (Join-Path $root 'src\SapLens.Api') -c Release -r win-x64 --self-contained true -o (Join-Path $Output 'server-win-x64') $identity }
Invoke-Step 'Publish desktop (win-x64)' { & dotnet publish (Join-Path $root 'src\SapLens.Desktop') -c Release -o (Join-Path $Output 'desktop-win-x64') $identity }

# Artifact validation: build identity stamped, React UI embedded, no loose UI folders.
function Test-Contains([string]$Path, [string]$Text) {
    $bytes = [System.IO.File]::ReadAllBytes($Path); $needle = [System.Text.Encoding]::UTF8.GetBytes($Text)
    $first = $needle[0]
    for ($i = [Array]::IndexOf($bytes, $first); $i -ge 0 -and $i -le $bytes.Length - $needle.Length; $i = [Array]::IndexOf($bytes, $first, $i + 1)) {
        $match = $true; for ($j = 1; $j -lt $needle.Length; $j++) { if ($bytes[$i + $j] -ne $needle[$j]) { $match = $false; break } }
        if ($match) { return $true }
    }
    return $false
}
foreach ($check in 'server-win-x64\SapLens.Api.dll', 'desktop-win-x64\SapLens2Prototype.exe') {
    $file = Join-Path $Output $check
    if (-not (Test-Contains $file "+$sha")) { throw "Build identity $sha missing in $check." }
    if (-not (Test-Contains $file 'SapLens.Api.wwwroot.assets.')) { throw "React UI missing in $check." }
    # The embedded-files manifest must nest the UI under wwwroot; a separator in a file name makes it invisible to the provider.
    if (-not (Test-Contains $file '<File Name="index.html">')) { throw "index.html missing from the embedded-files manifest of $check." }
    if ((Test-Contains $file '<File Name="wwwroot/') -or (Test-Contains $file '<File Name="wwwroot\')) { throw "UI files embedded with a separator in their name in $check." }
}
$sums = Get-ChildItem $Output -Recurse -File | Sort-Object FullName | ForEach-Object {
    '{0}  ./{1}' -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(), $_.FullName.Substring($Output.Length).TrimStart('\').Replace('\', '/') }
[System.IO.File]::WriteAllLines((Join-Path $Output 'SHA256SUMS'), [string[]]$sums)
$packages = [ordered]@{}
foreach ($package in 'server-win-x64', 'desktop-win-x64') {
    $files = @(Get-ChildItem (Join-Path $Output $package) -Recurse -File)
    $packages[$package] = [ordered]@{ files = $files.Count; bytes = ($files | Measure-Object Length -Sum).Sum }
}
$manifest = [ordered]@{ product = 'SAP Lens 2 (.NET experiment)'; version = '0.0.0-experiment'; source_sha = $sha; source_dirty = $dirty
    branch = (& git -C $root rev-parse --abbrev-ref HEAD).Trim(); dotnet_sdk = (& dotnet --version).Trim(); node = $nodeVersion; packages = $packages
    checksums_sha256 = (Get-FileHash (Join-Path $Output 'SHA256SUMS') -Algorithm SHA256).Hash.ToLowerInvariant() }
[System.IO.File]::WriteAllText((Join-Path $Output 'manifest.json'), ($manifest | ConvertTo-Json -Depth 4))

foreach ($package in 'server-win-x64', 'desktop-win-x64') {
    $folder = Join-Path $Output $package
    $bytes = (Get-ChildItem $folder -Recurse -File | Measure-Object Length -Sum).Sum
    Write-Host ('{0}: {1:N0} MB in {2}' -f $package, ($bytes / 1MB), $folder)
}
Write-Host 'Release build complete. Nothing was installed or started.'
