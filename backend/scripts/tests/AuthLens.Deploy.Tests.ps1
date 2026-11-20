# Pester 5 tests of the AuthLens Windows deployment state machine (scripts/deploy/AuthLens.Deploy.psm1). Every operating-system action (service
# control, the release link, HTTP, git, the server's maintenance commands) is mocked; folders live in TestDrive. Nothing is installed or started.
BeforeAll {
    . (Join-Path $PSScriptRoot 'TestHelpers.ps1')
    $script:ModulePath = (Resolve-Path (Join-Path $PSScriptRoot '..\deploy\AuthLens.Deploy.psm1')).Path
    $script:EntryPath = (Resolve-Path (Join-Path $PSScriptRoot '..\deploy\Deploy-AuthLens.ps1')).Path
    Import-TestDeploymentModule
    $script:M = 'AuthLens.Deploy'
    $script:Original = ''
    # Windows-only cmdlets the module calls; stubs let Pester mock them on Linux (on Windows the real commands exist and are mocked directly).
    foreach ($name in 'New-Service', 'Stop-Service', 'Start-Service', 'Get-NetTCPConnection') {
        if (-not (Get-Command $name -ErrorAction SilentlyContinue)) { New-Item -Path "function:global:$name" -Value { throw "stub $($MyInvocation.MyCommand.Name)" } | Out-Null }
    }
    # New-Service's stub carries the cmdlet's parameters, so mocks can filter on -Name and -DisplayName on Linux as on Windows.
    if (-not (Get-Command New-Service -CommandType Cmdlet -ErrorAction SilentlyContinue)) {
        New-Item -Path 'function:global:New-Service' -Force -Value { param([string]$Name, [string]$DisplayName, [string]$BinaryPathName, [string]$StartupType, [string]$Description) throw 'stub New-Service' } | Out-Null
    }
    $script:Old = 'a' * 40; $script:New = 'b' * 40
    $script:Missing = [pscustomobject]@{ Exists = $false; State = 'Missing'; StartMode = ''; Account = ''; PathName = ''; ProcessId = 0 }
    # No real service is ever queried, also on Windows (where the host may run AuthLens or SapLens2): tests decide which services exist.
    Mock -ModuleName $M Get-ALService { $script:Missing }

    function New-TestConfig {
        $root = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        foreach ($d in 'repo', 'work', 'releases', 'backups', 'data', 'tls') { New-Item -ItemType Directory -Force (Join-Path $root $d) | Out-Null }
        Set-Content (Join-Path $root 'tls/server.pfx') 'x'; Set-Content (Join-Path $root 'tls/cert-password') 'x'
        $json = [ordered]@{ RepositoryPath = (Join-Path $root 'repo'); WorkRoot = (Join-Path $root 'work'); ReleasesRoot = (Join-Path $root 'releases')
            BackupRoot = (Join-Path $root 'backups'); ListenAddress = '192.168.10.20'; Port = 18795; AllowedHosts = @('lens.example.com', '192.168.10.20')
            TrustedProxies = @('192.168.10.10'); DataDirectory = (Join-Path $root 'data'); CertificatePath = (Join-Path $root 'tls/server.pfx')
            CertificatePasswordFile = (Join-Path $root 'tls/cert-password'); ReadyTimeoutSeconds = 5; StopTimeoutSeconds = 3 }
        $file = Join-Path $root 'deploy.json'
        $json | ConvertTo-Json | Set-Content $file
        Read-AuthLensSettings $file
    }

    function New-TestRelease($Config, [string]$Name, [string]$Sha, [string]$Version = '2.0.0-alpha.1') {
        $folder = Join-Path $Config.ReleasesRoot $Name
        New-Item -ItemType Directory -Force (Join-Path $folder 'server') | Out-Null
        @{ source_sha = $Sha; version = $Version; source_dirty = $false } | ConvertTo-Json | Set-Content (Join-Path $folder 'build-manifest.json')
        $folder
    }

    # A fake host: service, link and HTTP state shared by the mocks; every action is appended to $script:Calls in order.
    function Use-FakeHost($Config, [string]$Previous, [hashtable]$Options = @{}) {
        $script:Calls = [System.Collections.Generic.List[string]]::new()
        $script:State = @{ Service = 'Running'; Pid = 4242; Link = $Previous; Identity = @{ $Previous = $script:Old }; Options = $Options; Applied = @('m1') }
        $script:Expected = Get-ALBinaryPath $Config
        $script:State.ServiceName = $Config.ServiceName
        Mock -ModuleName $M Get-ALService { param($Name) if ($Name -ne $script:State.ServiceName) { return $script:Missing }
            [pscustomobject]@{ Exists = $true; State = $script:State.Service; StartMode = 'Auto'; Account = "NT SERVICE\$Name"
            PathName = $script:Expected; ProcessId = $(if ($script:State.Service -eq 'Running') { $script:State.Pid } else { 0 }) } }
        Mock -ModuleName $M Stop-ALService { $script:Calls.Add('stop'); if ($script:State.Options.StopTimeout) { Stop-AL 'Service did not stop within 3 s. It was not killed.' 4 }; $script:State.Service = 'Stopped' }
        Mock -ModuleName $M Start-ALService { $script:Calls.Add('start:' + (Split-Path $script:State.Link -Leaf)); $script:State.Service = 'Running'; $script:State.Pid++ }
        Mock -ModuleName $M Get-ALLink { $script:State.Link }
        Mock -ModuleName $M Set-ALLink { param($Link, $Target) $script:Calls.Add('link:' + (Split-Path $Target -Leaf)); $script:State.Link = $Target }
        # Like the real function after PowerShell unrolls its result: one listener comes back as a bare [int], none as nothing.
        Mock -ModuleName $M Get-ALListener { if ($script:State.Service -eq 'Running') { $script:State.Pid } }
        Mock -ModuleName $M Set-ALServiceBinary { param($Name, $BinaryPath) $script:Calls.Add('binary:' + $(if ($BinaryPath -eq (Get-ALBinaryPath $Config)) { 'managed' } else { 'original' })); $script:Expected = $BinaryPath }
        Mock -ModuleName $M Start-Sleep { }
        Mock -ModuleName $M Stop-Process { throw 'Stop-Process must never be called' }
        Mock -ModuleName $M Invoke-ALHttp {
            param($Url)
            if ($Url -like '*/health/ready') { return [pscustomobject]@{ Status = $(if ($script:State.Options.NeverReady -and $script:State.Link -like '*new*') { 503 } else { 200 }); Body = '' } }
            $sha = $script:State.Identity[$script:State.Link]
            if ($script:State.Options.WrongIdentity -and $script:State.Link -like '*new*') { $sha = 'c' * 40 }
            # An adopted service running its original command line answers as the release it ran before.
            if ($script:Original -and $script:Expected -eq $script:Original) { $sha = $script:Old }
            [pscustomobject]@{ Status = 200; Body = (@{ source_sha = $sha; version = '2.0.0-alpha.1' } | ConvertTo-Json) }
        }
        Mock -ModuleName $M Invoke-ALMaintenance {
            param($ExePath, $Arguments, [switch]$AllowUnsupported)
            switch ($Arguments[0]) {
                '--schema-info' {
                    $script:Calls.Add('schema:' + (Split-Path (Split-Path (Split-Path $ExePath)) -Leaf))
                    if ($script:State.Options.OldBuildUnsupported -and $ExePath -like '*old*') { return $null }
                    $compatible = -not ($script:State.Options.NewerData -or ($script:State.Options.PreviousIncompatible -and $ExePath -like '*old*'))
                    return [pscustomobject]@{ compatible = $compatible; database_exists = $true; applied = $script:State.Applied; pending = $(if ($script:State.Options.PendingMigration -and $ExePath -like '*new*') { @('m2') } else { @() }); unknown_applied = $(if ($compatible) { @() } else { @('m9') }) }
                }
                '--backup-local' { $script:Calls.Add('backup'); return [pscustomobject]@{ file = (Join-Path $Arguments[1] 'pre.slbak'); sha256 = 'd' * 64; size = 10 } }
                '--backup-verify' { $script:Calls.Add('verify'); return [pscustomobject]@{ verified = -not $script:State.Options.BackupBroken; sha256 = 'd' * 64 } }
            }
        }
    }

    function Invoke-Deploy($Config, $Release) {
        $null = New-ALRun $Config 'deploy'
        try { Invoke-ALDeploy $Config $Release $script:New | Out-Null; 0 } catch { if ($_.Exception.PSObject.Properties["ExitCode"]) { $_.Exception.ExitCode } else { throw } }
    }
}

