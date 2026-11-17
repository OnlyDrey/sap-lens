<#
.SYNOPSIS
  Repeatable Windows x64 release build of SAP Lens 2 (.NET Server and Desktop) with the production React UI. Windows PowerShell 5.1 and PowerShell 7.

.DESCRIPTION
  1. Builds the React UI from frontend/ (npm ci + npm run build; Node.js 24 or 25, as frontend/package.json requires).
  2. Builds the .NET solution (Release) and runs the test suite (unless -SkipTests; -SkipPublishTests skips only the slow publish tests).
  3. Publishes both self-contained single-file executables (no trimming, Native AOT or compression) into a new versioned release folder:

       <Output>\SAP-Lens-2-<version>-<yyyyMMdd-HHmmss>-<commit>-win-x64\
         server\SapLens.Api.exe          Server (console or Windows service), plus e_sqlite3.dll and libSkiaSharp.dll (SQLite and image/PDF native libraries, loaded from beside the exe)
         desktop\SapLens2Prototype.exe   Desktop (WebView2, loopback only)
         symbols\server\, symbols\desktop\   .pdb files for diagnostics (not needed at runtime)
         build-manifest.json             commit, version, build time, platform, publish settings, size and SHA-256 of every artifact
         README.txt                      which executable to run and how to configure the Server
         SHA256SUMS                      checksums of every file above, build-manifest.json included

  The UI is embedded in the executables. Runtime data, databases, certificates, logs and secrets never belong in the release folder (the Server
  refuses a data directory inside it). Output defaults to experiments\dotnet-backend\artifacts\release (git-ignored); an existing release folder is
  never overwritten. Nothing is installed, started or changed on this machine.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-release.ps1 -Output C:\saplens2\builds
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
$platform = 'win-x64'

function Invoke-Step([string]$Name, [scriptblock]$Action) {
    Write-Host "==> $Name"
    & $Action
    if ($LASTEXITCODE -ne 0) { throw "$Name failed (exit code $LASTEXITCODE)." }
}

$nodeVersion = (& node --version) 2>$null
if (-not $nodeVersion) { throw 'Node.js is required to build the UI (24 or 25). Install it, for example: winget install OpenJS.NodeJS.LTS' }
$major = [int]($nodeVersion.TrimStart('v').Split('.')[0])
if ($major -lt 24 -or $major -gt 25) { throw "Node.js $nodeVersion is not supported by frontend/package.json (24 or 25 required)." }
$sdk = (& dotnet --version).Trim()
Write-Host "Node.js $nodeVersion, .NET SDK $sdk"

$sha = (& git -C $root rev-parse HEAD).Trim()
$committed = (& git -C $root log -1 --format=%cI).Trim()
$dirty = [bool](& git -C $root status --porcelain -- . ..\..\frontend)
if ($dirty) { Write-Warning 'The working tree has uncommitted changes; the manifest records source_dirty=true.' }
# Product version: product-version.json is the only source (docs/experiments/dotnet-backend/VERSIONING.md); a build never changes it.
$version = (Get-Content (Join-Path $root 'product-version.json') -Raw | ConvertFrom-Json).version
if ($version -notmatch '^(0|[1-9]\d{0,4})\.(0|[1-9]\d{0,4})\.(0|[1-9]\d{0,4})(-(alpha|beta|rc)\.([1-9]\d{0,4}))?$') { throw "product-version.json: '$version' is not MAJOR.MINOR.PATCH[-alpha.N|-beta.N|-rc.N]." }
$channel = if ($Matches[5]) { $Matches[5] } else { 'stable' }
$fileVersion = @([int]$Matches[1], [int]$Matches[2], [int]$Matches[3], $(if ($Matches[6]) { [int]$Matches[6] } else { 0 }))
$uiVersion = (Get-Content (Join-Path $root '..\..\backend\resources\product-version.json') -Raw | ConvertFrom-Json).version   # recorded, never used as this version
$built = [DateTime]::UtcNow
$release = Join-Path $Output ('SAP-Lens-2-{0}-{1}-{2}-{3}' -f $version, $built.ToString('yyyyMMdd-HHmmss'), $sha.Substring(0, 7), $platform)
if (Test-Path -LiteralPath $release) { throw "Release folder $release exists; an existing release is never overwritten." }
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

# Single-file settings live in the project files (SapLens.Api for win-x64, SapLens.Desktop always), so a manual `dotnet publish` gives the same layout.
$server = Join-Path $release 'server'; $desktop = Join-Path $release 'desktop'
Invoke-Step 'Publish server (win-x64, single file)' { & dotnet publish (Join-Path $root 'src\SapLens.Api') -c Release -r $platform -o $server $identity }
Invoke-Step 'Publish desktop (win-x64, single file)' { & dotnet publish (Join-Path $root 'src\SapLens.Desktop') -c Release -o $desktop $identity }
foreach ($part in 'server', 'desktop') {
    $symbols = Join-Path $release "symbols\$part"
    New-Item -ItemType Directory -Force $symbols | Out-Null
    Get-ChildItem (Join-Path $release $part) -Filter *.pdb | Move-Item -Destination $symbols
}

