BeforeAll {
    . (Join-Path $PSScriptRoot 'TestHelpers.ps1')
    Import-TestDeploymentModule
    Mock -ModuleName AuthLens.Deploy Get-SL2Service { [pscustomobject]@{ Exists = $false } }
    function New-NamingFixture {
        $script:SourceFile = Join-Path $TestDrive 'source.json'
        $script:TargetFile = Join-Path $TestDrive 'target.json'
        $raw = [ordered]@{ RepositoryPath = 'C:\example\repo'; ServiceName = 'SapLens2'; ServiceAccount = 'LocalSystem'
            ListenAddress = '192.0.2.10'; Port = 18795; AllowedHosts = @('lens.example.com'); TrustedProxies = @('192.0.2.1')
            DataDirectory = 'C:\example\active-data'; CertificatePath = 'C:\example\tls\original.pfx'; CertificatePasswordFile = 'C:\example\tls\original-password' }
        $raw | ConvertTo-Json | Set-Content $script:SourceFile
        $raw.ServiceName = 'AuthLens'; $raw.DataDirectory = 'C:\ProgramData\AuthLens\data'
        $raw | ConvertTo-Json | Set-Content $script:TargetFile
        $script:Source = Read-AuthLensSettings $script:SourceFile
        $script:Target = Read-AuthLensSettings $script:TargetFile
    }
}

Describe 'Canonical Windows target naming' {
    BeforeEach { New-NamingFixture }
    It 'plans the canonical name and paths without writing either existing configuration' {
        $before = @($script:SourceFile, $script:TargetFile | ForEach-Object { (Get-FileHash $_).Hash })
        $plan = Get-SL2CanonicalTargetPlan $script:Source $script:Target
        $plan.configuration_written | Should -BeFalse
        $plan.proposed_config.ServiceName | Should -BeExactly 'sap-lens'
        $plan.proposed_config.ServiceAccount | Should -BeExactly 'LocalSystem'
        ($plan.proposed_config.WorkRoot, $plan.proposed_config.ReleasesRoot, $plan.proposed_config.DataDirectory, $plan.proposed_config.BackupRoot) |
            Should -Be @('C:\sap-lens\deploy', 'C:\sap-lens\releases', 'C:\ProgramData\sap-lens\data', 'C:\ProgramData\sap-lens\predeploy-backups')
        $plan.proposed_config.CertificatePath | Should -Be 'C:\ProgramData\sap-lens\tls\original.pfx'
        $plan.proposed_config.CertificatePasswordFile | Should -Be 'C:\ProgramData\sap-lens\tls\original-password'
        @($script:SourceFile, $script:TargetFile | ForEach-Object { (Get-FileHash $_).Hash }) | Should -Be $before
        ($plan.proposed_config.ListenAddress, $plan.proposed_config.Port) | Should -Be @($script:Source.ListenAddress, $script:Source.Port)
        $plan.proposed_config.AllowedHosts | Should -Be $script:Source.AllowedHosts
        $plan.proposed_config.TrustedProxies | Should -Be $script:Source.TrustedProxies
    }
    It 'is idempotent for a reviewed canonical configuration and maps virtual accounts explicitly' {
        $script:Source.ServiceAccount = 'NT SERVICE\SapLens2'
        $plan = Get-SL2CanonicalTargetPlan $script:Source $script:Target
        $plan.proposed_config.ServiceAccount | Should -Be 'NT SERVICE\sap-lens'
        $file = Join-Path $TestDrive 'canonical.json'
        $plan.proposed_config | ConvertTo-Json | Set-Content $file
        @( (Get-SL2CanonicalTargetPlan $script:Source (Read-AuthLensSettings $file)).changes ).Count | Should -Be 0
    }
    It 'rejects a noncanonical production target before migration' {
        { Assert-SL2MigrationPair $script:Source $script:Target } | Should -Throw '*SapLens2/sap-lens*'
        $script:Target.ServiceName = 'sap-lens'
        { Assert-SL2CanonicalTargetLayout $script:Target } | Should -Throw '*Canonical target*'
        $plan = Get-SL2CanonicalTargetPlan $script:Source $script:Target
        { Assert-SL2CanonicalTargetLayout $plan.proposed_config } | Should -Not -Throw
    }
    It 'retains legacy source defaults and uses canonical defaults for a new canonical configuration' {
        $script:Source.WorkRoot | Should -Be (Join-Path $TestDrive 'deploy')
        @{ RepositoryPath = 'C:\example\repo'; ServiceName = 'sap-lens'; ListenAddress = '192.0.2.10'; Port = 18795 } | ConvertTo-Json | Set-Content $script:TargetFile
        $config = Read-AuthLensSettings $script:TargetFile
        $config.WorkRoot | Should -Be 'C:\sap-lens\deploy'
        $config.DataDirectory | Should -Be 'C:\ProgramData\sap-lens\data'
        $config.ServiceAccount | Should -Be 'NT SERVICE\sap-lens'
    }
    It 'recognizes both historical service aliases as conflicts' -ForEach @(@{ Alias = 'AuthLens' }, @{ Alias = 'SapLens2' }) {
        Mock -ModuleName AuthLens.Deploy Get-SL2Service { param($Name) [pscustomobject]@{ Exists = ($Name -eq $Alias) } }
        Get-SL2OtherService ([pscustomobject]@{ ServiceName = 'sap-lens' }) | Should -Be $Alias
    }
    It 'keeps the server installer root and all service conflict aliases explicit' {
        $text = Get-Content (Join-Path $PSScriptRoot '../../installer/AuthLens-Server.iss') -Raw
        $text | Should -Match 'DefaultDirName=C:\\sap-lens'
        $text | Should -Match "Result\[0\] := 'sap-lens'"
        $text | Should -Match "Result\[1\] := 'AuthLens'"
        $text | Should -Match "Result\[2\] := 'SapLens2'"
    }
}