Describe 'Configuration' {
    It 'derives every application-managed path from one installation root, which an explicit setting overrides path by path' {
        $template = Get-Content (Join-Path $PSScriptRoot '../deploy/deploy.example.json') -Raw | ConvertFrom-Json
        $template.Root | Should -Be 'C:\ProgramData\AuthLens'
        @($template.PSObject.Properties.Name | Where-Object { $_ -in 'WorkRoot', 'ReleasesRoot', 'BackupRoot', 'DataDirectory', 'ServiceName' }) | Should -BeNullOrEmpty
        $file = Join-Path $TestDrive 'layout.json'
        @{ RepositoryPath = 'C:\src\sap-lens'; ListenAddress = '192.0.2.10'; Port = 18795 } | ConvertTo-Json | Set-Content $file
        $config = Read-AuthLensSettings $file
        function Under([string[]]$Parts) { $path = 'C:\ProgramData\AuthLens'; foreach ($part in $Parts) { $path = [IO.Path]::Combine($path, $part) }; $path }   # the platform's separator
        ($config.Root, $config.ReleasesRoot, $config.DataDirectory, $config.WorkRoot, $config.BackupRoot, $config.CertificatePath, $config.CertificatePasswordFile) | Should -Be @(
            'C:\ProgramData\AuthLens', (Under 'releases'), (Under 'data'), (Under 'deployment'), (Under 'backups', 'predeploy'), (Under 'tls', 'server.pfx'), (Under 'tls', 'cert-password'))
        @{ Root = 'D:\AuthLens'; RepositoryPath = 'C:\src\sap-lens'; ListenAddress = '192.0.2.10'; Port = 18795; DataDirectory = 'E:\AuthLensData' } | ConvertTo-Json | Set-Content $file
        $config = Read-AuthLensSettings $file
        ($config.ReleasesRoot, $config.DataDirectory) | Should -Be @([IO.Path]::Combine('D:\AuthLens', 'releases'), 'E:\AuthLensData')
    }
    It 'refuses unknown settings, missing values and relative paths' {
        $file = Join-Path $TestDrive 'bad.json'
        @{ RepositoryPath = 'C:\r'; Typo = 1 } | ConvertTo-Json | Set-Content $file
        { Read-AuthLensSettings $file } | Should -Throw '*Unknown deployment setting*'
        @{ RepositoryPath = 'relative\repo'; ListenAddress = '10.0.0.1'; Port = 1; DataDirectory = 'C:\d'; CertificatePath = 'C:\c'; CertificatePasswordFile = 'C:\p' } | ConvertTo-Json | Set-Content $file
        { Read-AuthLensSettings $file } | Should -Throw '*absolute path*'
    }

    It 'builds the service command line from the configuration with TLS, hosts and trusted proxies and no secret' {
        $config = New-TestConfig
        $binary = Get-ALBinaryPath $config
        $binary | Should -Match '--network --listen 192.168.10.20 --port 18795'
        $binary | Should -Match '--allowed-hosts lens.example.com,192.168.10.20'
        $binary | Should -Match '--trusted-proxies 192.168.10.10'
        $binary | Should -Match '--cert-password-file'
        $binary | Should -Not -Match '--cert-password '
    }

    It 'names the service AuthLens and never selects a service of an earlier product' {
        $config = New-TestConfig
        ($config.ServiceName, $config.ServiceAccount, $config.ServiceNameConfigured) | Should -Be @('AuthLens', 'NT SERVICE\AuthLens', $false)
        Mock -ModuleName $M Get-ALService { param($Name) if ($Name -in 'SapLens2', 'sap-lens', 'SapLens') { [pscustomobject]@{ Exists = $true; State = 'Running' } } else { $script:Missing } }
        (Read-AuthLensSettings $config.ConfigFile).ServiceName | Should -Be 'AuthLens'
        Should -Invoke -ModuleName $M Get-ALService -Times 0                                    # earlier services are not even looked up
    }

    It 'reads the configuration from -ConfigFile, AUTHLENS_DEPLOY_CONFIG or the root, never from an earlier product location' {
        $config = New-TestConfig
        $saved = $env:AUTHLENS_DEPLOY_CONFIG, $env:SAPLENS_DEPLOY_CONFIG, $env:SAPLENS2_DEPLOY_CONFIG
        try {
            $env:AUTHLENS_DEPLOY_CONFIG = $null; $env:SAPLENS_DEPLOY_CONFIG = $config.ConfigFile; $env:SAPLENS2_DEPLOY_CONFIG = $config.ConfigFile
            { Read-AuthLensSettings '' } | Should -Throw '*C:\ProgramData\AuthLens\config\deploy.json*'
            $env:AUTHLENS_DEPLOY_CONFIG = $config.ConfigFile
            (Read-AuthLensSettings '').ConfigFile | Should -Be $config.ConfigFile
        } finally { $env:AUTHLENS_DEPLOY_CONFIG, $env:SAPLENS_DEPLOY_CONFIG, $env:SAPLENS2_DEPLOY_CONFIG = $saved }
    }

    It 'maps the test selections to the build filter' {
        Get-ALTestFilter 'full' | Should -Be ''
        $null -eq (Get-ALTestFilter 'none') | Should -BeTrue
        Get-ALTestFilter 'focused' | Should -Match 'FullyQualifiedName~AuthLens.Tests.V1DataMigrationTests'
        { Get-ALTestFilter 'some' } | Should -Throw
    }
}

