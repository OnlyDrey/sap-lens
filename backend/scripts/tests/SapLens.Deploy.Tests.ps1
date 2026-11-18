# Pester 5 tests of the SAP Lens Windows deployment state machine (scripts/deploy/SapLens.Deploy.psm1). Every operating-system action (service
# control, the release link, HTTP, git, the server's maintenance commands) is mocked; folders live in TestDrive. Nothing is installed or started.
BeforeAll {
    $script:ModulePath = (Resolve-Path (Join-Path $PSScriptRoot '..\deploy\SapLens.Deploy.psm1')).Path
    $script:EntryPath = (Resolve-Path (Join-Path $PSScriptRoot '..\deploy\Deploy-SapLens.ps1')).Path
    Import-Module $script:ModulePath -Force
    $script:M = 'SapLens.Deploy'
    $script:Original = ''
    # Windows-only cmdlets the module calls; stubs let Pester mock them on Linux (on Windows the real commands exist and are mocked directly).
    foreach ($name in 'New-Service', 'Stop-Service', 'Start-Service', 'Get-NetTCPConnection') {
        if (-not (Get-Command $name -ErrorAction SilentlyContinue)) { New-Item -Path "function:global:$name" -Value { throw "stub $($MyInvocation.MyCommand.Name)" } | Out-Null }
    }
    $script:Old = 'a' * 40; $script:New = 'b' * 40
    $script:Missing = [pscustomobject]@{ Exists = $false; State = 'Missing'; StartMode = ''; Account = ''; PathName = ''; ProcessId = 0 }
    # No real service is ever queried, also on Windows (where the host may run SapLens or SapLens2): tests decide which services exist.
    Mock -ModuleName $M Get-SL2Service { $script:Missing }

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
        Read-SapLensSettings $file
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
        $script:Expected = Get-SL2BinaryPath $Config
        $script:State.ServiceName = $Config.ServiceName
        Mock -ModuleName $M Get-SL2Service { param($Name) if ($Name -ne $script:State.ServiceName) { return $script:Missing }
            [pscustomobject]@{ Exists = $true; State = $script:State.Service; StartMode = 'Auto'; Account = "NT SERVICE\$Name"
            PathName = $script:Expected; ProcessId = $(if ($script:State.Service -eq 'Running') { $script:State.Pid } else { 0 }) } }
        Mock -ModuleName $M Stop-SL2Service { $script:Calls.Add('stop'); if ($script:State.Options.StopTimeout) { Stop-SL2 'Service did not stop within 3 s. It was not killed.' 4 }; $script:State.Service = 'Stopped' }
        Mock -ModuleName $M Start-SL2Service { $script:Calls.Add('start:' + (Split-Path $script:State.Link -Leaf)); $script:State.Service = 'Running'; $script:State.Pid++ }
        Mock -ModuleName $M Get-SL2Link { $script:State.Link }
        Mock -ModuleName $M Set-SL2Link { param($Link, $Target) $script:Calls.Add('link:' + (Split-Path $Target -Leaf)); $script:State.Link = $Target }
        # Like the real function after PowerShell unrolls its result: one listener comes back as a bare [int], none as nothing.
        Mock -ModuleName $M Get-SL2Listener { if ($script:State.Service -eq 'Running') { $script:State.Pid } }
        Mock -ModuleName $M Set-SL2ServiceBinary { param($Name, $BinaryPath) $script:Calls.Add('binary:' + $(if ($BinaryPath -eq (Get-SL2BinaryPath $Config)) { 'managed' } else { 'original' })); $script:Expected = $BinaryPath }
        Mock -ModuleName $M Start-Sleep { }
        Mock -ModuleName $M Stop-Process { throw 'Stop-Process must never be called' }
        Mock -ModuleName $M Invoke-SL2Http {
            param($Url)
            if ($Url -like '*/health/ready') { return [pscustomobject]@{ Status = $(if ($script:State.Options.NeverReady -and $script:State.Link -like '*new*') { 503 } else { 200 }); Body = '' } }
            $sha = $script:State.Identity[$script:State.Link]
            if ($script:State.Options.WrongIdentity -and $script:State.Link -like '*new*') { $sha = 'c' * 40 }
            # An adopted service running its original command line answers as the release it ran before.
            if ($script:Original -and $script:Expected -eq $script:Original) { $sha = $script:Old }
            [pscustomobject]@{ Status = 200; Body = (@{ source_sha = $sha; version = '2.0.0-alpha.1' } | ConvertTo-Json) }
        }
        Mock -ModuleName $M Invoke-SL2Maintenance {
            param($ExePath, $Arguments, [switch]$AllowUnsupported)
            switch ($Arguments[0]) {
                '--schema-info' {
                    $script:Calls.Add('schema:' + (Split-Path (Split-Path (Split-Path $ExePath)) -Leaf))
                    if ($script:State.Options.OldBuildUnsupported -and $ExePath -like '*old*') { return $null }
                    $compatible = -not ($script:State.Options.NewerData -or ($script:State.Options.PreviousIncompatible -and $ExePath -like '*old*'))
                    return [pscustomobject]@{ compatible = $compatible; database_exists = $true; applied = $script:State.Applied; pending = @(); unknown_applied = $(if ($compatible) { @() } else { @('m9') }) }
                }
                '--backup-local' { $script:Calls.Add('backup'); return [pscustomobject]@{ file = (Join-Path $Arguments[1] 'pre.slbak'); sha256 = 'd' * 64; size = 10 } }
                '--backup-verify' { $script:Calls.Add('verify'); return [pscustomobject]@{ verified = -not $script:State.Options.BackupBroken; sha256 = 'd' * 64 } }
            }
        }
    }

    function Invoke-Deploy($Config, $Release) {
        $null = New-SL2Run $Config 'deploy'
        try { Invoke-SL2Deploy $Config $Release $script:New | Out-Null; 0 } catch { if ($_.Exception.PSObject.Properties["ExitCode"]) { $_.Exception.ExitCode } else { throw } }
    }
}

