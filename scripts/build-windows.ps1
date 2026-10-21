param(
    [ValidateSet('All', 'Environment', 'Frontend', 'Python', 'Audit', 'Backend', 'Browser', 'Package', 'Verify', 'Smoke')]
    [string]$Stage = 'All'
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
# Keep audit tooling in the host interpreter, outside the isolated package environment.
$hostPython = (Get-Command python).Source
function Invoke-Stage([string]$Name, [scriptblock]$Action) {
    if ($Stage -eq 'All' -or $Stage -eq $Name) { & $Action }
}
function Measure-Task([string]$Name, [scriptblock]$Action) {
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $status = 'failed'
    Write-Host "::group::$Name"
    try { & $Action; $status = 'passed' } finally {
        $watch.Stop()
        $seconds = [math]::Round($watch.Elapsed.TotalSeconds, 2)
        Write-Host "TIMING $Name : $seconds seconds ($status)"
        if ($env:GITHUB_ACTIONS -eq 'true') { Write-Host "::notice title=Build timing::$Name : $seconds seconds ($status)" }
        Write-Host '::endgroup::'
        New-Item -ItemType Directory -Force (Join-Path $root 'backend/build') | Out-Null
        @{ stage = $Name; seconds = $seconds; status = $status } | ConvertTo-Json -Compress |
            Add-Content (Join-Path $root 'backend/build/timings.jsonl') -Encoding utf8
        if ($env:GITHUB_STEP_SUMMARY) {
            "| $Name | $seconds | $status |" | Add-Content $env:GITHUB_STEP_SUMMARY
        }
    }
}
if ($env:GITHUB_STEP_SUMMARY) {
    "`n| Build stage | Seconds | Result |`n|---|---:|---|" | Add-Content $env:GITHUB_STEP_SUMMARY
}
$originalBuildPath = $env:PATH
$env:PATH = (Split-Path $buildPython -Parent) + ';' + $env:PATH
try {
    Invoke-Stage Environment {
        Measure-Task 'Python environment creation' {
            & $hostPython -m venv backend/build/python-env
            Assert-Success 'Create build environment'
        }
    }
    Invoke-Stage Frontend {
        Push-Location frontend
        try {
            Measure-Task 'npm installation' {
                npm ci --no-audit --no-fund
                Assert-Success 'Install frontend dependencies'
            }
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
        # Audit tooling stays in the host interpreter and cannot enter the packaged environment.
        Measure-Task 'Audit tool provisioning' {
            & $hostPython -m pip install --disable-pip-version-check -r scripts/requirements-audit.txt
            Assert-Success 'Install audit tooling'
        }
        Measure-Task 'Python vulnerability audit' {
            $sitePackages = & $buildPython -c "import sysconfig; print(sysconfig.get_paths()['purelib'])"
            Assert-Success 'Locate build dependencies'
            & $hostPython -m pip_audit --path $sitePackages --vulnerability-service pypi --progress-spinner off
            Assert-Success 'Audit Windows dependencies'
        }
    }
    Invoke-Stage Backend {
        Measure-Task 'Backend tests' {
            & $buildPython -m unittest discover -s backend/tests -v
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
                npx playwright install chromium --only-shell
                Assert-Success 'Install test browser'
            }
            Measure-Task 'Playwright tests' {
                npm run test:browser
                Assert-Success 'Production browser regression tests'
            }
        } finally { Pop-Location }
    }
    Invoke-Stage Package {
        Measure-Task 'PyInstaller packaging' {
            & $buildPython scripts/write-windows-metadata.py
            Assert-Success 'Generate Windows metadata'
            $icon = Join-Path $root 'assets/sap-lens.ico'
            $metadata = Join-Path $root 'backend/build/version-info.txt'
            $iconData = $icon + ';assets'
            $frontendDist = Join-Path $root 'frontend/dist'
            & $buildPython -m PyInstaller --noconfirm --clean --onefile --windowed --name SAP-Lens --icon "$icon" --version-file "$metadata" --add-data "$iconData" --paths backend --add-data "$frontendDist;frontend/dist" --specpath backend --distpath backend/dist --workpath backend/build backend/desktop.py
            Assert-Success 'Package Windows executable'
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
    Write-Host "Completed build stage: $Stage"
} finally {
    $env:PATH = $originalBuildPath
}