Describe 'Source' {
    It 'never builds main or work and only deploys pushed commits of the branch' {
        $config = New-TestConfig
        { Resolve-ALCommit $config 'main' '' } | Should -Throw '*not ''main''*'
        # A single output line arrives as a plain string (the shape that broke Windows PowerShell 5.1 with "[System.Char] ... 'Trim'").
        Mock -ModuleName $M Invoke-ALGit { param($Repository, $Arguments) if ($Arguments[0] -eq 'rev-parse') { "$('e' * 40)`n" } }
        Mock -ModuleName $M Invoke-ALProcess { [pscustomobject]@{ ExitCode = 1; Output = @() } }
        { Resolve-ALCommit $config 'experiment/dotnet-backend' ('f' * 40) } | Should -Throw '*only pushed commits*'
        Resolve-ALCommit $config 'experiment/dotnet-backend' '' | Should -Be ('e' * 40)
    }

    It 'finds the .NET project under backend and, for commits from before the promotion, under experiments\dotnet-backend' {
        $tree = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force (Join-Path $tree 'backend'), (Join-Path $tree 'experiments/dotnet-backend') | Out-Null
        Set-Content (Join-Path $tree 'backend/requirements.txt') 'python backend'
        { Get-ALProjectRoot $tree } | Should -Throw '*No .NET project*'
        Set-Content (Join-Path $tree 'experiments/dotnet-backend/AuthLens.slnx') '<Solution />'
        Get-ALProjectRoot $tree | Should -Be ([System.IO.Path]::Combine($tree, 'experiments/dotnet-backend'))
        Remove-Item -Recurse (Join-Path $tree 'experiments')
        Set-Content (Join-Path $tree 'backend/AuthLens.slnx') '<Solution />'
        Get-ALProjectRoot $tree | Should -Be ([System.IO.Path]::Combine($tree, 'backend'))
    }

    It 'refuses to reuse a modified build worktree' {
        $config = New-TestConfig
        $worktree = Join-Path (Join-Path $config.WorkRoot 'worktrees') ('b' * 12)
        New-Item -ItemType Directory -Force $worktree | Out-Null
        Mock -ModuleName $M Invoke-ALGit { param($Repository, $Arguments) if ($Arguments[0] -eq 'rev-parse') { 'b' * 40 } else { ' M file.cs' } }
        { New-ALWorktree $config ('b' * 40) } | Should -Throw '*not a clean checkout*'
    }
}