# Artifact validation: exactly the expected runtime files, build identity stamped, React UI embedded, no loose UI, settings or data.
function Test-Contains([string]$Path, [string]$Text) {
    $bytes = [System.IO.File]::ReadAllBytes($Path); $needle = [System.Text.Encoding]::UTF8.GetBytes($Text)
    $first = $needle[0]
    for ($i = [Array]::IndexOf($bytes, $first); $i -ge 0 -and $i -le $bytes.Length - $needle.Length; $i = [Array]::IndexOf($bytes, $first, $i + 1)) {
        $match = $true; for ($j = 1; $j -lt $needle.Length; $j++) { if ($bytes[$i + $j] -ne $needle[$j]) { $match = $false; break } }
        if ($match) { return $true }
    }
    return $false
}
$expected = @{ server = @('SapLens.Api.exe', 'e_sqlite3.dll', 'libSkiaSharp.dll'); desktop = @('SapLens2Prototype.exe') }
foreach ($part in 'server', 'desktop') {
    $actual = @(Get-ChildItem (Join-Path $release $part) -Recurse -File | ForEach-Object { $_.FullName.Substring((Join-Path $release $part).Length + 1) } | Sort-Object)
    if (($actual -join '|') -ne (($expected[$part] | Sort-Object) -join '|')) { throw "Unexpected files in ${part}: $($actual -join ', ') (expected $($expected[$part] -join ', '))." }
}
foreach ($check in 'server\SapLens.Api.exe', 'desktop\SapLens2Prototype.exe') {
    $file = Join-Path $release $check
    if (-not (Test-Contains $file "$version+$sha")) { throw "Product version and build identity $version+$sha missing in $check." }
    # The UI is embedded as resources named SapLensUi/<path> (the separator after "assets" is the build machine's; the server normalizes it).
    if (-not (Test-Contains $file 'SapLensUi/index.html')) { throw "index.html missing from the embedded UI of $check." }
    if (-not ((Test-Contains $file 'SapLensUi/assets/') -or (Test-Contains $file 'SapLensUi/assets\'))) { throw "React UI assets missing in $check." }
}
if (-not (Test-Contains (Join-Path $server 'SapLens.Api.exe') 'Microsoft.Extensions.Hosting.WindowsServices.dll')) { throw 'The Windows service host is missing in the server executable.' }

$readme = (Get-Content (Join-Path $PSScriptRoot 'release-README.txt') -Raw).Replace('{{VERSION}}', $version).Replace('{{SHA}}', $sha).
    Replace('{{BUILT}}', $built.ToString('yyyy-MM-dd HH:mm:ss')).Replace('{{PLATFORM}}', 'Windows x64')
[System.IO.File]::WriteAllText((Join-Path $release 'README.txt'), $readme.Replace("`r`n", "`n").Replace("`n", "`r`n"))

function Get-Artifacts([string]$Folder, [string[]]$Exclude) {
    # Ordinal path order: the same on every machine and culture.
    $files = @(Get-ChildItem $Folder -Recurse -File | Where-Object { $Exclude -notcontains $_.FullName.Substring($Folder.Length + 1) })
    [string[]]$keys = $files | ForEach-Object { $_.FullName.Substring($Folder.Length + 1).Replace('\', '/') }
    $order = [int[]](0..($files.Count - 1)); [Array]::Sort($keys, $order, [StringComparer]::Ordinal)
    for ($i = 0; $i -lt $keys.Count; $i++) {
        $file = $files[$order[$i]]
        [ordered]@{ path = $keys[$i]; bytes = $file.Length; sha256 = (Get-FileHash $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
    }
}
$manifest = [ordered]@{
    schema = 1; product = 'SAP Lens 2'; version = $version; channel = $channel; file_version = $fileVersion; ui_source_version = $uiVersion
    source_sha = $sha; source_dirty = $dirty; source_committed_at = $committed
    branch = (& git -C $root rev-parse --abbrev-ref HEAD).Trim(); build_timestamp_utc = $built.ToString('yyyy-MM-ddTHH:mm:ssZ'); target_platform = $platform
    dotnet_sdk = $sdk; node = $nodeVersion
    publish = [ordered]@{ self_contained = $true; single_file = $true; trimmed = $false; native_aot = $false; compressed = $false
        server_native_libraries = 'beside the executable (e_sqlite3.dll, libSkiaSharp.dll)'; desktop_native_libraries = 'bundled, extracted to a temporary folder at start' }
    executables = [ordered]@{ server = 'server/SapLens.Api.exe'; desktop = 'desktop/SapLens2Prototype.exe' }
    artifacts = @(Get-Artifacts $release @('build-manifest.json', 'SHA256SUMS'))
}
[System.IO.File]::WriteAllText((Join-Path $release 'build-manifest.json'), ($manifest | ConvertTo-Json -Depth 5))
$sums = Get-Artifacts $release @('SHA256SUMS') | ForEach-Object { '{0}  ./{1}' -f $_.sha256, $_.path }
[System.IO.File]::WriteAllText((Join-Path $release 'SHA256SUMS'), (($sums -join "`n") + "`n"))

# No secrets or environment-specific values in the release (key/certificate/secret files, token formats, and the personal values listed in the
# git-ignored .secret-scan.local). Needs Python; without it the scan is reported as not run.
$python = @('python', 'py', 'python3') | Where-Object { Get-Command $_ -ErrorAction SilentlyContinue } | Select-Object -First 1
if ($python) { Invoke-Step 'Secret scan of the release folder' { & $python (Join-Path $root '..\..\scripts\check-secrets.py') --path $release } }
else { Write-Warning 'Python not found: the release secret scan (scripts/check-secrets.py --path) was NOT run.' }
& (Join-Path $PSScriptRoot 'verify-release.ps1') -ReleasePath $release
if ($LASTEXITCODE -ne 0) { throw 'Release verification failed.' }
foreach ($exe in 'server\SapLens.Api.exe', 'desktop\SapLens2Prototype.exe') { Write-Host ('{0}: {1:N1} MB' -f $exe, ((Get-Item (Join-Path $release $exe)).Length / 1MB)) }
Write-Host "Release build complete: $release"
Write-Host 'Nothing was installed or started.'
