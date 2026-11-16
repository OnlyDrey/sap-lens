# Pester 5 tests for scripts/start-server-test.ps1. Run: Invoke-Pester experiments/dotnet-backend/scripts/tests
# Synthetic files only: fake releases, certificates and password files live in TestDrive; nothing is installed or started for real.
BeforeAll {
    $script:Launcher = (Resolve-Path (Join-Path $PSScriptRoot '..\start-server-test.ps1')).Path
    . $script:Launcher

    function New-FakeRelease([string]$Root, [string]$Name, [datetime]$Built, [string[]]$Skip = @(), [switch]$NoManifest, [string]$ExeContent = '', [switch]$Legacy) {
        $layout = if ($Legacy) { $script:Layouts[1] } else { $script:Layouts[0] }
        $server = Join-Path (Join-Path $Root $Name) $layout.Folder
        New-Item -ItemType Directory -Force $server | Out-Null
        foreach ($file in $layout.Required) { if ($Skip -notcontains $file) { Set-Content -LiteralPath (Join-Path $server $file) -Value 'x' } }
        if ($ExeContent) {
            [System.IO.File]::WriteAllText((Join-Path $server 'SapLens.Api.exe'), $ExeContent.Replace("`r`n", "`n"))
            if ([System.IO.Path]::DirectorySeparatorChar -eq '/') { & chmod +x (Join-Path $server 'SapLens.Api.exe') }
        }
        if (-not $NoManifest) {
            $manifest = Join-Path (Join-Path $Root $Name) $layout.Manifest
            Set-Content -LiteralPath $manifest -Value '{"source_sha":"0123456789abcdef","source_dirty":false}'
            (Get-Item -LiteralPath $manifest).LastWriteTimeUtc = $Built
        }
        Join-Path $Root $Name
    }

    function Get-FreePort {
        $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0); $l.Start(); $p = $l.LocalEndpoint.Port; $l.Stop(); $p
    }
}

Describe 'Release selection' {
    BeforeEach {
        $builds = Join-Path $TestDrive ([guid]::NewGuid().ToString('n'))
        New-Item -ItemType Directory $builds | Out-Null
    }

    It 'selects the newest complete release and skips incomplete or unfinished ones' {
        New-FakeRelease $builds 'r1-old' ([datetime]'2026-11-01T10:00:00Z') | Out-Null
        $expected = New-FakeRelease $builds 'r2-good' ([datetime]'2026-11-10T10:00:00Z')
        New-FakeRelease $builds 'r3-missing-runtime' ([datetime]'2026-11-12T10:00:00Z') -Skip 'e_sqlite3.dll' | Out-Null
        New-FakeRelease $builds 'r3b-legacy-incomplete' ([datetime]'2026-11-12T11:00:00Z') -Legacy -Skip 'hostfxr.dll' | Out-Null
        New-FakeRelease $builds 'r4-interrupted' ([datetime]'2026-11-13T10:00:00Z') -NoManifest | Out-Null
        New-Item -ItemType Directory (Join-Path $builds 'r5-empty') | Out-Null
        $release = Resolve-ServerRelease -BuildsRoot $builds -ReleasePath ''
        $release.Release | Should -Be (Get-Item $expected).FullName
        $release.Executable | Should -Be (Join-Path (Join-Path $expected 'server') 'SapLens.Api.exe')
        $release.Layout | Should -Be 'single-file'
    }

    It 'still recognizes earlier folder-publish releases' {
        $legacy = New-FakeRelease $builds 'legacy' ([datetime]'2026-11-20T10:00:00Z') -Legacy
        New-FakeRelease $builds 'current' ([datetime]'2026-11-10T10:00:00Z') | Out-Null
        $release = Resolve-ServerRelease -BuildsRoot $builds -ReleasePath ''
        $release.Release | Should -Be (Get-Item $legacy).FullName
        $release.Layout | Should -Be 'folder'
        $release.Server | Should -Be (Join-Path (Get-Item $legacy).FullName 'server-win-x64')
    }

    It 'fails when no complete release exists' {
        New-FakeRelease $builds 'broken' ([datetime]'2026-11-10T10:00:00Z') -Skip 'SapLens.Api.exe' | Out-Null
        { Resolve-ServerRelease -BuildsRoot $builds -ReleasePath '' } | Should -Throw '*No complete Server release*'
        { Resolve-ServerRelease -BuildsRoot (Join-Path $builds 'absent') -ReleasePath '' } | Should -Throw '*does not exist*'
    }

    It 'accepts -ReleasePath as the release folder or its server folder and validates it' {
        $release = New-FakeRelease $builds 'manual' ([datetime]'2026-11-10T10:00:00Z')
        (Resolve-ServerRelease -BuildsRoot 'unused' -ReleasePath $release).Server | Should -Be (Join-Path (Get-Item $release).FullName 'server')
        (Resolve-ServerRelease -BuildsRoot 'unused' -ReleasePath (Join-Path $release 'server')).Release | Should -Be (Get-Item $release).FullName
        $broken = New-FakeRelease $builds 'broken' ([datetime]'2026-11-10T10:00:00Z') -Skip 'e_sqlite3.dll'
        { Resolve-ServerRelease -BuildsRoot 'unused' -ReleasePath $broken } | Should -Throw '*missing*e_sqlite3.dll*'
        $legacyBroken = New-FakeRelease $builds 'legacy-broken' ([datetime]'2026-11-10T10:00:00Z') -Legacy -Skip 'e_sqlite3.dll', 'coreclr.dll'
        { Resolve-ServerRelease -BuildsRoot 'unused' -ReleasePath $legacyBroken } | Should -Throw '*missing*coreclr.dll, e_sqlite3.dll*'
        $plain = Join-Path $builds 'plain-publish'; New-Item -ItemType Directory $plain | Out-Null
        foreach ($file in $script:RequiredServerFiles) { Set-Content (Join-Path $plain $file) 'x' }
        (Resolve-ServerRelease -BuildsRoot 'unused' -ReleasePath $plain).Server | Should -Be (Get-Item $plain).FullName
        { Resolve-ServerRelease -BuildsRoot 'unused' -ReleasePath (Join-Path $builds 'nope') } | Should -Throw '*does not exist*'
    }
}