Describe 'Deployment' {
    BeforeEach {
        $script:Config = New-TestConfig
        $script:Previous = New-TestRelease $script:Config 'old' $script:Old
        $script:Target = New-TestRelease $script:Config 'new' $script:New
    }

    It 'backs up and verifies before stopping, switches, starts and keeps the release when it is ready with the right identity' {
        Use-FakeHost $script:Config $script:Previous
        $script:State.Identity[$script:Target] = $script:New
        Invoke-Deploy $script:Config $script:Target | Should -Be 0
        ($script:Calls -join ' ') | Should -Be 'schema:new backup verify stop link:new start:new'
        (Read-ALJournal $script:Config).phase | Should -Be 'complete'
        (Read-ALJournal $script:Config).backup.sha256 | Should -Be ('d' * 64)
    }
    It 'requires a verified previous release and compatible schema before an installer may stop a service' {
        Use-FakeHost $script:Config $script:Previous
        Mock -ModuleName $M Test-ALPublishedRelease { [pscustomobject]@{Verified=$false} }
        { Invoke-ALDeploy $script:Config $script:Target $script:New -RequireRollback } | Should -Throw '*previous managed release must verify*'
        $script:Calls | Should -Not -Contain 'stop'
        Mock -ModuleName $M Test-ALPublishedRelease { [pscustomobject]@{Verified=$true} }
        Use-FakeHost $script:Config $script:Previous @{PendingMigration=$true}
        { Invoke-ALDeploy $script:Config $script:Target $script:New -RequireRollback } | Should -Throw '*cannot prove binary rollback*'
        $script:Calls | Should -Not -Contain 'stop'
        $script:Calls | Should -Not -Contain 'backup'
    }
    It 'uses the previous release backup engine and the unchanged service identity during installer updates' {
        Use-FakeHost $script:Config $script:Previous
        $script:State.Identity[$script:Target]=$script:New
        Mock -ModuleName $M Test-ALPublishedRelease { [pscustomobject]@{Verified=$true} }
        $null=New-ALRun $script:Config 'installer'
        Invoke-ALDeploy $script:Config $script:Target $script:New -RequireRollback
        (Read-ALJournal $script:Config).phase | Should -Be 'complete'
        Should -Invoke -ModuleName $M Invoke-ALMaintenance -Times 1 -ParameterFilter { $Arguments[0] -eq '--backup-local' -and $ExePath -like '*old*' }
        $script:Calls | Should -Not -Contain 'binary:managed'
    }

    It 'stops nothing when the data was written by a newer build, the backup cannot be verified, or an earlier run was interrupted' {
        Use-FakeHost $script:Config $script:Previous @{ NewerData = $true }
        Invoke-Deploy $script:Config $script:Target | Should -Be 2
        $script:Calls | Should -Not -Contain 'stop'

        Use-FakeHost $script:Config $script:Previous @{ BackupBroken = $true }
        Invoke-Deploy $script:Config $script:Target | Should -Be 1
        $script:Calls | Should -Not -Contain 'stop'

        Write-ALJournal $script:Config ([pscustomobject]@{ run = 'earlier'; phase = 'switched'; history = @(); updated = '' })
        Use-FakeHost $script:Config $script:Previous
        Invoke-Deploy $script:Config $script:Target | Should -Be 2
        $script:Calls | Should -Not -Contain 'stop'
    }

    It 'refuses when the service command line differs from the configuration' {
        Use-FakeHost $script:Config $script:Previous
        $script:Expected = 'something else'
        Invoke-Deploy $script:Config $script:Target | Should -Be 2
        $script:Calls | Should -Not -Contain 'stop'
    }

    It 'rolls back to the previous release when the new one answers with the wrong identity' {
        Use-FakeHost $script:Config $script:Previous @{ WrongIdentity = $true }
        $script:State.Identity[$script:Target] = $script:New
        Invoke-Deploy $script:Config $script:Target | Should -Be 1
        ($script:Calls -join ' ') | Should -Be 'schema:new backup verify stop link:new start:new stop schema:old link:old start:old'
        (Read-ALJournal $script:Config).phase | Should -Be 'rolled_back'
        $script:State.Link | Should -Be $script:Previous
    }

    It 'rolls back after a timeout when the new release never becomes ready' {
        Use-FakeHost $script:Config $script:Previous @{ NeverReady = $true }
        $script:State.Identity[$script:Target] = $script:New
        Invoke-Deploy $script:Config $script:Target | Should -Be 1
        $script:State.Link | Should -Be $script:Previous
        (Read-ALJournal $script:Config).phase | Should -Be 'rolled_back'
    }

    It 'never returns to a release that cannot open the data, and leaves exact recovery instructions' {
        Use-FakeHost $script:Config $script:Previous @{ WrongIdentity = $true; PreviousIncompatible = $true }
        $script:State.Identity[$script:Target] = $script:New
        Invoke-Deploy $script:Config $script:Target | Should -Be 4
        $script:State.Link | Should -Be $script:Target                                  # not switched back
        $script:Calls | Should -Not -Contain 'start:old'
        (Read-ALJournal $script:Config).phase | Should -Be 'manual_recovery_required'
        $note = Get-ChildItem -Recurse (Join-Path $script:Config.WorkRoot 'runs') -Filter RECOVERY-REQUIRED.txt | Select-Object -First 1
        Get-Content $note.FullName -Raw | Should -Match 'Pre-deployment backup'
    }

    It 'proves rollback safety for an older build without --schema-info by the applied migrations' {
        Use-FakeHost $script:Config $script:Previous @{ WrongIdentity = $true; OldBuildUnsupported = $true }
        $script:State.Identity[$script:Target] = $script:New
        Invoke-Deploy $script:Config $script:Target | Should -Be 1                        # nothing applied meanwhile: safe
        $script:State.Link | Should -Be $script:Previous

        Use-FakeHost $script:Config $script:Previous @{ WrongIdentity = $true; OldBuildUnsupported = $true }
        $script:State.Identity[$script:Target] = $script:New
        Mock -ModuleName $M Start-ALService { $script:Calls.Add('start'); $script:State.Service = 'Running'; $script:State.Pid++; $script:State.Applied = @('m1', 'm2') }
        Invoke-Deploy $script:Config $script:Target | Should -Be 4                        # the new release migrated the database: unsafe
        (Read-ALJournal $script:Config).phase | Should -Be 'manual_recovery_required'
    }

    It 'does not kill a service that does not stop' {
        Use-FakeHost $script:Config $script:Previous @{ StopTimeout = $true }
        Invoke-Deploy $script:Config $script:Target | Should -Be 4
        Should -Invoke -ModuleName $M Stop-Process -Times 0
    }

    It 'previews without backup or service change in a dry run' {
        Use-FakeHost $script:Config $script:Previous
        $null = New-ALRun $script:Config 'deploy'
        $result = Invoke-ALDeploy $script:Config $script:Target $script:New -DryRun
        $result.dry_run | Should -BeTrue
        ($script:Calls -join ' ') | Should -Be 'schema:new'
    }
}

