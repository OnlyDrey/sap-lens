# Pester 5 tests of the SAP Lens 2 Windows deployment state machine (scripts/deploy/SapLens2.Deploy.psm1). Every operating-system action (service
# control, the release link, HTTP, git, the server's maintenance commands) is mocked; folders live in TestDrive. Nothing is installed or started.
BeforeAll {
    $script:ModulePath = (Resolve-Path (Join-Path $PSScriptRoot '..\deploy\SapLens2.Deploy.psm1')).Path
    $script:EntryPath = (Resolve-Path (Join-Path $PSScriptRoot '..\deploy\Deploy-SapLens2.ps1')).Path
    Import-Module $script:ModulePath -Force
    $script:M = 'SapLens2.Deploy'
    $script:Original = ''
    # Windows-only cmdlets the module calls; stubs let Pester mock them on Linux (on Windows the real commands exist and are mocked directly).
    foreach ($name in 'New-Service', 'Stop-Service', 'Start-Service', 'Get-NetTCPConnection') {
        if (-not (Get-Command $name -ErrorAction SilentlyContinue)) { New-Item -Path "function:global:$name" -Value { throw "stub $($MyInvocation.MyCommand.Name)" } | Out-Null }
    }
    $script:Old = 'a' * 40; $script:New = 'b' * 40

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
        Read-SapLens2Settings $file
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
        Mock -ModuleName $M Get-SL2Service { [pscustomobject]@{ Exists = $true; State = $script:State.Service; StartMode = 'Auto'; Account = 'NT SERVICE\SapLens2'
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
        { Read-SapLens2Settings $file } | Should -Throw '*Unknown deployment setting*'
        @{ RepositoryPath = 'relative\repo'; ListenAddress = '10.0.0.1'; Port = 1; DataDirectory = 'C:\d'; CertificatePath = 'C:\c'; CertificatePasswordFile = 'C:\p' } | ConvertTo-Json | Set-Content $file
        { Read-SapLens2Settings $file } | Should -Throw '*absolute path*'
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
        $config | ConvertTo-Json | Set-Content $file
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