Describe 'Configuration validation' {
    BeforeEach {
        $tls = Join-Path $TestDrive 'tls'; New-Item -ItemType Directory -Force $tls | Out-Null
        $cert = Join-Path $tls 'server.pfx'; Set-Content $cert 'synthetic'
        $passwordFile = Join-Path $tls 'cert-password'; Set-Content $passwordFile 'synthetic-password-value' -NoNewline
        $valid = @{ ListenAddress = '10.0.7.50'; Port = 18795; AllowedHosts = @(); DataDirectory = (Join-Path $TestDrive 'runtime-test')
                    CertificatePath = $cert; CertificatePasswordFile = $passwordFile; Release = @{ Release = (Join-Path $TestDrive 'release') } }
        Mock Get-LocalIPAddresses { [System.Net.IPAddress]::Parse('10.0.7.50') }
        Mock Test-PortAvailable { $true }
    }

    It 'accepts a valid test configuration' {
        { Assert-TestConfiguration @valid } | Should -Not -Throw
    }

    It 'refuses <Name>' -ForEach @(
        @{ Name = 'a host name as listen address'; Change = @{ ListenAddress = 'server.lan' }; Message = '*must be an IP address*' }
        @{ Name = 'all interfaces'; Change = @{ ListenAddress = '0.0.0.0' }; Message = '*one specific address*' }
        @{ Name = 'loopback'; Change = @{ ListenAddress = '127.0.0.1' }; Message = '*LAN address*' }
        @{ Name = 'an address not assigned here'; Change = @{ ListenAddress = '10.0.7.51' }; Message = '*not assigned to this machine*' }
        @{ Name = 'a port out of range'; Change = @{ Port = 70000 }; Message = '*between 1 and 65535*' }
        @{ Name = 'a wildcard allowed host'; Change = @{ AllowedHosts = @('*.corp.example') }; Message = '*not a valid -AllowedHosts*' }
        @{ Name = 'a malformed trusted proxy'; Change = @{ TrustedProxies = @('10.0.7.20, 10.0.7.21') }; Message = '*not a valid -TrustedProxies*' }
        @{ Name = 'a relative data directory'; Change = @{ DataDirectory = 'runtime-test' }; Message = '*absolute path*' }
        @{ Name = 'a network share'; Change = @{ DataDirectory = '\\server\share\data' }; Message = '*network share*' }
        @{ Name = 'a missing certificate'; Change = @{ CertificatePath = (Join-Path ([System.IO.Path]::GetTempPath()) 'saplens2-absent-test.pfx') }; Message = '*never creates certificates*' }
        @{ Name = 'a missing password file'; Change = @{ CertificatePasswordFile = (Join-Path ([System.IO.Path]::GetTempPath()) 'saplens2-absent-test-password') }; Message = '*password file*does not exist*' }
    ) {
        $config = $valid.Clone(); foreach ($key in $Change.Keys) { $config[$key] = $Change[$key] }
        { Assert-TestConfiguration @config } | Should -Throw $Message
    }

    It 'refuses a port already in use' {
        Mock Test-PortAvailable { $false }
        { Assert-TestConfiguration @valid } | Should -Throw '*already in use*'
    }

    It 'refuses an empty password file' {
        Set-Content $valid.CertificatePasswordFile '' -NoNewline
        { Assert-TestConfiguration @valid } | Should -Throw '*is empty*'
    }

    It 'refuses production, Desktop and release data locations' {
        $saved = $env:LOCALAPPDATA, $env:ProgramData
        try {
            $env:LOCALAPPDATA = Join-Path $TestDrive 'local'; $env:ProgramData = Join-Path $TestDrive 'programdata'
            foreach ($path in (Join-Path $env:ProgramData 'SapLens2/data'), (Join-Path $env:ProgramData 'SAP Lens Server'), (Join-Path $env:LOCALAPPDATA 'SAP Lens 2 Prototype/data'), (Join-Path $env:LOCALAPPDATA 'SAP LENS/x')) {
                $config = $valid.Clone(); $config.DataDirectory = $path
                { Assert-TestConfiguration @config } | Should -Throw '*production or Desktop location*'
            }
            $config = $valid.Clone(); $config.DataDirectory = Join-Path $valid.Release.Release 'data'
            { Assert-TestConfiguration @config } | Should -Throw '*inside the release folder*'
        } finally { $env:LOCALAPPDATA, $env:ProgramData = $saved }
    }
}