Describe 'Recovery and rollback' {
    BeforeEach {
        $script:Config = New-TestConfig
        $script:Previous = New-TestRelease $script:Config 'old' $script:Old
        $script:Target = New-TestRelease $script:Config 'new' $script:New
    }

    It 'returns an interrupted deployment to the previous release' {
        Use-FakeHost $script:Config $script:Target
        $script:State.Identity[$script:Previous] = $script:Old
        $script:State.Service = 'Stopped'
        Write-ALJournal $script:Config ([pscustomobject]@{ run = 'cut'; phase = 'switched'; from_release = $script:Previous; to_release = $script:Target; applied_before = @('m1')
            service_state_before = 'Running'; backup = $null; history = @(); updated = '' })
        $null = New-ALRun $script:Config 'recover'
        (Invoke-ALRecover $script:Config).phase | Should -Be 'rolled_back'
        $script:State.Link | Should -Be $script:Previous
        $script:State.Service | Should -Be 'Running'
    }

    It 'marks a run interrupted before the stop as aborted and restarts a service that was running' {
        Use-FakeHost $script:Config $script:Previous
        $script:State.Service = 'Stopped'
        Write-ALJournal $script:Config ([pscustomobject]@{ run = 'cut'; phase = 'backup'; from_release = $script:Previous; service_state_before = 'Running'; history = @(); updated = '' })
        $null = New-ALRun $script:Config 'recover'
        (Invoke-ALRecover $script:Config).phase | Should -Be 'aborted'
        $script:State.Service | Should -Be 'Running'
        $script:State.Link | Should -Be $script:Previous
    }

    It 'rolls back on request only when the previous release can open the data' {
        Use-FakeHost $script:Config $script:Target @{ PreviousIncompatible = $true }
        Write-ALJournal $script:Config ([pscustomobject]@{ run = 'done'; phase = 'complete'; from_release = $script:Previous; history = @(); updated = '' })
        $null = New-ALRun $script:Config 'rollback'
        { Invoke-ALRollback $script:Config '' } | Should -Throw '*not safe*'
        $script:State.Link | Should -Be $script:Target
    }
}

Describe 'Service installation and host safety' {
    It 'displays the AuthLens service as AuthLens and an isolated test service by its own name' {
        $config = New-TestConfig
        Mock -ModuleName $M New-Service { }
        Mock -ModuleName $M Invoke-ALProcess { @{ ExitCode = 0; Output = @() } }
        $config.ServiceName = 'AuthLens.Acceptance-' + ('a' * 32)
        Set-ALServiceEntry $config 'synthetic' $false 'demand'
        Should -Invoke -ModuleName $M New-Service -Times 1 -ParameterFilter { $Name -eq $DisplayName -and $Name -like 'AuthLens.Acceptance-*' }
        $config.ServiceName = 'AuthLens'
        Set-ALServiceEntry $config 'synthetic' $false 'demand'
        Should -Invoke -ModuleName $M New-Service -Times 1 -ParameterFilter { $Name -eq 'AuthLens' -and $DisplayName -eq 'AuthLens' }
        Should -Invoke -ModuleName $M Invoke-ALProcess -Times 1 -ParameterFilter {
            $File -eq 'sc.exe' -and $Arguments[1] -eq 'AuthLens' -and $Arguments -contains 'DisplayName=' -and $Arguments[-1] -eq 'AuthLens'
        }
    }
    It 'refuses to install while another process holds the port and never stops it' {
        $config = New-TestConfig
        $release = New-TestRelease $config 'new' $script:New
        Mock -ModuleName $M Get-ALService { [pscustomobject]@{ Exists = $false; State = 'Missing'; StartMode = ''; Account = ''; PathName = ''; ProcessId = 0 } }
        Mock -ModuleName $M Get-ALLink { $release }
        Mock -ModuleName $M Get-ALListener { 999 }
        Mock -ModuleName $M Stop-Process { throw 'never' }
        Mock -ModuleName $M New-Service { throw 'must not be created' }
        { Install-ALService $config } | Should -Throw '*used by process 999*'
        Should -Invoke -ModuleName $M Stop-Process -Times 0
    }

    It 'installs AuthLens beside a running SAP Lens service without looking at, stopping or changing it' {
        $config = New-TestConfig
        $release = New-TestRelease $config 'new' $script:New
        Mock -ModuleName $M Get-ALLink { $release }
        Mock -ModuleName $M Get-ALService { param($Name) if ($Name -in 'SapLens2', 'sap-lens', 'SapLens') { [pscustomobject]@{ Exists = $true; State = 'Running'; ProcessId = 7 } } else { $script:Missing } }
        Mock -ModuleName $M Get-ALListener { @() }
        Mock -ModuleName $M New-Service { }
        Mock -ModuleName $M Invoke-ALProcess { @{ ExitCode = 0; Output = @() } }
        Mock -ModuleName $M Stop-ALService { throw 'no service is stopped' }
        Install-ALService $config
        Should -Invoke -ModuleName $M New-Service -Times 1 -ParameterFilter { $Name -eq 'AuthLens' }
        Should -Invoke -ModuleName $M Get-ALService -Times 0 -ParameterFilter { $Name -in 'SapLens2', 'sap-lens', 'SapLens' }
        Should -Invoke -ModuleName $M Invoke-ALProcess -Times 0 -ParameterFilter { ($Arguments -join ' ') -match 'SapLens2|sap-lens\b' }
    }

    It 'reports an unmanaged server (for example the test launcher) as such' {
        $config = New-TestConfig
        Mock -ModuleName $M Get-ALService { [pscustomobject]@{ Exists = $false; State = 'Missing'; StartMode = ''; Account = ''; PathName = ''; ProcessId = 0 } }
        Mock -ModuleName $M Get-ALLink { '' }
        Mock -ModuleName $M Get-ALListener { 999 }
        Mock -ModuleName $M Invoke-ALHttp { [pscustomobject]@{ Status = 200; Body = '{"source_sha":"x","version":"2.0.0-alpha.1"}' } }
        (Get-ALStatus $config).service_model | Should -Be 'unmanaged-process'
    }

    It 'allows one deployment operation at a time' {
        $config = New-TestConfig
        Enter-ALLock $config
        try {
            $second = Start-Job -ScriptBlock { param($Module, $Work) Import-Module $Module; try { Enter-ALLock ([pscustomobject]@{ WorkRoot = $Work }); 'acquired' } catch { $_.Exception.Message } } -ArgumentList $script:ModulePath, $config.WorkRoot
            ($second | Wait-Job | Receive-Job) | Should -Match 'Another deployment operation is running'
        } finally { Exit-ALLock }
    }

    It 'requires -Yes for actions that change the service' {
        $config = New-TestConfig
        $file = Join-Path $TestDrive 'entry.json'
        $config | Select-Object * -ExcludeProperty ConfigFile, ServiceNameConfigured, ServiceName, ServiceAccount | ConvertTo-Json | Set-Content $file
        $run = Invoke-TestPowerShell @('-File', $script:EntryPath, '-Action', 'Deploy', '-ConfigFile', $file)
        $run.Code | Should -Be 2
        $run.Output | Should -Match 'repeat with -Yes'
        # Authorization is refused before config lookup or implicit host-service detection.
        $run = Invoke-TestPowerShell @('-File', $script:EntryPath, '-Action', 'Restore', '-ConfigFile', (Join-Path $TestDrive 'missing.json'))
        $run.Code | Should -Be 2
        $run.Output | Should -Match 'repeat with -Yes'
    }
}