Describe 'Configuration' {
    It 'refuses unknown settings, missing values and relative paths' {
        $file = Join-Path $TestDrive 'bad.json'
        @{ RepositoryPath = 'C:\r'; Typo = 1 } | ConvertTo-Json | Set-Content $file
        { Read-SapLensSettings $file } | Should -Throw '*Unknown deployment setting*'
        @{ RepositoryPath = 'relative\repo'; ListenAddress = '10.0.0.1'; Port = 1; DataDirectory = 'C:\d'; CertificatePath = 'C:\c'; CertificatePasswordFile = 'C:\p' } | ConvertTo-Json | Set-Content $file
        { Read-SapLensSettings $file } | Should -Throw '*absolute path*'
    }

    It 'builds the service command line from the configuration with TLS, hosts and trusted proxies and no secret' {
        $config = New-TestConfig
        $binary = Get-SL2BinaryPath $config
        $binary | Should -Match '--network --listen 192.168.10.20 --port 18795'
        $binary | Should -Match '--allowed-hosts lens.example.com,192.168.10.20'
        $binary | Should -Match '--trusted-proxies 192.168.10.10'
        $binary | Should -Match '--cert-password-file'
        $binary | Should -Not -Match '--cert-password '
    }

    It 'names the service SapLens for a new installation and keeps an existing earlier SapLens2 service' {
        $config = New-TestConfig
        ($config.ServiceName, $config.ServiceAccount, $config.ServiceNameConfigured) | Should -Be @('SapLens', 'NT SERVICE\SapLens', $false)
        Mock -ModuleName $M Get-SL2Service { param($Name) if ($Name -eq 'SapLens2') { [pscustomobject]@{ Exists = $true; State = 'Running' } } else { $script:Missing } }
        $config = Read-SapLensSettings $config.ConfigFile
        ($config.ServiceName, $config.ServiceAccount) | Should -Be @('SapLens2', 'NT SERVICE\SapLens2')
        Mock -ModuleName $M Get-SL2Service { [pscustomobject]@{ Exists = $true; State = 'Running' } }      # both exist: SapLens wins
        (Read-SapLensSettings $config.ConfigFile).ServiceName | Should -Be 'SapLens'
    }

    It 'finds the configuration under the current and the earlier variable name and defaults folders to the configuration folder' {
        $config = New-TestConfig
        $minimal = Join-Path $TestDrive 'minimal/deploy.local.json'
        New-Item -ItemType Directory -Force (Split-Path $minimal) | Out-Null
        $config | Select-Object RepositoryPath, ListenAddress, Port, DataDirectory, CertificatePath, CertificatePasswordFile | ConvertTo-Json | Set-Content $minimal
        $saved = $env:SAPLENS_DEPLOY_CONFIG, $env:SAPLENS2_DEPLOY_CONFIG
        try {
            $env:SAPLENS_DEPLOY_CONFIG = $null; $env:SAPLENS2_DEPLOY_CONFIG = $minimal
            $read = Read-SapLensSettings ''
            $read.ConfigFile | Should -Be $minimal
            $read.ReleasesRoot | Should -Be ([System.IO.Path]::Combine((Split-Path $minimal), 'releases'))
            $read.WorkRoot | Should -Be ([System.IO.Path]::Combine((Split-Path $minimal), 'deploy'))
            $env:SAPLENS_DEPLOY_CONFIG = $config.ConfigFile
            (Read-SapLensSettings '').ConfigFile | Should -Be $config.ConfigFile                  # the current name wins
        } finally { $env:SAPLENS_DEPLOY_CONFIG, $env:SAPLENS2_DEPLOY_CONFIG = $saved }
    }

    It 'maps the test selections to the build filter' {
        Get-SL2TestFilter 'full' | Should -Be ''
        $null -eq (Get-SL2TestFilter 'none') | Should -BeTrue
        Get-SL2TestFilter 'focused' | Should -Match 'FullyQualifiedName~SapLens.Tests.V1DataMigrationTests'
        { Get-SL2TestFilter 'some' } | Should -Throw
    }
}