Describe 'Argument construction' {
    It 'uses only the supported options, defaults allowed hosts to the listen address and never includes the password' {
        $arguments = New-ServerArguments -ListenAddress '10.0.7.50' -Port 18795 -AllowedHosts @() -DataDirectory (Join-Path $TestDrive 'runtime-test') `
            -CertificatePath 'C:\ProgramData\SapLens2\tls\server.pfx' -CertificatePasswordFile 'C:\ProgramData\SapLens2\tls\cert-password'
        $arguments | Should -Be @('--data-dir', [System.IO.Path]::GetFullPath((Join-Path $TestDrive 'runtime-test')), '--network', '--listen', '10.0.7.50', '--port', '18795',
            '--allowed-hosts', '10.0.7.50', '--cert', 'C:\ProgramData\SapLens2\tls\server.pfx', '--cert-password-file', 'C:\ProgramData\SapLens2\tls\cert-password')
        (New-ServerArguments -ListenAddress '10.0.7.50' -Port 1 -AllowedHosts 'saplens2.test.example', '10.0.7.50' -DataDirectory $TestDrive -CertificatePath c -CertificatePasswordFile p)[8] |
            Should -Be 'saplens2.test.example,10.0.7.50'
    }

    It 'adds --trusted-proxies only when -TrustedProxies is given' {
        $plain = New-ServerArguments -ListenAddress '10.0.7.50' -Port 18795 -AllowedHosts @() -DataDirectory $TestDrive -CertificatePath c -CertificatePasswordFile p
        $plain | Should -Not -Contain '--trusted-proxies'
        $proxied = New-ServerArguments -ListenAddress '10.0.7.50' -Port 18795 -AllowedHosts 'lens.proxy.test', '10.0.7.50' -DataDirectory $TestDrive -CertificatePath c `
            -CertificatePasswordFile p -TrustedProxies '10.0.7.20', '10.0.8.0/24'
        $proxied[-2..-1] | Should -Be @('--trusted-proxies', '10.0.7.20,10.0.8.0/24')
    }

    It 'quotes paths with spaces for display' {
        Format-CommandLine 'C:\a b\SapLens.Api.exe' @('--data-dir', 'C:\x y') | Should -Be '"C:\a b\SapLens.Api.exe" --data-dir "C:\x y"'
    }
}

