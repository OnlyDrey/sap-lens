BeforeAll {
    . (Join-Path $PSScriptRoot 'TestHelpers.ps1')
}

Describe 'PowerShell test infrastructure' {
    It 'uses the current edition without relying on PATH' {
        $previous = $env:AUTHLENS_TEST_POWERSHELL
        try {
            $env:AUTHLENS_TEST_POWERSHELL = ''
            $executable = Get-TestPowerShellExecutable
            Split-Path $executable | Should -Be $PSHOME
            $run = Invoke-TestPowerShell @('-Command', '$PSVersionTable.PSEdition; exit 0')
            $run.Code | Should -Be 0
            $run.Output.Trim() | Should -Be $PSVersionTable.PSEdition
        } finally { $env:AUTHLENS_TEST_POWERSHELL = $previous }
    }

    It 'refuses an invalid explicit executable rather than skipping or falling back' {
        $previous = $env:AUTHLENS_TEST_POWERSHELL
        try {
            $env:AUTHLENS_TEST_POWERSHELL = Join-Path $TestDrive 'missing-shell.exe'
            { Get-TestPowerShellExecutable } | Should -Throw '*existing absolute path*'
            $env:AUTHLENS_TEST_POWERSHELL = 'powershell.exe'
            { Get-TestPowerShellExecutable } | Should -Throw '*existing absolute path*'
        } finally { $env:AUTHLENS_TEST_POWERSHELL = $previous }
    }

    It 'preserves refusal exit codes and raw stderr under ErrorActionPreference Stop' {
        $ErrorActionPreference = 'Stop'
        $scriptFile = Join-Path $TestDrive 'refusal with spaces.ps1'
        Set-Content -LiteralPath $scriptFile '[Console]::Error.WriteLine("synthetic refusal"); exit 7'
        $run = Invoke-TestPowerShell @('-File', $scriptFile)
        $run.Code | Should -Be 7
        $run.Output | Should -Match 'synthetic refusal'
        $ErrorActionPreference | Should -Be 'Stop'
    }

    It 'removes a second module identity before Pester resolves a mock by name' {
        $copy = Join-Path $TestDrive 'other-checkout'
        New-Item -ItemType Directory $copy | Out-Null
        Copy-Item (Join-Path $PSScriptRoot '../deploy/AuthLens.Deploy.psm1'),
            (Join-Path $PSScriptRoot '../deploy/AuthLens.Paths.ps1'),
            (Join-Path $PSScriptRoot '../deploy/AuthLens.Acl.ps1'),
            (Join-Path $PSScriptRoot '../deploy/AuthLens.Installer.ps1') -Destination $copy
        try {
            Import-TestDeploymentModule
            Import-Module (Join-Path $copy 'AuthLens.Deploy.psm1') -Force -Global
            @(Get-Module AuthLens.Deploy -All).Count | Should -Be 2
            { InModuleScope AuthLens.Deploy { } } | Should -Throw '*Multiple script or manifest modules*'
            Import-TestDeploymentModule
            $loaded = @(Get-Module AuthLens.Deploy -All)
            $loaded.Count | Should -Be 1
            $loaded[0].Path | Should -Be (Resolve-Path (Join-Path $PSScriptRoot '../deploy/AuthLens.Deploy.psm1')).ProviderPath
            Mock -ModuleName AuthLens.Deploy Get-ALService { 'isolated fixture' }
            InModuleScope AuthLens.Deploy { Get-ALService 'unused' | Should -Be 'isolated fixture' }
        } finally { Get-Module AuthLens.Deploy -All | Remove-Module -Force }
    }
}