Describe 'Source' {
    It 'never builds main or work and only deploys pushed commits of the branch' {
        $config = New-TestConfig
        { Resolve-SL2Commit $config 'main' '' } | Should -Throw '*not ''main''*'
        # A single output line arrives as a plain string (the shape that broke Windows PowerShell 5.1 with "[System.Char] ... 'Trim'").
        Mock -ModuleName $M Invoke-SL2Git { param($Repository, $Arguments) if ($Arguments[0] -eq 'rev-parse') { "$('e' * 40)`n" } }
        Mock -ModuleName $M Invoke-SL2Process { [pscustomobject]@{ ExitCode = 1; Output = @() } }
        { Resolve-SL2Commit $config 'experiment/dotnet-backend' ('f' * 40) } | Should -Throw '*only pushed commits*'
        Resolve-SL2Commit $config 'experiment/dotnet-backend' '' | Should -Be ('e' * 40)
    }

    It 'finds the .NET project under backend and, for commits from before the promotion, under experiments\dotnet-backend' {
        $tree = Join-Path $TestDrive ([guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force (Join-Path $tree 'backend'), (Join-Path $tree 'experiments/dotnet-backend') | Out-Null
        Set-Content (Join-Path $tree 'backend/requirements.txt') 'python backend'
        { Get-SL2ProjectRoot $tree } | Should -Throw '*No .NET project*'
        Set-Content (Join-Path $tree 'experiments/dotnet-backend/SapLens.slnx') '<Solution />'
        Get-SL2ProjectRoot $tree | Should -Be ([System.IO.Path]::Combine($tree, 'experiments/dotnet-backend'))
        Remove-Item -Recurse (Join-Path $tree 'experiments')
        Set-Content (Join-Path $tree 'backend/SapLens.slnx') '<Solution />'
        Get-SL2ProjectRoot $tree | Should -Be ([System.IO.Path]::Combine($tree, 'backend'))
    }

    It 'refuses to reuse a modified build worktree' {
        $config = New-TestConfig
        $worktree = Join-Path (Join-Path $config.WorkRoot 'worktrees') ('b' * 12)
        New-Item -ItemType Directory -Force $worktree | Out-Null
        Mock -ModuleName $M Invoke-SL2Git { param($Repository, $Arguments) if ($Arguments[0] -eq 'rev-parse') { 'b' * 40 } else { ' M file.cs' } }
        { New-SL2Worktree $config ('b' * 40) } | Should -Throw '*not a clean checkout*'
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
        (Read-SL2Journal $script:Config).phase | Should -Be 'complete'
        (Read-SL2Journal $script:Config).backup.sha256 | Should -Be ('d' * 64)
    }

    It 'stops nothing when the data was written by a newer build, the backup cannot be verified, or an earlier run was interrupted' {
        Use-FakeHost $script:Config $script:Previous @{ NewerData = $true }
        Invoke-Deploy $script:Config $script:Target | Should -Be 2
        $script:Calls | Should -Not -Contain 'stop'

        Use-FakeHost $script:Config $script:Previous @{ BackupBroken = $true }
        Invoke-Deploy $script:Config $script:Target | Should -Be 1
        $script:Calls | Should -Not -Contain 'stop'

        Write-SL2Journal $script:Config ([pscustomobject]@{ run = 'earlier'; phase = 'switched'; history = @(); updated = '' })
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
        (Read-SL2Journal $script:Config).phase | Should -Be 'rolled_back'
        $script:State.Link | Should -Be $script:Previous
    }

    It 'rolls back after a timeout when the new release never becomes ready' {
        Use-FakeHost $script:Config $script:Previous @{ NeverReady = $true }
        $script:State.Identity[$script:Target] = $script:New
        Invoke-Deploy $script:Config $script:Target | Should -Be 1
        $script:State.Link | Should -Be $script:Previous
        (Read-SL2Journal $script:Config).phase | Should -Be 'rolled_back'
    }

    It 'never returns to a release that cannot open the data, and leaves exact recovery instructions' {
        Use-FakeHost $script:Config $script:Previous @{ WrongIdentity = $true; PreviousIncompatible = $true }
        $script:State.Identity[$script:Target] = $script:New
        Invoke-Deploy $script:Config $script:Target | Should -Be 4
        $script:State.Link | Should -Be $script:Target                                  # not switched back
        $script:Calls | Should -Not -Contain 'start:old'
        (Read-SL2Journal $script:Config).phase | Should -Be 'manual_recovery_required'
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
        Mock -ModuleName $M Start-SL2Service { $script:Calls.Add('start'); $script:State.Service = 'Running'; $script:State.Pid++; $script:State.Applied = @('m1', 'm2') }
        Invoke-Deploy $script:Config $script:Target | Should -Be 4                        # the new release migrated the database: unsafe
        (Read-SL2Journal $script:Config).phase | Should -Be 'manual_recovery_required'
    }

    It 'does not kill a service that does not stop' {
        Use-FakeHost $script:Config $script:Previous @{ StopTimeout = $true }
        Invoke-Deploy $script:Config $script:Target | Should -Be 4
        Should -Invoke -ModuleName $M Stop-Process -Times 0
    }

    It 'previews without backup or service change in a dry run' {
        Use-FakeHost $script:Config $script:Previous
        $null = New-SL2Run $script:Config 'deploy'
        $result = Invoke-SL2Deploy $script:Config $script:Target $script:New -DryRun
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
        Write-SL2Journal $script:Config ([pscustomobject]@{ run = 'cut'; phase = 'switched'; from_release = $script:Previous; to_release = $script:Target; applied_before = @('m1')
            service_state_before = 'Running'; backup = $null; history = @(); updated = '' })
        $null = New-SL2Run $script:Config 'recover'
        (Invoke-SL2Recover $script:Config).phase | Should -Be 'rolled_back'
        $script:State.Link | Should -Be $script:Previous
        $script:State.Service | Should -Be 'Running'
    }

    It 'marks a run interrupted before the stop as aborted and restarts a service that was running' {
        Use-FakeHost $script:Config $script:Previous
        $script:State.Service = 'Stopped'
        Write-SL2Journal $script:Config ([pscustomobject]@{ run = 'cut'; phase = 'backup'; from_release = $script:Previous; service_state_before = 'Running'; history = @(); updated = '' })
        $null = New-SL2Run $script:Config 'recover'
        (Invoke-SL2Recover $script:Config).phase | Should -Be 'aborted'
        $script:State.Service | Should -Be 'Running'
        $script:State.Link | Should -Be $script:Previous
    }

    It 'rolls back on request only when the previous release can open the data' {
        Use-FakeHost $script:Config $script:Target @{ PreviousIncompatible = $true }
        Write-SL2Journal $script:Config ([pscustomobject]@{ run = 'done'; phase = 'complete'; from_release = $script:Previous; history = @(); updated = '' })
        $null = New-SL2Run $script:Config 'rollback'
        { Invoke-SL2Rollback $script:Config '' } | Should -Throw '*not safe*'
        $script:State.Link | Should -Be $script:Target
    }
}

Describe 'Service installation and host safety' {
    It 'refuses to install while another process holds the port and never stops it' {
        $config = New-TestConfig
        $release = New-TestRelease $config 'new' $script:New
        Mock -ModuleName $M Get-SL2Service { [pscustomobject]@{ Exists = $false; State = 'Missing'; StartMode = ''; Account = ''; PathName = ''; ProcessId = 0 } }
        Mock -ModuleName $M Get-SL2Link { $release }
        Mock -ModuleName $M Get-SL2Listener { 999 }
        Mock -ModuleName $M Stop-Process { throw 'never' }
        Mock -ModuleName $M New-Service { throw 'must not be created' }
        { Install-SL2Service $config } | Should -Throw '*used by process 999*'
        Should -Invoke -ModuleName $M Stop-Process -Times 0
    }

    It 'never creates a second service beside an earlier SapLens2 installation' {
        $config = New-TestConfig
        $config.ServiceName = 'SapLens'; $config.ServiceNameConfigured = $true
        Mock -ModuleName $M Get-SL2Service { param($Name) if ($Name -eq 'SapLens2') { [pscustomobject]@{ Exists = $true; State = 'Running'; ProcessId = 7 } } else { $script:Missing } }
        Mock -ModuleName $M New-Service { throw 'must not be created' }
        { Install-SL2Service $config } | Should -Throw '*a second service is never created*'
        Should -Invoke -ModuleName $M New-Service -Times 0
    }

    It 'reports an unmanaged server (for example the test launcher) as such' {
        $config = New-TestConfig
        Mock -ModuleName $M Get-SL2Service { [pscustomobject]@{ Exists = $false; State = 'Missing'; StartMode = ''; Account = ''; PathName = ''; ProcessId = 0 } }
        Mock -ModuleName $M Get-SL2Link { '' }
        Mock -ModuleName $M Get-SL2Listener { 999 }
        Mock -ModuleName $M Invoke-SL2Http { [pscustomobject]@{ Status = 200; Body = '{"source_sha":"x","version":"2.0.0-alpha.1"}' } }
        (Get-SL2Status $config).service_model | Should -Be 'unmanaged-process'
    }

    It 'allows one deployment operation at a time' {
        $config = New-TestConfig
        Enter-SL2Lock $config
        try {
            $second = Start-Job -ScriptBlock { param($Module, $Work) Import-Module $Module; try { Enter-SL2Lock ([pscustomobject]@{ WorkRoot = $Work }); 'acquired' } catch { $_.Exception.Message } } -ArgumentList $script:ModulePath, $config.WorkRoot
            ($second | Wait-Job | Receive-Job) | Should -Match 'Another deployment operation is running'
        } finally { Exit-SL2Lock }
    }

    It 'requires -Yes for actions that change the service' {
        $config = New-TestConfig
        $file = Join-Path $TestDrive 'entry.json'
        $config | Select-Object * -ExcludeProperty ConfigFile, ServiceNameConfigured, ServiceName, ServiceAccount | ConvertTo-Json | Set-Content $file
        $output = & pwsh -NoProfile -File $script:EntryPath -Action Deploy -ConfigFile $file 2>&1
        $LASTEXITCODE | Should -Be 2
        ($output -join "`n") | Should -Match 'repeat with -Yes'
    }
}

Describe 'Windows PowerShell 5.1 regressions' {
    It 'reads a single git line that PowerShell returns as a plain string (the [System.Char] Trim failure)' {
        $config = New-TestConfig
        Mock -ModuleName $M Invoke-SL2Git { "  $('c' * 40)  " }
        Get-SL2GitValue $config.RepositoryPath @('rev-parse', 'HEAD') | Should -Be ('c' * 40)
        Mock -ModuleName $M Invoke-SL2Git { 'one'; 'two' }
        { Get-SL2GitValue $config.RepositoryPath @('rev-parse', 'HEAD') } | Should -Throw '*expected one*'
    }

    It 'keeps native commands from stopping on stderr and never reads $IsWindows unguarded' {
        $module = Get-Content $script:ModulePath -Raw
        foreach ($name in 'Invoke-SL2Git', 'Invoke-SL2Process', 'Invoke-SL2Http') {
            $body = ([regex]::Match($module, "function $name\b[^{]*\{(?<b>[\s\S]*?)\n\}")).Groups['b'].Value
            $body | Should -Match "ErrorActionPreference = 'Continue'"
        }
        $module | Should -Not -Match '\)\[0\]\.Trim\(\)'
        (Get-Content $script:EntryPath -Raw) | Should -Not -Match '-not \$IsWindows'
    }

    It 'appends to a journal history read back from JSON with a single entry' {
        $config = New-TestConfig
        $null = New-SL2Run $config 'recover'
        Write-SL2Journal $config ([pscustomobject]@{ run = 'r'; phase = 'backup'; history = @(@{ phase = 'prepared'; at = 'x' }); updated = '' })
        $journal = Read-SL2Journal $config
        Set-SL2Phase $config $journal 'aborted'
        @((Read-SL2Journal $config).history).Count | Should -Be 2
    }
}

Describe 'Adopting a hand-installed service' {
    AfterAll { $script:Original = '' }
    BeforeEach {
        $script:Config = New-TestConfig
        $script:Target = New-TestRelease $script:Config 'new' $script:New
        $script:Original = '"C:\saplens2\builds\manual\server\SapLens.Api.exe" ' + ((Get-SL2ServiceArguments $script:Config | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' ')
    }

    It 'adopts only on request and only with the configured arguments' {
        Use-FakeHost $script:Config ''
        $script:Expected = $script:Original
        Invoke-Deploy $script:Config $script:Target | Should -Be 2                              # without -AdoptService
        $script:Calls | Should -Not -Contain 'stop'
        $script:Expected = $script:Original -replace '--port 18795', '--port 18796'
        $null = New-SL2Run $script:Config 'deploy'
        { Invoke-SL2Deploy $script:Config $script:Target $script:New -AdoptService } | Should -Throw '*arguments differ*'
        $script:Calls | Should -Not -Contain 'stop'
    }

    It 'adopts a service whose equivalent arguments are in another order, with host and proxy lists in another order' {
        Use-FakeHost $script:Config ''
        # The shape of a hand-installed service: options reordered, lists reordered, a different case in a path.
        $c = $script:Config
        $script:Expected = ('"C:\saplens2\builds\manual\server\SapLens.Api.exe" --data-dir "{0}" --listen 192.168.10.20 --port 18795 --network ' +
            '--allowed-hosts 192.168.10.20,LENS.example.com --trusted-proxies 192.168.10.10 --cert "{1}" --cert-password-file "{2}"') -f $c.DataDirectory, $c.CertificatePath, $c.CertificatePasswordFile
        $script:Original = $script:Expected
        $script:State.Identity[$script:Target] = $script:New
        $null = New-SL2Run $script:Config 'deploy'
        (Invoke-SL2Deploy $script:Config $script:Target $script:New -AdoptService).deployed | Should -BeTrue
        ($script:Calls -join ' ') | Should -Be 'schema:new backup verify stop link:new binary:managed start:new'
        (Read-SL2Journal $script:Config).service_binary_before | Should -Be $script:Original      # captured for rollback
    }

    It 'moves the service to the managed release link and keeps it there when ready' {
        Use-FakeHost $script:Config ''
        $script:Expected = $script:Original
        $script:State.Identity[$script:Target] = $script:New
        $null = New-SL2Run $script:Config 'deploy'
        (Invoke-SL2Deploy $script:Config $script:Target $script:New -AdoptService).deployed | Should -BeTrue
        ($script:Calls -join ' ') | Should -Be 'schema:new backup verify stop link:new binary:managed start:new'
    }

    It 'restores the original command line when the adopted deployment fails' {
        Use-FakeHost $script:Config '' @{ WrongIdentity = $true }
        $script:Expected = $script:Original
        $script:State.Identity[$script:Target] = $script:New
        $script:State.Identity[''] = $script:Old
        $null = New-SL2Run $script:Config 'deploy'
        { Invoke-SL2Deploy $script:Config $script:Target $script:New -AdoptService } | Should -Throw '*rolled back*'
        $script:Expected | Should -Be $script:Original
        $script:Calls | Should -Contain 'binary:original'
        (Read-SL2Journal $script:Config).phase | Should -Be 'rolled_back'
    }
}

Describe 'Migrating an earlier SapLens2 service to SapLens' {
    BeforeEach {
        $script:Config = New-TestConfig
        $script:Current = New-TestRelease $script:Config 'current' $script:Old
        # Two services by name; the fake host listens with the running one's process.
        $script:Svc = @{ SapLens2 = @{ State = 'Running'; Pid = 100; StartMode = 'Auto'; Path = (Get-SL2BinaryPath $script:Config) } }
        $script:Calls = [System.Collections.Generic.List[string]]::new()
        $script:Fail = @{}
        Mock -ModuleName $M Get-SL2Service { param($Name) $s = $script:Svc[$Name]; if (-not $s) { return $script:Missing }
            [pscustomobject]@{ Exists = $true; State = $s.State; StartMode = $s.StartMode; Account = "NT SERVICE\$Name"; PathName = $s.Path; ProcessId = $(if ($s.State -eq 'Running') { $s.Pid } else { 0 }) } }
        Mock -ModuleName $M New-Service { param($Name, $DisplayName, $BinaryPathName) $script:Calls.Add("create:$Name"); $script:Svc[$Name] = @{ State = 'Stopped'; Pid = 200; StartMode = 'Manual'; Path = $BinaryPathName } }
        Mock -ModuleName $M Invoke-SL2Process { param($File, $Arguments) $script:Calls.Add(($Arguments | Select-Object -First 4) -join ' ')
            if ($Arguments[0] -eq 'delete') { $script:Svc.Remove($Arguments[1]) }
            if ($Arguments[0] -eq 'config' -and $Arguments[2] -eq 'start=') { $script:Svc[$Arguments[1]].StartMode = $Arguments[3] }
            [pscustomobject]@{ ExitCode = 0; Output = @() } }
        Mock -ModuleName $M Stop-SL2Service { param($Name) $script:Calls.Add("stop:$Name"); $script:Svc[$Name].State = 'Stopped' }
        Mock -ModuleName $M Start-SL2Service { param($Name) $script:Calls.Add("start:$Name"); $script:Svc[$Name].State = 'Running' }
        Mock -ModuleName $M Get-SL2Link { $script:Current }
        Mock -ModuleName $M Get-SL2Listener { foreach ($s in $script:Svc.Values) { if ($s.State -eq 'Running') { $s.Pid } } }
        Mock -ModuleName $M Invoke-SL2Http { param($Url) if ($Url -like '*/health/ready') { return [pscustomobject]@{ Status = $(if ($script:Fail.NeverReady -and $script:Svc['SapLens'] -and $script:Svc['SapLens'].State -eq 'Running') { 503 } else { 200 }); Body = '' } }
            [pscustomobject]@{ Status = 200; Body = (@{ source_sha = $script:Old; version = '2.0.0-alpha.1' } | ConvertTo-Json) } }
        Mock -ModuleName $M Start-Sleep { }
        Mock -ModuleName $M Stop-Process { throw 'Stop-Process must never be called' }
        $script:Config = Read-SapLensSettings $script:Config.ConfigFile          # detects SapLens2
        $null = New-SL2Run $script:Config 'migrateservice'
    }

    It 'creates SapLens with its own account, verifies it, then removes SapLens2; data and command line stay the same' {
        $script:Config.ServiceName | Should -Be 'SapLens2'
        $result = Invoke-SL2MigrateService $script:Config
        ($result.service, $result.account, $result.legacy_service_deleted) | Should -Be @('SapLens', 'NT SERVICE\SapLens', $true)
        $script:Svc.Keys | Should -Be @('SapLens')
        $script:Svc['SapLens'].Path | Should -Be (Get-SL2BinaryPath $script:Config)
        $script:Svc['SapLens'].StartMode | Should -Be 'auto'
        $order = $script:Calls -join ' | '
        $order | Should -Match 'create:SapLens .*obj= NT SERVICE\\SapLens.*/grant NT SERVICE\\SapLens:\(OI\)\(CI\)M.*stop:SapLens2 \| config SapLens2 start= disabled \| start:SapLens .*config SapLens start= auto \| delete SapLens2'
        Test-Path (Join-Path (Split-Path (Get-ChildItem -Recurse -Filter legacy-service.json -Path $script:Config.WorkRoot).FullName) 'legacy-service.json') | Should -BeTrue
        (Read-SapLensSettings $script:Config.ConfigFile).ServiceName | Should -Be 'SapLens'      # detected after the migration
    }

    It 'removes the new service and restores SapLens2 when SapLens does not become ready' {
        $script:Fail.NeverReady = $true
        { Invoke-SL2MigrateService $script:Config } | Should -Throw '*SapLens2 is unchanged and running again*'
        $script:Svc.Keys | Should -Be @('SapLens2')
        ($script:Svc['SapLens2'].State, $script:Svc['SapLens2'].StartMode) | Should -Be @('Running', 'auto')
        $script:Calls | Should -Contain 'delete SapLens'
    }

    It 'refuses without any change when the service is named in the configuration, both services exist, or SapLens2 is not on the managed release' {
        $named = $script:Config.PSObject.Copy(); $named.ServiceNameConfigured = $true
        { Invoke-SL2MigrateService $named } | Should -Throw '*Remove both settings*'
        $script:Svc['SapLens2'].Path = '"C:\manual\SapLens.Api.exe" --data-dir C:\d'
        { Invoke-SL2MigrateService $script:Config } | Should -Throw '*-AdoptService first*'
        $script:Svc['SapLens'] = @{ State = 'Stopped'; Pid = 0; StartMode = 'Manual'; Path = '' }
        { Invoke-SL2MigrateService $script:Config } | Should -Throw '*Both SapLens and SapLens2 exist*'
        $script:Calls | Should -BeNullOrEmpty
    }
}

Describe 'Semantic comparison of service arguments' {
    BeforeAll {
        $script:Base = @('--data-dir', 'C:\ProgramData\SapLens\data', '--network', '--listen', '192.0.2.10', '--port', '18795',
            '--allowed-hosts', 'lens.example.com,192.0.2.10', '--cert', 'C:\ProgramData\SapLens\tls\server.pfx',
            '--cert-password-file', 'C:\ProgramData\SapLens\tls\cert-password', '--trusted-proxies', '192.0.2.1,192.0.2.2')
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
        $reordered = @('--listen', '192.0.2.10', '--port', '18795', '--network', '--trusted-proxies', '192.0.2.1,192.0.2.2', '--cert', 'C:\ProgramData\SapLens\tls\server.pfx',
            '--allowed-hosts', 'lens.example.com,192.0.2.10', '--cert-password-file', 'C:\ProgramData\SapLens\tls\cert-password', '--data-dir', 'C:\ProgramData\SapLens\data')
        @(Compare-SL2ServiceArguments $reordered $script:Base).Count | Should -Be 0
    }

    It 'treats host and proxy lists as sets: order, spacing, host-name case and repeated entries do not matter' {
        $lists = With (With $script:Base '--allowed-hosts' ' 192.0.2.10 , LENS.EXAMPLE.COM,lens.example.com') '--trusted-proxies' '192.0.2.2,192.0.2.1'
        @(Compare-SL2ServiceArguments $lists $script:Base).Count | Should -Be 0
    }

    It 'reports every real difference in a security-sensitive value' {
        foreach ($case in @(
                @('--data-dir', 'C:\ProgramData\SapLens\other'), @('--listen', '192.0.2.11'), @('--port', '18796'), @('--allowed-hosts', 'lens.example.com'),
                @('--allowed-hosts', 'lens.example.com,192.0.2.10,evil.example.net'), @('--trusted-proxies', '192.0.2.1'), @('--trusted-proxies', '192.0.2.1,192.0.2.3'),
                @('--cert', 'C:\ProgramData\SapLens\tls\other.pfx'), @('--cert-password-file', 'C:\ProgramData\SapLens\tls\other'), @('--port', '018795x'))) {
            $differences = @(Compare-SL2ServiceArguments (With $script:Base $case[0] $case[1]) $script:Base)
            $differences.Count | Should -Be 1 -Because "$($case[0]) $($case[1])"
            $differences[0] | Should -BeLike "$($case[0]) differs*"
        }
    }

    It 'reports a missing security-sensitive option on either side' {
        foreach ($name in '--data-dir', '--network', '--listen', '--port', '--allowed-hosts', '--trusted-proxies', '--cert', '--cert-password-file') {
            @(Compare-SL2ServiceArguments (Without $script:Base $name) $script:Base) | Should -Be "$name is missing on the service" -Because $name
            @(Compare-SL2ServiceArguments $script:Base (Without $script:Base $name)) | Should -Be "$name is on the service but not in the configuration" -Because $name
        }
    }

    It 'refuses repeated, conflicting, unknown and incomplete options instead of ignoring them' {
        @(Compare-SL2ServiceArguments ($script:Base + @('--port', '18795')) $script:Base) | Should -BeLike '*--port is given more than once*'
        @(Compare-SL2ServiceArguments ($script:Base + @('--port', '18796')) $script:Base) | Should -BeLike '*--port is given more than once*'
        @(Compare-SL2ServiceArguments ($script:Base + @('--network')) $script:Base) | Should -BeLike '*--network is given more than once*'
        @(Compare-SL2ServiceArguments ($script:Base + @('--auth', 'none')) $script:Base) | Should -BeLike "*unsupported argument '--auth'*"
        @(Compare-SL2ServiceArguments ($script:Base + @('--Port', '18795')) $script:Base) | Should -BeLike "*unsupported argument '--Port'*"   # names are case-sensitive
        @(Compare-SL2ServiceArguments ($script:Base + @('stray')) $script:Base) | Should -BeLike "*unsupported argument 'stray'*"
        @(Compare-SL2ServiceArguments (@('--data-dir') + (Without $script:Base '--data-dir')) $script:Base) | Should -BeLike '*--data-dir has no value*'
        @(Compare-SL2ServiceArguments $script:Base ($script:Base + @('--port', '1'))) | Should -BeLike 'configuration:*more than once*'
    }

    It 'reads quoted paths with spaces from a service command line and compares paths without regard to case' {
        $spaced = With (With $script:Base '--data-dir' 'C:\Program Data\SAP Lens\data') '--cert' 'C:\Program Data\SAP Lens\tls\server.pfx'
        $line = '"C:\Program Files\SAP Lens Server\server\SapLens.Api.exe" ' + (($spaced | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }) -join ' ')
        $tokens = @(Split-SL2CommandLine $line)
        $tokens[0] | Should -Be 'C:\Program Files\SAP Lens Server\server\SapLens.Api.exe'
        @(Compare-SL2ServiceArguments @($tokens | Select-Object -Skip 1) $spaced).Count | Should -Be 0
        @(Compare-SL2ServiceArguments @($tokens | Select-Object -Skip 1) (With $spaced '--data-dir' 'c:\program data\sap lens\DATA')).Count | Should -Be 0
        @(Compare-SL2ServiceArguments @($tokens | Select-Object -Skip 1) (With $spaced '--data-dir' 'C:\Program Data\SAP Lens\data2')).Count | Should -Be 1
    }

    It 'compares listen and proxy addresses as IP addresses' {
        $v6 = With (With $script:Base '--listen' '2001:db8::10') '--trusted-proxies' '2001:DB8:0:0::1'
        @(Compare-SL2ServiceArguments (With (With $script:Base '--listen' '2001:0db8::0010') '--trusted-proxies' '2001:db8::1') $v6).Count | Should -Be 0
    }
}