Describe 'Windows PowerShell 5.1 regressions' {
    It 'reads a single git line that PowerShell returns as a plain string (the [System.Char] Trim failure)' {
        $config = New-TestConfig
        Mock -ModuleName $M Invoke-ALGit { "  $('c' * 40)  " }
        Get-ALGitValue $config.RepositoryPath @('rev-parse', 'HEAD') | Should -Be ('c' * 40)
        Mock -ModuleName $M Invoke-ALGit { 'one'; 'two' }
        { Get-ALGitValue $config.RepositoryPath @('rev-parse', 'HEAD') } | Should -Throw '*expected one*'
    }

    It 'keeps native commands from stopping on stderr and never reads $IsWindows unguarded' {
        $module = Get-Content $script:ModulePath -Raw
        foreach ($name in 'Invoke-ALGit', 'Invoke-ALProcess', 'Invoke-ALHttp') {
            $body = ([regex]::Match($module, "function $name\b[^{]*\{(?<b>[\s\S]*?)\n\}")).Groups['b'].Value
            $body | Should -Match "ErrorActionPreference = 'Continue'"
        }
        $module | Should -Not -Match '\)\[0\]\.Trim\(\)'
        (Get-Content $script:EntryPath -Raw) | Should -Not -Match '-not \$IsWindows'
    }

    It 'appends to a journal history read back from JSON with a single entry' {
        $config = New-TestConfig
        $null = New-ALRun $config 'recover'
        Write-ALJournal $config ([pscustomobject]@{ run = 'r'; phase = 'backup'; history = @(@{ phase = 'prepared'; at = 'x' }); updated = '' })
        $journal = Read-ALJournal $config
        Set-ALPhase $config $journal 'aborted'
        @((Read-ALJournal $config).history).Count | Should -Be 2
    }
}

