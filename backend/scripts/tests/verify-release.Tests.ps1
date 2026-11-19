# Release verification (verify-release.ps1): the schema-1 manifest contract for full Windows and Linux releases, and server deployment packages
# (-Scope Server) as Publish-ALRelease writes them, including packages published before deployment-package.json existed.
Describe 'Release verification' {
    BeforeAll { . (Join-Path $PSScriptRoot 'ReleaseFixture.ps1') }

    It 'accepts an intact release' {
        $path = Join-Path $TestDrive 'AuthLens-2.0.0-alpha.1-20261116-100000-abc1234-win-x64'; New-VerifiableRelease $path
        $run = Invoke-Verify $path
        $run.Code | Should -Be 0
        $run.Output | Should -Match 'Release verified: 5 artifacts'
    }

    It 'accepts the same contract for <Platform>, with its platform-specific executables' -ForEach @(
        @{ Platform = 'win-x64'; Artifacts = 5 }, @{ Platform = 'linux-x64'; Artifacts = 2 }
    ) {
        $path = Join-Path $TestDrive "AuthLens-2.0.0-alpha.1-20261116-100000-aaaaaaa-$Platform"; New-VerifiableRelease $path $Platform
        $run = Invoke-Verify $path
        $run.Code | Should -Be 0
        $run.Output | Should -Match "Release verified: $Artifacts artifacts, commit a{40}, built 2026-11-16T10:00:00Z for $Platform"
    }

    It 'keeps verifying a release built before the rename to AuthLens' {
        $path = Join-Path $TestDrive 'SAP-Lens-2-2.0.0-alpha.1-20261117-100000-aaaaaaa-win-x64'; New-VerifiableRelease $path -Historical
        (Invoke-Verify $path).Code | Should -Be 0
    }

    It 'refuses <Name> in a Linux release' -ForEach @(
        @{ Name = 'a Desktop executable'; Change = { param($m) $m.executables | Add-Member desktop 'desktop/AuthLens.exe' }; Message = 'linux-x64: a Desktop executable is listed' }
        @{ Name = 'Desktop native libraries'; Change = { param($m) $m.publish | Add-Member desktop_native_libraries 'bundled' }; Message = 'linux-x64: publish.desktop_native_libraries is listed' }
        @{ Name = 'the Windows server executable'; Change = { param($m) $m.executables.server = 'server/AuthLens.Api.exe' }; Message = 'linux-x64: executables.server is not server/AuthLens.Api' }
    ) {
        $path = Join-Path $TestDrive "AuthLens-2.0.0-alpha.1-20261116-100000-aaaaaaa-$([guid]::NewGuid().ToString('n').Substring(0, 6))-linux-x64"; New-VerifiableRelease $path 'linux-x64'
        Edit-Manifest $path $Change
        $run = Invoke-Verify $path
        $run.Code | Should -Be 1
        $run.Output | Should -Match ([regex]::Escape($Message))
    }

    It 'refuses a folder name for another platform' {
        $path = Join-Path $TestDrive 'AuthLens-2.0.0-alpha.1-20261116-100000-aaaaaaa-linux-x64'; New-VerifiableRelease $path 'win-x64'
        $run = Invoke-Verify $path
        $run.Code | Should -Be 1
        $run.Output | Should -Match 'does not end with the platform win-x64'
    }

    It 'refuses a folder name that carries another version' {
        $path = Join-Path $TestDrive 'AuthLens-2.0.0-alpha.2-20261116-100000-abc1234-win-x64'; New-VerifiableRelease $path
        $run = Invoke-Verify $path
        $run.Code | Should -Be 1
        $run.Output | Should -Match 'does not carry version 2.0.0-alpha.1'
    }

    It 'detects <Name>' -ForEach @(
        @{ Name = 'a modified executable'; Change = { param($p) Add-Content (Join-Path $p 'server/AuthLens.Api.exe') 'tampered' }; Message = 'differs: server/AuthLens.Api.exe' }
        @{ Name = 'a missing native library'; Change = { param($p) Remove-Item (Join-Path $p 'server/e_sqlite3.dll') }; Message = 'missing: server/e_sqlite3.dll' }
        @{ Name = 'an added file'; Change = { param($p) Set-Content (Join-Path $p 'server/appsettings.json') '{}' }; Message = 'not in the manifest: server/appsettings.json' }
        @{ Name = 'an edited manifest'; Change = { param($p) Add-Content (Join-Path $p 'build-manifest.json') ' ' }; Message = 'SHA256SUMS checksum differs: build-manifest.json' }
        @{ Name = 'a file version that does not follow from the version'; Change = { param($p) $m = Get-Content (Join-Path $p 'build-manifest.json') -Raw | ConvertFrom-Json; $m.file_version = @(2, 0, 0, 7); [System.IO.File]::WriteAllText((Join-Path $p 'build-manifest.json'), ($m | ConvertTo-Json -Depth 5)) }; Message = 'does not follow from version 2.0.0-alpha.1' }
        @{ Name = 'an invalid version'; Change = { param($p) $m = Get-Content (Join-Path $p 'build-manifest.json') -Raw | ConvertFrom-Json; $m.version = '0.0.0-experiment'; [System.IO.File]::WriteAllText((Join-Path $p 'build-manifest.json'), ($m | ConvertTo-Json -Depth 5)) }; Message = "manifest version '0.0.0-experiment' is not" }
        @{ Name = 'a missing required field'; Change = { param($p) Edit-Manifest $p { param($m) $m.PSObject.Properties.Remove('node') } }; Message = 'manifest field missing: node' }
        @{ Name = 'another schema'; Change = { param($p) Edit-Manifest $p { param($m) $m.schema = 2 } }; Message = "manifest schema '2' is not 1" }
        @{ Name = 'another product'; Change = { param($p) Edit-Manifest $p { param($m) $m.product = 'Other' } }; Message = "manifest product 'Other' is not AuthLens" }
        @{ Name = 'a short commit id'; Change = { param($p) Edit-Manifest $p { param($m) $m.source_sha = 'abc1234' } }; Message = 'is not a 40-character commit id' }
        @{ Name = 'a channel that does not follow from the version'; Change = { param($p) Edit-Manifest $p { param($m) $m.channel = 'stable' } }; Message = "manifest channel 'stable' does not follow" }
        @{ Name = 'a dirty flag that is not a boolean'; Change = { param($p) Edit-Manifest $p { param($m) $m.source_dirty = 'no' } }; Message = 'source_dirty is not true or false' }
        @{ Name = 'an invalid build time'; Change = { param($p) Edit-Manifest $p { param($m) $m.build_timestamp_utc = 'yesterday' } }; Message = 'build_timestamp_utc is not a timestamp' }
        @{ Name = 'an unknown platform'; Change = { param($p) Edit-Manifest $p { param($m) $m.target_platform = 'osx-arm64' } }; Message = "target_platform 'osx-arm64' is not win-x64 or linux-x64" }
        @{ Name = 'a Windows release without the Desktop'; Change = { param($p) Edit-Manifest $p { param($m) $m.executables.PSObject.Properties.Remove('desktop') } }; Message = 'win-x64: executables.desktop is missing' }
        @{ Name = 'a trimmed publish'; Change = { param($p) Edit-Manifest $p { param($m) $m.publish.trimmed = $true } }; Message = 'publish.trimmed is not false' }
        @{ Name = 'an artifact path outside the release'; Change = { param($p) Edit-Manifest $p { param($m) $m.artifacts[0].path = '../outside.txt' } }; Message = "artifact path not allowed: '../outside.txt'" }
        @{ Name = 'an artifact with an invalid checksum'; Change = { param($p) Edit-Manifest $p { param($m) $m.artifacts[0].sha256 = 'ABC' } }; Message = 'artifact metadata invalid: desktop/AuthLens.exe' }
        @{ Name = 'SHA256SUMS without an artifact'; Change = { param($p) $f = Join-Path $p 'SHA256SUMS'; [System.IO.File]::WriteAllText($f, ((Get-Content $f | Where-Object { $_ -notmatch 'README' }) -join "`n") + "`n") }; Message = 'SHA256SUMS does not cover README.txt' }
    ) {
        $path = Join-Path $TestDrive ([guid]::NewGuid().ToString('n')); New-VerifiableRelease $path
        & $Change $path
        $run = Invoke-Verify $path
        $run.Code | Should -Be 1
        $run.Output | Should -Match ([regex]::Escape($Message))
    }

    It 'refuses a server package in full scope and names each missing artifact' {
        $path = Join-Path $TestDrive 'AuthLens-2.0.0-alpha.1-20261118-070450-aaaaaaa-win-x64'; New-HistoricalPackage $path
        $run = Invoke-Verify $path
        $run.Code | Should -Be 1
        $run.Output | Should -Match 'missing: desktop/AuthLens.exe'
        $run.Output | Should -Match 'missing: symbols/server/AuthLens.Api.pdb'
    }
}

