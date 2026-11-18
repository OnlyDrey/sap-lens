# Isolated synthetic files and mocked SCM/network/ACL operations only. Never queries a host service.
BeforeAll {
    Import-Module (Join-Path $PSScriptRoot '../deploy/SapLens.Deploy.psm1') -Force
    $script:M = 'SapLens.Deploy'
    function New-MigrationFixture {
        $root = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        $old = Join-Path $root 'old'; $new = Join-Path $root 'new'
        foreach ($name in 'data', 'tls', 'backup', 'history', 'work', 'releases/release/server') { New-Item -ItemType Directory -Force (Join-Path $old $name) | Out-Null }
        foreach ($name in 'tls/server.pfx', 'tls/password', 'backup/host.key', 'data/saplens.sqlite3', 'releases/release/server/SapLens.Api.exe') { Set-Content -LiteralPath (Join-Path $old $name) 'synthetic' }
        @{ path = (Join-Path $old 'backup/host.key') } | ConvertTo-Json | Set-Content (Join-Path $old 'data/backup-key-location.json')
        @{ source_sha = ('a' * 40); version = '2.0.0-alpha.1'; source_dirty = $false } | ConvertTo-Json | Set-Content (Join-Path $old 'releases/release/build-manifest.json')
        $script:Source = [pscustomobject]@{ ServiceName = 'SapLens2'; ServiceAccount = 'LocalSystem'; ConfigFile = (Join-Path $root 'source.json'); RepositoryPath = $root
            WorkRoot = (Join-Path $old 'work'); ReleasesRoot = (Join-Path $old 'releases'); BackupRoot = (Join-Path $old 'history'); DataDirectory = (Join-Path $old 'data')
            CertificatePath = (Join-Path $old 'tls/server.pfx'); CertificatePasswordFile = (Join-Path $old 'tls/password'); ListenAddress = '192.0.2.10'; Port = 18795
            AllowedHosts = @('lens.example.com'); TrustedProxies = @('192.0.2.1'); StopTimeoutSeconds = 1; ReadyTimeoutSeconds = 1 }
        $script:Target = $script:Source.PSObject.Copy()
        foreach ($p in 'WorkRoot', 'ReleasesRoot', 'BackupRoot', 'DataDirectory', 'CertificatePath', 'CertificatePasswordFile') { $script:Target.$p = $script:Source.$p.Replace($old, $new) }
        $script:Target.ServiceName = 'SapLens'; $script:Target.ConfigFile = Join-Path $root 'target.json'
        $script:Source | ConvertTo-Json | Set-Content $script:Source.ConfigFile
        $script:Target | ConvertTo-Json | Set-Content $script:Target.ConfigFile
        $script:Inspector = Join-Path $old 'releases/release/server/SapLens.Api.exe'
        $script:Services = @{ SapLens2 = [pscustomobject]@{ Exists = $true; State = 'Running'; Account = 'LocalSystem'; StartMode = 'Auto'; ProcessId = 42
            PathName = ('"' + $script:Inspector + '" ' + ((Get-SL2ServiceArguments $script:Source | ForEach-Object { '"' + $_ + '"' }) -join ' ')) } }
        $script:Mutations = [Collections.Generic.List[string]]::new()
        Mock -ModuleName $M Get-SL2Service { param($Name) if ($script:Services.ContainsKey($Name)) { $script:Services[$Name] } else { [pscustomobject]@{ Exists = $false; State = 'Missing'; ProcessId = 0 } } }
        Mock -ModuleName $M Get-SL2Listener { foreach ($svc in $script:Services.Values) { if ($svc.State -eq 'Running') { $svc.ProcessId } } }
        Mock -ModuleName $M Get-SL2Link { '' }
        Mock -ModuleName $M Get-SL2MigrationAcl { 'synthetic-DACL' }
        Mock -ModuleName $M Get-SL2FreeSpace { 100GB }
        Mock -ModuleName $M Invoke-SL2Process { [pscustomobject]@{ ExitCode = 0; Output = @() } }
        Mock -ModuleName $M Invoke-SL2Maintenance {
            param($ExePath, $Arguments)
            switch ($Arguments[0]) {
                '--inspect-data' { [pscustomobject]@{ ok = $true; databases = @('synthetic'); schema = @{ compatible = $true; applied = @('m1') } } }
                '--schema-info' { [pscustomobject]@{ database_exists = $false; compatible = $true; pending = @('m1'); applied = @(); known = @('m1') } }
            }
        }
        Mock -ModuleName $M Stop-SL2Service { throw 'Preflight may never stop a service' }
        Mock -ModuleName $M Start-SL2Service { throw 'Preflight may never start a service' }
        Mock -ModuleName $M Set-SL2ServiceEntry { throw 'Preflight may never create a service' }
        Mock -ModuleName $M Write-SL2Journal { throw 'Preflight may never write a journal' }
    }
}