Describe 'Adopting a hand-installed service' {
    AfterAll { $script:Original = '' }
    BeforeEach {
        $script:Config = New-TestConfig
        $script:Target = New-TestRelease $script:Config 'new' $script:New
        $script:Original = '"C:\saplens2\builds\manual\server\AuthLens.Api.exe" ' + ((Get-ALServiceArguments $script:Config | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' ')
    }

    It 'adopts only on request and only with the configured arguments' {
        Use-FakeHost $script:Config ''
        $script:Expected = $script:Original
        Invoke-Deploy $script:Config $script:Target | Should -Be 2                              # without -AdoptService
        $script:Calls | Should -Not -Contain 'stop'
        $script:Expected = $script:Original -replace '--port 18795', '--port 18796'
        $null = New-ALRun $script:Config 'deploy'
        { Invoke-ALDeploy $script:Config $script:Target $script:New -AdoptService } | Should -Throw '*arguments differ*'
        $script:Calls | Should -Not -Contain 'stop'
    }

    It 'adopts a service whose equivalent arguments are in another order, with host and proxy lists in another order' {
        Use-FakeHost $script:Config ''
        # The shape of a hand-installed service: options reordered, lists reordered, a different case in a path.
        $c = $script:Config
        $script:Expected = ('"C:\saplens2\builds\manual\server\AuthLens.Api.exe" --data-dir "{0}" --listen 192.168.10.20 --port 18795 --network ' +
            '--allowed-hosts 192.168.10.20,LENS.example.com --trusted-proxies 192.168.10.10 --cert "{1}" --cert-password-file "{2}"') -f $c.DataDirectory, $c.CertificatePath, $c.CertificatePasswordFile
        $script:Original = $script:Expected
        $script:State.Identity[$script:Target] = $script:New
        $null = New-ALRun $script:Config 'deploy'
        (Invoke-ALDeploy $script:Config $script:Target $script:New -AdoptService).deployed | Should -BeTrue
        ($script:Calls -join ' ') | Should -Be 'schema:new backup verify stop link:new binary:managed start:new'
        (Read-ALJournal $script:Config).service_binary_before | Should -Be $script:Original      # captured for rollback
    }

    It 'moves the service to the managed release link and keeps it there when ready' {
        Use-FakeHost $script:Config ''
        $script:Expected = $script:Original
        $script:State.Identity[$script:Target] = $script:New
        $null = New-ALRun $script:Config 'deploy'
        (Invoke-ALDeploy $script:Config $script:Target $script:New -AdoptService).deployed | Should -BeTrue
        ($script:Calls -join ' ') | Should -Be 'schema:new backup verify stop link:new binary:managed start:new'
    }

    It 'restores the original command line when the adopted deployment fails' {
        Use-FakeHost $script:Config '' @{ WrongIdentity = $true }
        $script:Expected = $script:Original
        $script:State.Identity[$script:Target] = $script:New
        $script:State.Identity[''] = $script:Old
        $null = New-ALRun $script:Config 'deploy'
        { Invoke-ALDeploy $script:Config $script:Target $script:New -AdoptService } | Should -Throw '*rolled back*'
        $script:Expected | Should -Be $script:Original
        $script:Calls | Should -Contain 'binary:original'
        (Read-ALJournal $script:Config).phase | Should -Be 'rolled_back'
    }
}

Describe 'Semantic comparison of service arguments' {
    BeforeAll {
        $script:Base = @('--data-dir', 'C:\ProgramData\sap-lens\data', '--network', '--listen', '192.0.2.10', '--port', '18795',
            '--allowed-hosts', 'lens.example.com,192.0.2.10', '--cert', 'C:\ProgramData\sap-lens\tls\server.pfx',
            '--cert-password-file', 'C:\ProgramData\sap-lens\tls\cert-password', '--trusted-proxies', '192.0.2.1,192.0.2.2')
        function Without([string[]]$Arguments, [string]$Name) {
            $out = New-Object System.Collections.Generic.List[string]
            for ($i = 0; $i -lt $Arguments.Count; $i++) { if ($Arguments[$i] -ceq $Name) { if ($Name -ne '--network') { $i++ }; continue }; $out.Add($Arguments[$i]) }
            , $out.ToArray()
        }
        function With([string[]]$Arguments, [string]$Name, [string]$Value) {
            $copy = [string[]]$Arguments.Clone(); $copy[[array]::IndexOf($copy, $Name) + 1] = $Value; , $copy
        }
    }

    It 'treats the same options in another order as equivalent' {
        $reordered = @('--listen', '192.0.2.10', '--port', '18795', '--network', '--trusted-proxies', '192.0.2.1,192.0.2.2', '--cert', 'C:\ProgramData\sap-lens\tls\server.pfx',
            '--allowed-hosts', 'lens.example.com,192.0.2.10', '--cert-password-file', 'C:\ProgramData\sap-lens\tls\cert-password', '--data-dir', 'C:\ProgramData\sap-lens\data')
        @(Compare-ALServiceArguments $reordered $script:Base).Count | Should -Be 0
    }

    It 'treats host and proxy lists as sets: order, spacing, host-name case and repeated entries do not matter' {
        $lists = With (With $script:Base '--allowed-hosts' ' 192.0.2.10 , LENS.EXAMPLE.COM,lens.example.com') '--trusted-proxies' '192.0.2.2,192.0.2.1'
        @(Compare-ALServiceArguments $lists $script:Base).Count | Should -Be 0
    }

    It 'reports every real difference in a security-sensitive value' {
        foreach ($case in @(
                @('--data-dir', 'C:\ProgramData\sap-lens\other'), @('--listen', '192.0.2.11'), @('--port', '18796'), @('--allowed-hosts', 'lens.example.com'),
                @('--allowed-hosts', 'lens.example.com,192.0.2.10,evil.example.net'), @('--trusted-proxies', '192.0.2.1'), @('--trusted-proxies', '192.0.2.1,192.0.2.3'),
                @('--cert', 'C:\ProgramData\sap-lens\tls\other.pfx'), @('--cert-password-file', 'C:\ProgramData\sap-lens\tls\other'), @('--port', '018795x'))) {
            $differences = @(Compare-ALServiceArguments (With $script:Base $case[0] $case[1]) $script:Base)
            $differences.Count | Should -Be 1 -Because "$($case[0]) $($case[1])"
            $differences[0] | Should -BeLike "$($case[0]) differs*"
        }
    }

    It 'reports a missing security-sensitive option on either side' {
        foreach ($name in '--data-dir', '--network', '--listen', '--port', '--allowed-hosts', '--trusted-proxies', '--cert', '--cert-password-file') {
            @(Compare-ALServiceArguments (Without $script:Base $name) $script:Base) | Should -Be "$name is missing on the service" -Because $name
            @(Compare-ALServiceArguments $script:Base (Without $script:Base $name)) | Should -Be "$name is on the service but not in the configuration" -Because $name
        }
    }

    It 'refuses repeated, conflicting, unknown and incomplete options instead of ignoring them' {
        @(Compare-ALServiceArguments ($script:Base + @('--port', '18795')) $script:Base) | Should -BeLike '*--port is given more than once*'
        @(Compare-ALServiceArguments ($script:Base + @('--port', '18796')) $script:Base) | Should -BeLike '*--port is given more than once*'
        @(Compare-ALServiceArguments ($script:Base + @('--network')) $script:Base) | Should -BeLike '*--network is given more than once*'
        @(Compare-ALServiceArguments ($script:Base + @('--auth', 'none')) $script:Base) | Should -BeLike "*unsupported argument '--auth'*"
        @(Compare-ALServiceArguments ($script:Base + @('--Port', '18795')) $script:Base) | Should -BeLike "*unsupported argument '--Port'*"   # names are case-sensitive
        @(Compare-ALServiceArguments ($script:Base + @('stray')) $script:Base) | Should -BeLike "*unsupported argument 'stray'*"
        @(Compare-ALServiceArguments (@('--data-dir') + (Without $script:Base '--data-dir')) $script:Base) | Should -BeLike '*--data-dir has no value*'
        @(Compare-ALServiceArguments $script:Base ($script:Base + @('--port', '1'))) | Should -BeLike 'configuration:*more than once*'
    }

    It 'reads quoted paths with spaces from a service command line and compares paths without regard to case' {
        $spaced = With (With $script:Base '--data-dir' 'C:\Program Data\AuthLens\data') '--cert' 'C:\Program Data\AuthLens\tls\server.pfx'
        $line = '"C:\Program Files\AuthLens Server\server\AuthLens.Api.exe" ' + (($spaced | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' ')
        $tokens = @(Split-ALCommandLine $line)
        $tokens[0] | Should -Be 'C:\Program Files\AuthLens Server\server\AuthLens.Api.exe'
        @(Compare-ALServiceArguments @($tokens | Select-Object -Skip 1) $spaced).Count | Should -Be 0
        @(Compare-ALServiceArguments @($tokens | Select-Object -Skip 1) (With $spaced '--data-dir' 'c:\program data\authlens\DATA')).Count | Should -Be 0
        @(Compare-ALServiceArguments @($tokens | Select-Object -Skip 1) (With $spaced '--data-dir' 'C:\Program Data\AuthLens\data2')).Count | Should -Be 1
    }

    It 'compares listen and proxy addresses as IP addresses' {
        $v6 = With (With $script:Base '--listen' '2001:db8::10') '--trusted-proxies' '2001:DB8:0:0::1'
        @(Compare-ALServiceArguments (With (With $script:Base '--listen' '2001:0db8::0010') '--trusted-proxies' '2001:db8::1') $v6).Count | Should -Be 0
    }
}

Describe 'Managed service detection (binary_path_matches)' {
    BeforeEach {
        $script:Config = New-TestConfig
        $script:Previous = New-TestRelease $script:Config 'old' $script:Old
        $script:Target = New-TestRelease $script:Config 'new' $script:New
        $c = $script:Config
        $exe = [System.IO.Path]::Combine([System.IO.Path]::Combine([System.IO.Path]::Combine($c.ReleasesRoot, 'current'), 'server'), 'AuthLens.Api.exe')
        # How Windows can store the managed command line: executable unquoted (Windows PowerShell 5.1 passing binPath= to sc.exe), options
        # and host list reordered, path case changed.
        $script:Equivalent = ('{0} --port 18795 --listen 192.168.10.20 --network --allowed-hosts 192.168.10.20,lens.example.com --data-dir {1} ' +
            '--cert {2} --cert-password-file {3} --trusted-proxies 192.168.10.10') -f $exe.ToUpperInvariant(), $c.DataDirectory, $c.CertificatePath, $c.CertificatePasswordFile
    }

    It 'reports an equivalent command line as managed and a real difference as not managed' {
        Test-ALServiceBinary (Get-ALBinaryPath $script:Config) $script:Config | Should -BeTrue
        Test-ALServiceBinary $script:Equivalent $script:Config | Should -BeTrue
        Test-ALServiceBinary ($script:Equivalent -replace '--port 18795', '--port 18796') $script:Config | Should -BeFalse
        Test-ALServiceBinary ($script:Equivalent -replace '\\CURRENT\\', '\OTHER\' -replace '/CURRENT/', '/OTHER/') $script:Config | Should -BeFalse
        Test-ALServiceBinary ($script:Equivalent + ' --auth none') $script:Config | Should -BeFalse
        Test-ALServiceBinary '' $script:Config | Should -BeFalse
    }

    It 'shows binary_path_matches true in the status of an equivalent managed service' {
        Use-FakeHost $script:Config $script:Previous
        $script:Expected = $script:Equivalent
        Mock -ModuleName $M Invoke-ALHttp { [pscustomobject]@{ Status = 200; Body = '{"source_sha":"a","version":"2.0.0-alpha.1"}' } }
        (Get-ALStatus $script:Config).binary_path_matches | Should -BeTrue
        $script:Expected = $script:Equivalent -replace '--port 18795', '--port 18796'
        (Get-ALStatus $script:Config).binary_path_matches | Should -BeFalse
    }

    It 'deploys to an equivalent managed service without asking for adoption and without rewriting its command line' {
        Use-FakeHost $script:Config $script:Previous
        $script:Expected = $script:Equivalent
        $script:State.Identity[$script:Target] = $script:New
        Invoke-Deploy $script:Config $script:Target | Should -Be 0
        ($script:Calls -join ' ') | Should -Be 'schema:new backup verify stop link:new start:new'
    }
}
