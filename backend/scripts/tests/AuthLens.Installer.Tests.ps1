BeforeAll {
    . (Join-Path $PSScriptRoot 'TestHelpers.ps1')
    Import-TestDeploymentModule
    $M='AuthLens.Deploy'
    function New-InstallerFixture {
        $base=Join-Path $TestDrive ([Guid]::NewGuid().ToString('N'))
        $root=Join-Path $base 'program'; $data=Join-Path $base 'data'; $package=Join-Path $base 'package'
        foreach ($folder in $root,$data,(Join-Path $package 'desktop'),(Join-Path $package 'server')) { New-Item -ItemType Directory -Force $folder | Out-Null }
        [IO.File]::WriteAllText((Join-Path $root 'AuthLens.exe'),'old')
        [IO.File]::WriteAllText((Join-Path $package 'desktop/AuthLens.exe'),'new')
        [IO.File]::WriteAllText((Join-Path $data 'authlens.sqlite3'),'synthetic data sentinel')
        $old=@{product='AuthLens';artifacts=@(@{path='desktop/AuthLens.exe';sha256=(Get-FileHash (Join-Path $root 'AuthLens.exe')).Hash})}
        $old | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $root 'build-manifest.json')
        $script:Manifest=[pscustomobject]@{product='AuthLens';source_sha=('b'*40);artifacts=@([pscustomobject]@{path='desktop/AuthLens.exe';sha256=(Get-FileHash (Join-Path $package 'desktop/AuthLens.exe')).Hash})}
        $script:Manifest | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $package 'build-manifest.json')
        [pscustomobject]@{Root=$root;Data=$data;Package=$package}
    }
}

