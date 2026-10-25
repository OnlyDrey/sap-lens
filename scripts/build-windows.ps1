param(
    [ValidateSet('All', 'Environment', 'Frontend', 'FrontendInstall', 'FrontendBuild', 'Python', 'Audit', 'Backend', 'Browser', 'Package', 'Verify', 'Smoke', 'Artifact')]
    [string]$Stage = 'All',
    [string]$ArtifactDirectory,
    [string]$ArtifactDownloadDirectory,
    [string]$ArtifactDigest,
    [string]$PythonExecutable,
    [string]$AuditPython,
    [switch]$ValidatedDeployment,
    [switch]$BenchmarkPackaging
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
function Assert-Success([string]$Stage) {
    if ($LASTEXITCODE -eq 0) { return }
    $message = "$Stage failed with exit code $LASTEXITCODE"
    if ($env:GITHUB_ACTIONS -eq 'true') { Write-Host "::error title=SAP Lens build::$message" }
    throw $message
}
$buildPython = Join-Path $root 'backend/build/python-env/Scripts/python.exe'
# Keep audit tooling outside the package environment; local callers supply a dedicated audit interpreter.
$hostPython = if ($PythonExecutable) { $PythonExecutable } else { (Get-Command python).Source }
if (-not $AuditPython) { $AuditPython = $hostPython }
function Invoke-Stage([string]$Name, [scriptblock]$Action) {
    if ($Stage -eq 'All' -or $Stage -eq $Name -or ($Name -in @('FrontendInstall', 'FrontendBuild') -and $Stage -eq 'Frontend')) { & $Action }
}
function Measure-Task([string]$Name, [scriptblock]$Action) {
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $status = 'failed'
    Write-Host "::group::$Name"
    try { & $Action; $status = 'passed' } finally {
        $watch.Stop()
        $seconds = [math]::Round($watch.Elapsed.TotalSeconds, 2)
        Write-Host "TIMING $Name : $seconds seconds ($status)"
        Write-Host '::endgroup::'
        try {
            New-Item -ItemType Directory -Force (Join-Path $root 'backend/build') | Out-Null
            @{ stage = $Name; seconds = $seconds; status = $status } | ConvertTo-Json -Compress |
                Add-Content (Join-Path $root 'backend/build/timings.jsonl') -Encoding utf8
        } catch {
            Write-Host '::warning::Stage timing could not be saved; inspect the task log.'
        }
    }
}
$originalBuildPath = $env:PATH
$env:PATH = (Split-Path $buildPython -Parent) + ';' + $env:PATH
try {
    Invoke-Stage Environment {
        $timings = Join-Path $root 'backend/build/timings.jsonl'
        if (Test-Path $timings) { Remove-Item $timings }
        foreach ($report in @('package-verification.json', 'artifact-verification.json')) {
            $reportPath = Join-Path $root "backend/build/$report"
            if (Test-Path $reportPath) { Remove-Item $reportPath }
        }
        Measure-Task 'Python environment creation' {
            & $hostPython -m venv backend/build/python-env
            Assert-Success 'Create build environment'
        }
    }
    Invoke-Stage FrontendInstall {
        Push-Location frontend
        try {
            Measure-Task 'npm installation' {
                npm ci --no-audit --no-fund
                Assert-Success 'Install frontend dependencies'
            }
        } finally { Pop-Location }
    }
    Invoke-Stage FrontendBuild {
        Push-Location frontend
        try {
            Measure-Task 'Frontend compilation' {
                npm run build
                Assert-Success 'Build production frontend'
            }
        } finally { Pop-Location }
    }
    Invoke-Stage Python {
        Measure-Task 'Python dependency installation' {
            & $buildPython -m pip install --disable-pip-version-check -r backend/requirements-build.txt -r backend/requirements-dev.txt
            Assert-Success 'Install build and test dependencies'
            & $buildPython -m pip check
            Assert-Success 'Check Python dependencies'
        }
    }
    Invoke-Stage Audit {
        # Inspect the full isolated Windows environment, including platform-only dependencies.
        # Audit tooling uses its separate interpreter and cannot enter the packaged environment.
        Measure-Task 'Audit tool provisioning' {
            & $AuditPython -m pip install --disable-pip-version-check -r scripts/requirements-audit.txt
            Assert-Success 'Install audit tooling'
        }
        Measure-Task 'Python vulnerability audit' {
            $sitePackages = & $buildPython -c "import sysconfig; print(sysconfig.get_paths()['purelib'])"
            Assert-Success 'Locate build dependencies'
            & $AuditPython -m pip_audit --path $sitePackages --vulnerability-service pypi --progress-spinner off
            Assert-Success 'Audit Windows dependencies'
        }
    }
    Invoke-Stage Backend {
        Measure-Task 'Backend tests' {
            & $buildPython -W error::DeprecationWarning -m unittest discover -s backend/tests -v
            Assert-Success 'Backend regression tests'
        }
    }
    Invoke-Stage Browser {
        Push-Location frontend
        try {
            Measure-Task 'Production JavaScript audit' {
                npm audit --omit=dev
                Assert-Success 'Audit production JavaScript dependencies'
            }
            Measure-Task 'Playwright installation' {
                # Use the exact installed CLI; do not invoke npx package resolution.
                node node_modules/playwright/cli.js install chromium --only-shell
                Assert-Success 'Install test browser'
            }
            Measure-Task 'Playwright tests' {
                npm run test:browser -- --reporter=line,github
                Assert-Success 'Production browser regression tests'
            }
        } finally { Pop-Location }
    }
    Invoke-Stage Package {
        # Standalone local builds get an unmistakable dev identity; CI requires its resolved metadata.
        if ($ValidatedDeployment) {
            # Deployment dispatches carry an explicit channel identity sealed by
            # same-run shared validation, rather than legacy desktop reservation.
            & $buildPython scripts/deployment-package.py require-inputs
        } else {
            & $buildPython scripts/release-windows.py ensure-local-build
        }
        Assert-Success 'Require resolved build identity'
        & $buildPython scripts/write-windows-metadata.py
        Assert-Success 'Generate Windows metadata'
        $icon = Join-Path $root 'assets/sap-lens.ico'
        $metadata = Join-Path $root 'backend/build/version-info.txt'
        $frontendDist = Join-Path $root 'frontend/dist'
        $buildIdentity = Join-Path $root 'backend/build/build-version.json'
        $packagingArguments = @(
            '--noconfirm', '--onefile', '--windowed', '--noupx', '--name', 'SAP-Lens',
            '--icon', $icon, '--version-file', $metadata,
            '--add-data', ($icon + ';assets'), '--paths', 'backend',
            '--add-data', ($buildIdentity + ';.'),
            '--add-data', ($frontendDist + ';frontend/dist'), '--specpath', 'backend',
            '--distpath', 'backend/dist', '--workpath', 'backend/build', 'backend/desktop.py'
        )
        Measure-Task 'PyInstaller packaging (clean)' {
            & $buildPython -m PyInstaller --clean @packagingArguments
            Assert-Success 'Package Windows executable'
        }
        if ($BenchmarkPackaging) {
            # A same-job experiment only: nothing is restored from a previous checkout/run.
            # The resulting EXE still goes through the complete verifier and GUI smoke test.
            Measure-Task 'PyInstaller packaging (same-job incremental)' {
                & $buildPython -m PyInstaller @packagingArguments
                Assert-Success 'Benchmark incremental packaging'
            }
        }
    }
    Invoke-Stage Verify {
        Measure-Task 'Package verification and checksum' {
            $hash = (Get-FileHash backend/dist/SAP-Lens.exe -Algorithm SHA256).Hash.ToLowerInvariant()
            "$hash  SAP-Lens.exe" | Set-Content backend/dist/SAP-Lens.exe.sha256 -Encoding ascii
            & $buildPython scripts/verify-windows-package.py
            Assert-Success 'Verify Windows package assets and privacy'
        }
    }
    Invoke-Stage Smoke {
        Measure-Task 'EXE smoke testing' { & (Join-Path $PSScriptRoot 'test-windows-exe.ps1') }
    }
    if ($Stage -eq 'Artifact') {
        if (-not $ArtifactDirectory) { throw 'Artifact verification needs a downloaded artifact directory.' }
        Measure-Task 'Downloaded artifact verification' {
            if ($ArtifactDownloadDirectory) {
                & $buildPython scripts/verify-artifact-zip.py --download $ArtifactDownloadDirectory --destination $ArtifactDirectory --expected-digest $ArtifactDigest
                Assert-Success 'Verify ZIP digest and exact distribution members'
            }
            $verified = Get-Content -Raw backend/build/package-verification.json | ConvertFrom-Json
            & $buildPython scripts/verify-windows-package.py --distribution $ArtifactDirectory --expected-sha256 $verified.exe_sha256 --report backend/build/artifact-verification.json
            Assert-Success 'Verify downloaded artifact matches the approved executable'
        }
    }
    Write-Host "Completed build stage: $Stage"
} finally {
    $env:PATH = $originalBuildPath
}