Describe 'End to end with a fake Server executable' -Skip:([System.IO.Path]::DirectorySeparatorChar -ne '/') {
    # A shell script named SapLens.Api.exe stands in for the Server (Linux test hosts only): it records its arguments and exits with a chosen code.
    BeforeAll {
        $address = @(Get-LocalIPAddresses | Where-Object { $_.AddressFamily -eq 'InterNetwork' -and -not [System.Net.IPAddress]::IsLoopback($_) }) | Select-Object -First 1
        $tls = Join-Path $TestDrive 'e2e-tls'; New-Item -ItemType Directory -Force $tls | Out-Null
        $cert = Join-Path $tls 'server.pfx'; Set-Content $cert 'synthetic'
        $passwordFile = Join-Path $tls 'cert-password'; Set-Content $passwordFile 'synthetic-password-value' -NoNewline
        $record = Join-Path $TestDrive 'arguments.txt'
        function Invoke-Launcher([string]$Builds, [string[]]$Extra) {
            $output = & pwsh -NoProfile -NonInteractive -File $script:Launcher -BuildsRoot $Builds -ListenAddress $address.ToString() -Port (Get-FreePort) `
                -DataDirectory (Join-Path $TestDrive 'runtime-test') -CertificatePath $cert -CertificatePasswordFile $passwordFile @Extra 2>&1
            @{ Code = $LASTEXITCODE; Output = ($output | Out-String) }
        }
    }

    It 'runs the Server in the foreground with the documented arguments and returns its exit code' {
        if (-not $address) { Set-ItResult -Skipped -Because 'no non-loopback IPv4 address on this host'; return }
        $builds = Join-Path $TestDrive 'builds-ok'
        New-FakeRelease $builds 'r1' ([datetime]'2026-11-10T10:00:00Z') -ExeContent "#!/bin/sh`nprintf '%s\n' `"`$@`" > '$record'`necho 'Listening (fake)'`nexit 0`n" | Out-Null
        $run = Invoke-Launcher $builds @()
        $run.Code | Should -Be 0
        $run.Output | Should -Match 'Listening \(fake\)'
        $run.Output | Should -Not -Match 'synthetic-password-value'
        $recorded = Get-Content $record
        $recorded | Should -Contain '--network'
        $recorded | Should -Contain '--cert-password-file'
        $recorded -join ' ' | Should -Not -Match 'synthetic-password-value'
    }

    It 'propagates a startup refusal (exit code 3) from the Server' {
        if (-not $address) { Set-ItResult -Skipped -Because 'no non-loopback IPv4 address on this host'; return }
        $builds = Join-Path $TestDrive 'builds-refused'
        New-FakeRelease $builds 'r1' ([datetime]'2026-11-10T10:00:00Z') -ExeContent "#!/bin/sh`necho 'startup refused: synthetic reason' >&2`nexit 3`n" | Out-Null
        $run = Invoke-Launcher $builds @()
        $run.Code | Should -Be 3
        $run.Output | Should -Match 'startup refused: synthetic reason'
        $run.Output | Should -Match 'exited with code 3'
    }

    It 'validates and prints the command without starting anything in -DryRun, and exits 2 when it refuses' {
        if (-not $address) { Set-ItResult -Skipped -Because 'no non-loopback IPv4 address on this host'; return }
        $builds = Join-Path $TestDrive 'builds-dry'
        New-FakeRelease $builds 'r1' ([datetime]'2026-11-10T10:00:00Z') -ExeContent "#!/bin/sh`ntouch '$TestDrive/started'`nexit 0`n" | Out-Null
        $run = Invoke-Launcher $builds @('-DryRun')
        $run.Code | Should -Be 0
        $run.Output | Should -Match 'Dry run: configuration valid'
        $run.Output | Should -Match '--cert-password-file'
        $run.Output | Should -Not -Match 'synthetic-password-value'
        Test-Path (Join-Path $TestDrive 'started') | Should -BeFalse
        Test-Path (Join-Path $TestDrive 'runtime-test') | Should -BeFalse
        $refused = Invoke-Launcher (Join-Path $TestDrive 'no-builds') @('-DryRun')
        $refused.Code | Should -Be 2
        $refused.Output | Should -Match 'start-server-test: Builds folder'
    }
}

Describe 'Release verification' {
    BeforeAll {
        $script:Verify = (Resolve-Path (Join-Path $PSScriptRoot '..\verify-release.ps1')).Path
        function New-VerifiableRelease([string]$Path) {
            New-Item -ItemType Directory -Force (Join-Path $Path 'server'), (Join-Path $Path 'desktop') | Out-Null
            Set-Content (Join-Path $Path 'server/SapLens.Api.exe') 'server'; Set-Content (Join-Path $Path 'server/e_sqlite3.dll') 'sqlite'
            Set-Content (Join-Path $Path 'desktop/SapLens2Prototype.exe') 'desktop'; Set-Content (Join-Path $Path 'README.txt') 'readme'
            $artifacts = foreach ($relative in 'README.txt', 'desktop/SapLens2Prototype.exe', 'server/SapLens.Api.exe', 'server/e_sqlite3.dll') {
                $file = Get-Item (Join-Path $Path $relative)
                [ordered]@{ path = $relative; bytes = $file.Length; sha256 = (Get-FileHash $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
            }
            $manifest = [ordered]@{ source_sha = 'abc'; build_timestamp_utc = '2026-11-16T10:00:00Z'; target_platform = 'win-x64'
                executables = [ordered]@{ server = 'server/SapLens.Api.exe'; desktop = 'desktop/SapLens2Prototype.exe' }; artifacts = @($artifacts) }
            [System.IO.File]::WriteAllText((Join-Path $Path 'build-manifest.json'), ($manifest | ConvertTo-Json -Depth 5))
            $sums = foreach ($relative in @('build-manifest.json') + @($artifacts | ForEach-Object { $_.path })) {
                '{0}  ./{1}' -f (Get-FileHash (Join-Path $Path $relative) -Algorithm SHA256).Hash.ToLowerInvariant(), $relative }
            [System.IO.File]::WriteAllText((Join-Path $Path 'SHA256SUMS'), (($sums -join "`n") + "`n"))
        }
        function Invoke-Verify([string]$Path) {
            $output = & pwsh -NoProfile -NonInteractive -File $script:Verify -ReleasePath $Path 2>&1
            @{ Code = $LASTEXITCODE; Output = ($output | Out-String) }
        }
    }

    It 'accepts an intact release' {
        $path = Join-Path $TestDrive 'intact'; New-VerifiableRelease $path
        $run = Invoke-Verify $path
        $run.Code | Should -Be 0
        $run.Output | Should -Match 'Release verified: 4 artifacts'
    }

    It 'detects <Name>' -ForEach @(
        @{ Name = 'a modified executable'; Change = { param($p) Add-Content (Join-Path $p 'server/SapLens.Api.exe') 'tampered' }; Message = 'differs: server/SapLens.Api.exe' }
        @{ Name = 'a missing native library'; Change = { param($p) Remove-Item (Join-Path $p 'server/e_sqlite3.dll') }; Message = 'missing: server/e_sqlite3.dll' }
        @{ Name = 'an added file'; Change = { param($p) Set-Content (Join-Path $p 'server/appsettings.json') '{}' }; Message = 'not in the manifest: server/appsettings.json' }
        @{ Name = 'an edited manifest'; Change = { param($p) Add-Content (Join-Path $p 'build-manifest.json') ' ' }; Message = 'SHA256SUMS checksum differs: build-manifest.json' }
    ) {
        $path = Join-Path $TestDrive ([guid]::NewGuid().ToString('n')); New-VerifiableRelease $path
        & $Change $path
        $run = Invoke-Verify $path
        $run.Code | Should -Be 1
        $run.Output | Should -Match ([regex]::Escape($Message))
    }
}