Describe 'Server deployment packages (verify-release.ps1 -Scope Server)' {
    BeforeAll { . (Join-Path $PSScriptRoot 'ReleaseFixture.ps1') }

    It 'verifies an undeclared package published before deployment-package.json, naming every omitted file' {
        $path = Join-Path $TestDrive 'AuthLens-2.0.0-alpha.1-20261118-070450-aaaaaaa-win-x64'; New-HistoricalPackage $path
        $run = Invoke-Verify $path 'Server'
        $run.Code | Should -Be 0
        $run.Output | Should -Match 'server package \(undeclared: published before deployment-package.json existed\): 3 of 5 artifacts present and matching, 2 omitted'
        $run.Output | Should -Match 'omitted \(not part of a server package\): desktop/AuthLens.exe'
        $run.Output | Should -Match 'omitted \(not part of a server package\): symbols/server/AuthLens.Api.pdb'
    }

    It 'verifies an undeclared package of a release built before the rename' {
        $path = Join-Path $TestDrive 'SAP-Lens-2-2.0.0-alpha.1-20261117-100000-aaaaaaa-win-x64'; New-VerifiableRelease $path -Historical
        foreach ($tree in 'desktop', 'symbols') { Remove-Item -LiteralPath (Join-Path $path $tree) -Recurse -Force }
        (Invoke-Verify $path 'Server').Code | Should -Be 0
    }

    It 'never accepts a missing <Name> in a server package' -ForEach @(
        @{ Name = 'server file'; File = 'server/e_sqlite3.dll' }, @{ Name = 'server executable'; File = 'server/AuthLens.Api.exe' }, @{ Name = 'README'; File = 'README.txt' }
    ) {
        $path = Join-Path $TestDrive ([guid]::NewGuid().ToString('n')); New-HistoricalPackage $path
        Remove-Item -LiteralPath (Join-Path $path $File)
        $run = Invoke-Verify $path 'Server'
        $run.Code | Should -Be 1
        $run.Output | Should -Match ([regex]::Escape("missing: $File"))
    }

    It 'refuses a server package whose files or manifest no longer match' -ForEach @(
        @{ Name = 'a modified server executable'; Change = { param($p) Add-Content (Join-Path $p 'server/AuthLens.Api.exe') 'x' }; Message = 'checksum differs: server/AuthLens.Api.exe' }
        @{ Name = 'an edited manifest'; Change = { param($p) Add-Content (Join-Path $p 'build-manifest.json') ' ' }; Message = 'SHA256SUMS checksum differs: build-manifest.json' }
        @{ Name = 'an added file'; Change = { param($p) Set-Content (Join-Path $p 'server/extra.dll') 'x' }; Message = 'not in the manifest: server/extra.dll' }
    ) {
        $path = Join-Path $TestDrive ([guid]::NewGuid().ToString('n')); New-HistoricalPackage $path
        & $Change $path
        $run = Invoke-Verify $path 'Server'
        $run.Code | Should -Be 1
        $run.Output | Should -Match ([regex]::Escape($Message))
    }

    Context 'packages published by Publish-ALRelease' {
        BeforeAll { Import-TestDeploymentModule }
        AfterAll { Remove-Module AuthLens.Deploy -ErrorAction SilentlyContinue }

        It 'publishes the server package with its declaration, verifies it before it appears, and reuses it' {
            $build = Join-Path $TestDrive 'build/AuthLens-2.0.0-alpha.1-20261119-055432-aaaaaaa-win-x64'; New-VerifiableRelease $build
            $config = [pscustomobject]@{ ReleasesRoot = (Join-Path $TestDrive 'releases') }
            $manifest = Get-Content (Join-Path $build 'build-manifest.json') -Raw | ConvertFrom-Json
            $published = Publish-ALRelease $config $build $manifest
            Test-Path (Join-Path $config.ReleasesRoot '.staging') | Should -BeFalse
            @(Get-ChildItem $published -Recurse -File | ForEach-Object { $_.FullName.Substring($published.Length + 1).Replace('\', '/') } | Sort-Object) |
                Should -Be @('build-manifest.json', 'deployment-package.json', 'README.txt', 'server/AuthLens.Api.exe', 'server/e_sqlite3.dll', 'SHA256SUMS')
            $declaration = Get-Content (Join-Path $published 'deployment-package.json') -Raw | ConvertFrom-Json
            $declaration.kind | Should -Be 'server'
            @($declaration.omitted) | Should -Be @('desktop/AuthLens.exe', 'symbols/server/AuthLens.Api.pdb')
            (Get-FileHash (Join-Path $published 'build-manifest.json')).Hash | Should -Be (Get-FileHash (Join-Path $build 'build-manifest.json')).Hash   # never rewritten
            $run = Invoke-Verify $published 'Server'
            $run.Code | Should -Be 0; $run.Output | Should -Match 'declared by deployment-package.json'
            (Invoke-Verify $published).Output | Should -Match 'this is a server deployment package'
            Publish-ALRelease $config $build $manifest | Should -Be $published
        }

        It 'never publishes an incomplete build: the staging copy is kept for inspection and no release appears' {
            $build = Join-Path $TestDrive 'broken/AuthLens-2.0.0-alpha.1-20261119-060000-aaaaaaa-win-x64'; New-VerifiableRelease $build
            Add-Content (Join-Path $build 'server/e_sqlite3.dll') 'corrupted after the build'
            $config = [pscustomobject]@{ ReleasesRoot = (Join-Path $TestDrive 'releases-broken') }
            $manifest = Get-Content (Join-Path $build 'build-manifest.json') -Raw | ConvertFrom-Json
            { Publish-ALRelease $config $build $manifest } | Should -Throw '*failed verification and was not published*'
            Test-Path (Join-Path $config.ReleasesRoot (Split-Path $build -Leaf)) | Should -BeFalse
            Test-Path (Join-Path $config.ReleasesRoot ".staging/$(Split-Path $build -Leaf)") | Should -BeTrue
            { Publish-ALRelease $config $build $manifest } | Should -Throw '*remains from an interrupted publication*'
        }

        It 'refuses to reuse an existing folder of the same commit that does not verify, and leaves it unchanged' {
            $build = Join-Path $TestDrive 'again/AuthLens-2.0.0-alpha.1-20261118-070450-aaaaaaa-win-x64'; New-VerifiableRelease $build
            $config = [pscustomobject]@{ ReleasesRoot = (Join-Path $TestDrive 'releases-existing') }
            $existing = Join-Path $config.ReleasesRoot (Split-Path $build -Leaf); New-HistoricalPackage $existing
            Remove-Item (Join-Path $existing 'server/e_sqlite3.dll')
            $before = @(Get-ChildItem $existing -Recurse -File).Count
            $manifest = Get-Content (Join-Path $build 'build-manifest.json') -Raw | ConvertFrom-Json
            { Publish-ALRelease $config $build $manifest } | Should -Throw '*does not verify as a server package*'
            @(Get-ChildItem $existing -Recurse -File).Count | Should -Be $before
        }
    }

    It 'refuses a declaration that disagrees with the package' -ForEach @(
        @{ Name = 'another omitted list'; Change = { param($d) $d.omitted = @('desktop/AuthLens.exe') }; Message = 'declares other omitted files than are absent' }
        @{ Name = 'another manifest'; Change = { param($d) $d.build_manifest_sha256 = ('0' * 64) }; Message = 'names another build-manifest.json' }
        @{ Name = 'another kind'; Change = { param($d) $d.kind = 'full' }; Message = 'not a schema-1 server package declaration' }
    ) {
        $path = Join-Path $TestDrive ([guid]::NewGuid().ToString('n')); New-HistoricalPackage $path
        $declaration = [pscustomobject]@{ schema = 1; kind = 'server'; source_release = (Split-Path $path -Leaf); build_manifest_sha256 = (Get-FileHash (Join-Path $path 'build-manifest.json')).Hash.ToLowerInvariant()
            omitted = @('desktop/AuthLens.exe', 'symbols/server/AuthLens.Api.pdb'); created_utc = '2026-11-19T00:00:00Z' }
        & $Change $declaration
        [System.IO.File]::WriteAllText((Join-Path $path 'deployment-package.json'), ($declaration | ConvertTo-Json))
        $run = Invoke-Verify $path 'Server'
        $run.Code | Should -Be 1
        $run.Output | Should -Match ([regex]::Escape($Message))
    }
}