Describe 'Native Desktop installer acceptance on explicitly selected synthetic fixtures' {
    It 'installs, updates with an application-engine backup and recovers an interrupted checkpoint' -Skip:($env:OS -ne 'Windows_NT' -or -not $env:AUTHLENS_INSTALLER_TEST_RELEASE) {
        # Opt in with a verified full Windows release. No SCM, registry or existing data/profile is selected.
        $package=$env:AUTHLENS_INSTALLER_TEST_RELEASE
        $fixture=Join-Path $TestDrive ('native-installer-'+[Guid]::NewGuid().ToString('N'))
        New-ALInstallerPrivateDirectory $fixture
        $root=Join-Path $fixture 'program'; $data=Join-Path $fixture 'data'
        $fresh=Invoke-ALInstallerDesktop $root $data $package
        $fresh.installed | Should -BeTrue; $fresh.updated | Should -BeFalse
        $keys=Join-Path $fixture 'keys'; New-ALInstallerPrivateDirectory $keys
        $server=Join-Path $package 'server/AuthLens.Api.exe'
        $null=Invoke-ALMaintenance $server @('--backup-key','create',(Join-Path $keys 'host.key'),'--data-dir',$data)
        $update=Invoke-ALInstallerDesktop $root $data $package
        $update.updated | Should -BeTrue
        (Invoke-ALMaintenance $server @('--backup-verify',$update.backup.file,'--data-dir',$data)).verified | Should -BeTrue
        $path=Join-Path $root '.setup-state/journal.json'; $journal=Get-Content $path -Raw | ConvertFrom-Json
        $journal.phase='verifying'; Write-ALInstallerJournal $path $journal
        (Invoke-ALInstallerDesktop $root $data $package -Recover).recovered | Should -BeTrue
        $schema=Invoke-ALMaintenance $server @('--schema-info','--data-dir',$data)
        $schema.database_exists | Should -BeTrue; $schema.compatible | Should -BeTrue
        Test-Path (Join-Path $update.run 'previous.exe') | Should -BeTrue
        Test-Path (Join-Path $update.run 'recovery-tools/installer-tools.json') | Should -BeTrue
    }
}
Describe 'Native release-pointer update boundaries on synthetic fixtures' {
    It 'switches a junction without altering either release, and preserves interrupted staging' -Skip:($env:OS -ne 'Windows_NT') {
        $root=Join-Path $TestDrive ([Guid]::NewGuid().ToString('N'))
        $old=Join-Path $root 'old'; $new=Join-Path $root 'new'; $link=Join-Path $root 'current'
        foreach ($path in $old,$new) { New-Item -ItemType Directory -Force $path | Out-Null; Set-Content (Join-Path $path 'sentinel') $path }
        try {
            Set-ALLink $link $old
            Set-Content ($link+'.next') 'interrupted sentinel'
            { Set-ALLink $link $new } | Should -Throw '*preserved for inspection*'
            (Get-ALLink $link) | Should -Be $old
            Get-Content ($link+'.next') | Should -Be 'interrupted sentinel'
            # This file belongs only to this fixture, and is removed solely to exercise the normal swap afterwards.
            Remove-Item -LiteralPath ($link+'.next')
            Set-ALLink $link $new
            (Get-ALLink $link) | Should -Be $new
            Get-Content (Join-Path $old 'sentinel') | Should -Be $old
            Get-Content (Join-Path $new 'sentinel') | Should -Be $new
        } finally { if (Test-Path -LiteralPath $link) { (Get-Item -LiteralPath $link -Force).Delete() } }
    }
    It 'rejects external targets, parent loops and nested junctions before creating a pointer' -Skip:($env:OS -ne 'Windows_NT') {
        $root=Join-Path $TestDrive ([Guid]::NewGuid().ToString('N')); $release=Join-Path $root 'release'; $link=Join-Path $root 'current'
        $outside=Join-Path $TestDrive ([Guid]::NewGuid().ToString('N'))
        foreach ($path in $release,$outside) { New-Item -ItemType Directory -Force $path | Out-Null }
        { Set-ALLink $link $outside } | Should -Throw '*inside its releases*'
        { Set-ALLink $link $root } | Should -Throw '*inside its releases*'
        $nested=Join-Path $release 'escape'; New-Item -ItemType Junction -Path $nested -Target $outside | Out-Null
        try { { Set-ALLink $link $release } | Should -Throw '*reparse points*'; Test-Path $link | Should -BeFalse }
        finally { (Get-Item -LiteralPath $nested -Force).Delete() }
    }
}
Describe 'Installer transactions on isolated program/data fixtures' {
    BeforeEach {
        $script:Fixture=New-InstallerFixture
        $script:FailNew=$false; $script:FailOld=$false; $script:FailBackup=$false; $script:Pending=@(); $script:Applied=@('m1')
        Mock -ModuleName $M Get-ALInstallerPackage { $script:Manifest }
        Mock -ModuleName $M New-ALInstallerPrivateDirectory { param($Path) New-Item -ItemType Directory -Path $Path | Out-Null }
        Mock -ModuleName $M Assert-ALAclPlan { [pscustomobject]@{safe=$true} }
        Mock -ModuleName $M Save-ALInstallerRecoveryTools { }
        Mock -ModuleName $M Assert-ALDesktopIdle { }
        Mock -ModuleName $M Invoke-ALProcess { throw 'No real native command or service may run in these unit tests.' }
        Mock -ModuleName $M Invoke-ALMaintenance {
            param($ExePath,$Arguments)
            switch ($Arguments[0]) {
                '--schema-info' { return [pscustomobject]@{compatible=$true;database_exists=$true;pending=$script:Pending;applied=$script:Applied} }
                '--backup-local' { if ($script:FailBackup) { Stop-AL 'synthetic backup refusal' }; return [pscustomobject]@{file='synthetic.slbak';sha256='abc';size=42} }
                '--backup-verify' { return [pscustomobject]@{verified=$true;sha256='abc'} }
                default { throw 'Unexpected maintenance operation' }
            }
        }
        Mock -ModuleName $M Invoke-ALDesktopProbe {
            param($Exe,$Data)
            $bytes=[IO.File]::ReadAllText($Exe)
            if (($bytes -eq 'new' -and $script:FailNew) -or ($bytes -eq 'old' -and $script:FailOld)) { Stop-AL 'synthetic readiness refusal' 1 }
        }
    }
    It 'updates only after verified recovery files and an application-engine backup, preserving data' {
        $result=Invoke-ALInstallerDesktop $Fixture.Root $Fixture.Data $Fixture.Package
        $result.updated | Should -BeTrue
        [IO.File]::ReadAllText((Join-Path $Fixture.Root 'AuthLens.exe')) | Should -Be 'new'
        [IO.File]::ReadAllText((Join-Path $Fixture.Data 'authlens.sqlite3')) | Should -Be 'synthetic data sentinel'
        [IO.File]::ReadAllText((Join-Path $result.run 'previous.exe')) | Should -Be 'old'
        Should -Invoke -ModuleName $M Invoke-ALMaintenance -Times 1 -ParameterFilter { $Arguments[0] -eq '--backup-verify' }
        Should -Invoke -ModuleName $M Invoke-ALDesktopProbe -Times 2
    }
    It 'selects an explicit executable of the current PowerShell edition without PATH discovery' {
        $shell=Get-ALShell
        [IO.Path]::IsPathRooted($shell) | Should -BeTrue
        (Split-Path $shell) | Should -Be $PSHOME
        Test-Path -LiteralPath $shell -PathType Leaf | Should -BeTrue
    }
    It 'restores and probes the previous executable when the candidate is not ready' {
        $script:FailNew=$true
        { Invoke-ALInstallerDesktop $Fixture.Root $Fixture.Data $Fixture.Package } | Should -Throw '*previous Desktop was restored*'
        [IO.File]::ReadAllText((Join-Path $Fixture.Root 'AuthLens.exe')) | Should -Be 'old'
        (Get-Content (Join-Path $Fixture.Root '.setup-state/journal.json') -Raw | ConvertFrom-Json).phase | Should -Be 'rolled_back'
    }
    It 'refuses a pending schema change before backup or replacement' {
        $script:Pending=@('m2')
        { Invoke-ALInstallerDesktop $Fixture.Root $Fixture.Data $Fixture.Package } | Should -Throw '*pending schema migrations*'
        Should -Invoke -ModuleName $M Invoke-ALDesktopProbe -Times 0
        [IO.File]::ReadAllText((Join-Path $Fixture.Root 'AuthLens.exe')) | Should -Be 'old'
    }
    It 'preserves a failed backup run and never replaces installed files' {
        $script:FailBackup=$true
        { Invoke-ALInstallerDesktop $Fixture.Root $Fixture.Data $Fixture.Package } | Should -Throw '*backup refusal*'
        [IO.File]::ReadAllText((Join-Path $Fixture.Root 'AuthLens.exe')) | Should -Be 'old'
        (Get-Content (Join-Path $Fixture.Root '.setup-state/journal.json') -Raw | ConvertFrom-Json).phase | Should -Be 'backup'
    }
    It 'requires explicit recovery after interruption and preserves previous recovery artifacts' {
        $result=Invoke-ALInstallerDesktop $Fixture.Root $Fixture.Data $Fixture.Package
        $path=Join-Path $Fixture.Root '.setup-state/journal.json'
        $journal=Get-Content $path -Raw | ConvertFrom-Json; $journal.phase='verifying'; $journal | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $path
        { Invoke-ALInstallerDesktop $Fixture.Root $Fixture.Data $Fixture.Package } | Should -Throw '*explicit recovery*'
        (Invoke-ALInstallerDesktop $Fixture.Root $Fixture.Data $Fixture.Package -Recover).recovered | Should -BeTrue
        [IO.File]::ReadAllText((Join-Path $Fixture.Root 'AuthLens.exe')) | Should -Be 'old'
        Test-Path (Join-Path $result.run 'previous.exe') | Should -BeTrue
    }
    It 'refuses changed recovery files without overwriting the current executable' {
        $result=Invoke-ALInstallerDesktop $Fixture.Root $Fixture.Data $Fixture.Package
        $path=Join-Path $Fixture.Root '.setup-state/journal.json'; $journal=Get-Content $path -Raw | ConvertFrom-Json; $journal.phase='verifying'; $journal | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $path
        [IO.File]::WriteAllText((Join-Path $result.run 'previous.exe'),'tampered')
        { Invoke-ALInstallerDesktop $Fixture.Root $Fixture.Data $Fixture.Package -Recover } | Should -Throw '*recovery proof*'
        [IO.File]::ReadAllText((Join-Path $Fixture.Root 'AuthLens.exe')) | Should -Be 'new'
    }
    It 'refuses recovery after the database schema changes and preserves both binaries' {
        $result=Invoke-ALInstallerDesktop $Fixture.Root $Fixture.Data $Fixture.Package
        $path=Join-Path $Fixture.Root '.setup-state/journal.json'; $journal=Get-Content $path -Raw | ConvertFrom-Json; $journal.phase='verifying'; $journal | ConvertTo-Json -Depth 8 | Set-Content -Encoding UTF8 $path
        $script:Applied=@('m1','m2')
        { Invoke-ALInstallerDesktop $Fixture.Root $Fixture.Data $Fixture.Package -Recover } | Should -Throw '*Data schema changed*'
        [IO.File]::ReadAllText((Join-Path $Fixture.Root 'AuthLens.exe')) | Should -Be 'new'
        [IO.File]::ReadAllText((Join-Path $result.run 'previous.exe')) | Should -Be 'old'
    }
    It 'records manual recovery when neither candidate nor rollback becomes ready' {
        # The previous probe succeeds; only its later rollback probe fails.
        $script:Probes=0
        Mock -ModuleName $M Invoke-ALDesktopProbe { $script:Probes++; if ($script:Probes -gt 1) { Stop-AL 'synthetic readiness refusal' 1 } }
        { Invoke-ALInstallerDesktop $Fixture.Root $Fixture.Data $Fixture.Package } | Should -Throw '*rollback could not be verified*'
        $journal=Get-Content (Join-Path $Fixture.Root '.setup-state/journal.json') -Raw | ConvertFrom-Json
        $journal.phase | Should -Be 'manual_recovery_required'
        Test-Path (Join-Path $journal.run 'previous.exe') | Should -BeTrue
    }
    It 'never silently switches the data directory on a completed installation' {
        $null=Invoke-ALInstallerDesktop $Fixture.Root $Fixture.Data $Fixture.Package
        $different=Join-Path (Split-Path $Fixture.Data) 'different-data'; New-Item -ItemType Directory $different | Out-Null
        { Invoke-ALInstallerDesktop $Fixture.Root $different $Fixture.Package } | Should -Throw '*configuration is never silently replaced*'
    }
    It 'refuses downgrades through the helper independently of Setup registry checks' {
        $path=Join-Path $Fixture.Root 'build-manifest.json'; $old=Get-Content $path -Raw | ConvertFrom-Json
        $old | Add-Member file_version @(2,0,0,2); $old | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 $path
        $script:Manifest | Add-Member file_version @(2,0,0,1)
        { Invoke-ALInstallerDesktop $Fixture.Root $Fixture.Data $Fixture.Package } | Should -Throw '*downgrades*'
        Should -Invoke -ModuleName $M Invoke-ALDesktopProbe -Times 0
    }
    It 'fails closed when the installed manifest or executable cannot prove its identity' {
        [IO.File]::WriteAllText((Join-Path $Fixture.Root 'AuthLens.exe'),'tampered')
        { Invoke-ALInstallerDesktop $Fixture.Root $Fixture.Data $Fixture.Package } | Should -Throw '*does not match*'
    }
    It 'refuses overlapping data and program roots' {
        { Invoke-ALInstallerDesktop $Fixture.Root (Join-Path $Fixture.Root 'data') $Fixture.Package } | Should -Throw '*outside its program directory*'
    }
    It 'refuses protected legacy paths without running any native operation' {
        { Assert-ALInstallerPath 'C:\saplens2\data' } | Should -Throw '*Protected legacy*'
        { Assert-ALInstallerPath 'C:\sap-lens\migration' } | Should -Throw '*Protected legacy*'
    }
    It 'refuses an unsafe private state audit before replacement' {
        Mock -ModuleName $M Assert-ALAclPlan { Stop-AL 'synthetic broad ACL refusal' }
        { Invoke-ALInstallerDesktop $Fixture.Root $Fixture.Data $Fixture.Package } | Should -Throw '*broad ACL refusal*'
        [IO.File]::ReadAllText((Join-Path $Fixture.Root 'AuthLens.exe')) | Should -Be 'old'
    }
    It 'delegates Server installation to the existing locked state machine with mandatory rollback proof' {
        Mock -ModuleName $M Initialize-ALInstallerServerRoot { }
        Mock -ModuleName $M Enter-ALLock { }
        Mock -ModuleName $M Exit-ALLock { }
        Mock -ModuleName $M New-ALRun { }
        Mock -ModuleName $M Publish-ALRelease { $script:Fixture.Package }
        Mock -ModuleName $M Invoke-ALDeploy { }
        Invoke-ALInstallerServer ([pscustomobject]@{}) $Fixture.Package
        Should -Invoke -ModuleName $M Invoke-ALDeploy -Times 1 -ParameterFilter { $FirstInstall -and $RequireRollback }
        Should -Invoke -ModuleName $M Exit-ALLock -Times 1
    }
    It 'recovers a packaged Server without Git, a new payload or reinitializing its directories' {
        Mock -ModuleName $M Assert-ALInstallerServerConfiguration { }
        Mock -ModuleName $M Get-ALAclPlan { @() }
        Mock -ModuleName $M Enter-ALLock { }
        Mock -ModuleName $M Exit-ALLock { }
        Mock -ModuleName $M New-ALRun { }
        Mock -ModuleName $M Initialize-ALInstallerServerRoot { throw 'Recovery must not initialize directories.' }
        Mock -ModuleName $M Invoke-ALRecover { [pscustomobject]@{recovered=$true} }
        (Invoke-ALInstallerServer ([pscustomobject]@{}) '' -Recover).recovered | Should -BeTrue
        Should -Invoke -ModuleName $M Get-ALInstallerPackage -Times 0
        Should -Invoke -ModuleName $M Invoke-ALRecover -Times 1
        Should -Invoke -ModuleName $M Exit-ALLock -Times 1
    }
}