Describe 'Read-only identity and directory migration preflight' {
    BeforeEach { New-MigrationFixture }
    It 'checks all prerequisites without writing installation files or controlling services' {
        $before = @(Get-ChildItem (Split-Path $script:Source.ConfigFile) -Recurse -Force | ForEach-Object FullName)
        $result = Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector
        $result.safe | Should -BeTrue
        $result.checks.Count | Should -Be 7
        @(Get-ChildItem (Split-Path $script:Source.ConfigFile) -Recurse -Force | ForEach-Object FullName) | Should -Be $before
        Should -Invoke -ModuleName $M Stop-SL2Service -Times 0
        Should -Invoke -ModuleName $M Write-SL2Journal -Times 0
    }
    It 'blocks an existing canonical service including v1 without adopting it' {
        $script:Services.SapLens = $script:Services.SapLens2.PSObject.Copy()
        $result = Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector
        $result.safe | Should -BeFalse
        ($result.checks | Where-Object name -eq 'service_conflicts').message | Should -Match 'already exists'
    }
    It 'blocks network changes, unsafe targets, and insufficient capacity independently' {
        $script:Target.Port = 443
        $script:Target.DataDirectory = $script:Source.DataDirectory
        $result = Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector
        @($result.checks | Where-Object { -not $_.passed }).Count | Should -Be 2
        $script:Target.DataDirectory = Join-Path (Split-Path $script:Target.WorkRoot) 'data'
        Mock -ModuleName $M Get-SL2FreeSpace { 0 }
        (Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector).safe | Should -BeFalse
    }
    It 'reports integrity and pending-migration failures as blocking conditions' {
        Mock -ModuleName $M Invoke-SL2Maintenance { param($ExePath, $Arguments) if ($Arguments[0] -eq '--inspect-data') { @{ ok = $false } } else { @{ database_exists = $true; compatible = $true; pending = @('future') } } }
        $result = Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector
        @($result.checks | Where-Object { -not $_.passed }).name | Should -Contain 'sqlite_consistency'
    }
    It 'blocks a previous migration journal and does not overwrite retained staging' {
        Set-Content (Join-Path $script:Source.WorkRoot 'migration-journal.json') '{}'
        New-Item -ItemType Directory -Path $script:Target.DataDirectory -Force | Out-Null
        $result = Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector
        @($result.checks | Where-Object { -not $_.passed }).name | Should -Contain 'recovery_state'
        @($result.checks | Where-Object { -not $_.passed }).name | Should -Contain 'targets_and_capacity'
    }
    It 'rejects source path aliases and source service argument drift' {
        $script:Services.SapLens2.PathName += ' --unexpected-option x'
        (Get-SL2MigrationPreflight $script:Source $script:Target $script:Inspector).safe | Should -BeFalse
        (Test-SL2PathOverlap 'C:\old\data' 'C:\old\data\child') | Should -BeTrue
        (Test-SL2PathOverlap 'C:\old\data' 'C:\old\database') | Should -BeFalse
    }
}
