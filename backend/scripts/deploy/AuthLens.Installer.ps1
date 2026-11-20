# Installer adapters for the existing release verifier, deployment journal and application backup engine.
# No service or file operations occur on import. Setup payloads and failed runs are never reused or overwritten.
$script:InstallerTools = @('Install-AuthLens.ps1','verify-release.ps1','deploy/AuthLens.Deploy.psm1','deploy/Deploy-AuthLens.ps1','deploy/AuthLens.Paths.ps1','deploy/AuthLens.Acl.ps1','deploy/AuthLens.Installer.ps1')
function Save-ALInstallerRecoveryTools([string]$Run) {
    $tools = Join-AL $Run 'recovery-tools'
    $entries = foreach ($relative in $script:InstallerTools) {
        $source = Join-AL (Split-Path $PSScriptRoot) ($relative -replace '/', [IO.Path]::DirectorySeparatorChar)
        $target = Join-AL $tools ($relative -replace '/', [IO.Path]::DirectorySeparatorChar)
        New-Item -ItemType Directory -Force (Split-Path $target) | Out-Null
        Copy-Item -LiteralPath $source -Destination $target
        [ordered]@{path=$relative;sha256=(Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()}
    }
    [IO.File]::WriteAllText((Join-AL $tools 'installer-tools.json'),(@{schema=1;files=@($entries)} | ConvertTo-Json -Depth 5))
}
function Assert-ALInstallerPath([string]$Path) {
    if (-not [IO.Path]::IsPathRooted($Path) -or $Path.StartsWith('\\') -or $Path.StartsWith('//')) { Stop-AL 'Installer paths must be absolute local paths.' }
    $full = [IO.Path]::GetFullPath($Path).TrimEnd('\','/')
    if (Test-ALAclForbidden $full) { Stop-AL 'Global Windows directories are not installer targets.' }
    if ($env:SystemRoot -and (Test-ALPathWithin $full $env:SystemRoot)) { Stop-AL 'Windows system directories are protected.' }
    if ($full.Length -lt 4 -or $full -match '^(?i)C:\\saplens2($|\\)|^(?i)C:\\sap-lens($|\\)') { Stop-AL 'Protected legacy installations and drive roots are never installer targets.' }
    $local = [Environment]::GetFolderPath('LocalApplicationData')
    foreach ($old in 'SAP Lens','SAP Lens Desktop','SAP Lens 2 Prototype','Programs\SAP Lens','Programs\SAP Lens Desktop') {
        if ($local -and (Test-ALPathWithin $full (Join-AL $local $old))) { Stop-AL 'Earlier product profiles are protected.' }
    }
    Test-ALPathTree $full
}

function Get-ALInstallerPackage([string]$Package) {
    Assert-ALInstallerPath $Package
    $null = @(Get-ALTreeFiles $Package)
    $verifier = Join-AL (Split-Path $PSScriptRoot) 'verify-release.ps1'
    $result = Invoke-ALProcess (Get-ALShell) @('-NoProfile','-NonInteractive','-File',$verifier,'-ReleasePath',$Package) ''
    if ($result.ExitCode -ne 0) { Stop-AL 'Installer package integrity verification failed; no installed files were replaced.' }
    $manifest = Get-Content -LiteralPath (Join-AL $Package 'build-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.product -cne 'AuthLens' -or $manifest.target_platform -ne 'win-x64' -or $manifest.source_dirty) { Stop-AL 'Only a clean AuthLens Windows package may be installed.' }
    $manifest
}

function Invoke-ALInstallerServer($Config, [string]$Package, [switch]$Recover) {
    # All SCM calls remain in the existing state machine. Explicit configuration is required, even on first install.
    if ($Recover) {
        Assert-ALInstallerServerConfiguration $Config
        $null=Assert-ALAclPlan (Get-ALAclPlan $Config) 'Server installer recovery'
        Enter-ALLock $Config
        try {
            $null=New-ALRun $Config 'installer-recover'
            Save-ALInstallerRecoveryTools $script:RunFolder
            return Invoke-ALRecover $Config
        } finally { Exit-ALLock }
    }
    $manifest = Get-ALInstallerPackage $Package
    Initialize-ALInstallerServerRoot $Config
    Enter-ALLock $Config
    try {
        $null = New-ALRun $Config 'installer'
        Save-ALInstallerRecoveryTools $script:RunFolder
        $published = Publish-ALRelease $Config $Package $manifest
        Invoke-ALDeploy $Config $published $manifest.source_sha -FirstInstall -RequireRollback
    } finally { Exit-ALLock }
}

function Assert-ALInstallerServerConfiguration($Config) {
    if ($Config.ServiceName -in @('SapLens2','sap-lens','SapLens')) { Stop-AL 'Legacy services are protected.' }
    foreach ($path in $Config.Root,$Config.DataDirectory,$Config.WorkRoot,$Config.ReleasesRoot,$Config.BackupRoot,$Config.ConfigFile,$Config.CertificatePath,$Config.CertificatePasswordFile) { Assert-ALInstallerPath $path }
}
function Initialize-ALInstallerServerRoot($Config) {
    Assert-ALInstallerServerConfiguration $Config
    if (-not (Test-Path -LiteralPath $Config.Root)) { New-ALDirectoryWithAcl $Config.Root (New-ALProtectedDirectorySecurity) }
    $null=Assert-ALAclPlan @([pscustomobject]@{Path=$Config.Root;Class='private';Role='installation root';Recurse=$false}) 'Server installation root'
    Initialize-ALInstallation $Config
}

function New-ALInstallerPrivateDirectory([string]$Path) {
    Assert-ALInstallerPath $Path
    if (Test-Path -LiteralPath $Path) { Stop-AL 'Installer recovery directory already exists; it was preserved.' }
    $security = New-ALProtectedDirectorySecurity
    $security.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.WindowsIdentity]::GetCurrent().User,'FullControl','ContainerInherit, ObjectInherit','None','Allow'))
    New-ALDirectoryWithAcl $Path $security
}

function Assert-ALDesktopIdle([string]$Data) {
    $normal = Join-AL ([Environment]::GetFolderPath('LocalApplicationData')) 'AuthLens\data'
    $name = 'Local\AuthLensDesktop'
    if ([IO.Path]::GetFullPath($Data).TrimEnd('\') -ine [IO.Path]::GetFullPath($normal)) {
        $hash = [Security.Cryptography.SHA256]::Create()
        try { $suffix = ([BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes([IO.Path]::GetFullPath($Data).TrimEnd('\').ToUpperInvariant())))).Replace('-','').Substring(0,16) } finally { $hash.Dispose() }
        $name += '-' + $suffix
    }
    try { $mutex = [Threading.Mutex]::OpenExisting($name) } catch [Threading.WaitHandleCannotBeOpenedException] { return }
    $mutex.Dispose()
    Stop-AL 'Close the selected AuthLens Desktop before installing or recovering. It is never terminated.'
}

function Invoke-ALDesktopProbe([string]$Exe, [string]$Data) {
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName=$Exe; $info.Arguments='--data-dir "'+[IO.Path]::GetFullPath($Data).TrimEnd('\','/')+'" --self-check'
    $info.UseShellExecute=$false; $info.CreateNoWindow=$true; $info.RedirectStandardOutput=$true; $info.RedirectStandardError=$true
    $process=[Diagnostics.Process]::Start($info)
    try {
        $output=$process.StandardOutput.ReadToEndAsync(); $errorOutput=$process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(60000)) { Stop-AL "Owned Desktop readiness probe $($process.Id) did not exit; it was not terminated. Review its data-directory log before recovery." 4 }
        if ($process.ExitCode -ne 0) { Stop-AL 'Desktop readiness failed; see its isolated data-directory log.' 1 }
        $null=$output.GetAwaiter().GetResult(); $null=$errorOutput.GetAwaiter().GetResult()
    } finally { $process.Dispose() }
}

function Write-ALInstallerJournal([string]$Path, $Journal) {
    # Atomic checkpoints; the run's immutable previous files and encrypted backup are separate from this replaceable status.
    $temporary = $Path + '.' + [Guid]::NewGuid().ToString('N') + '.part'
    [IO.File]::WriteAllText($temporary,($Journal | ConvertTo-Json -Depth 8))
    if (Test-Path -LiteralPath $Path) { [IO.File]::Replace($temporary,$Path,($Path+'.previous-'+[Guid]::NewGuid().ToString('N'))) } else { [IO.File]::Move($temporary,$Path) }
}

function Assert-ALInstalledDesktop([string]$Root) {
    $manifest = Get-Content -LiteralPath (Join-AL $Root 'build-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $entry = @($manifest.artifacts | Where-Object path -CEQ 'desktop/AuthLens.exe')
    if ($manifest.product -cne 'AuthLens' -or $entry.Count -ne 1 -or (Get-FileHash -LiteralPath (Join-AL $Root 'AuthLens.exe') -Algorithm SHA256).Hash -ine $entry[0].sha256) { Stop-AL 'The previous Desktop executable does not match its manifest; no update is allowed.' }
    $manifest
}

function Restore-ALInstallerDesktop([string]$Root, [string]$Data, [string]$JournalPath, $Journal, [string]$MaintenanceExe) {
    Assert-ALDesktopIdle $Data
    $schema = Invoke-ALMaintenance $MaintenanceExe @('--schema-info','--data-dir',$Data)
    if ((@($Journal.applied_before) -join '|') -cne (@($schema.applied) -join '|')) { Stop-AL 'Data schema changed; automatic binary rollback is refused. Recovery evidence was preserved.' 4 }
    $old = Join-AL $Journal.run 'previous.exe'
    if (-not (Test-Path -LiteralPath $old) -or (Get-FileHash -LiteralPath $old -Algorithm SHA256).Hash -ine $Journal.previous_sha256) { Stop-AL 'Previous executable recovery proof is missing or changed.' 4 }
    if ((Get-FileHash -LiteralPath (Join-AL $Journal.run 'previous-manifest.json') -Algorithm SHA256).Hash -ine $Journal.previous_manifest_sha256) { Stop-AL 'Previous manifest recovery proof changed.' 4 }
    $next = Join-AL $Root ('restore-' + [Guid]::NewGuid().ToString('N') + '.exe')
    Copy-Item -LiteralPath $old -Destination $next
    $installed = Join-AL $Root 'AuthLens.exe'
    if (Test-Path -LiteralPath $installed) { [IO.File]::Replace($next,$installed,(Join-AL $Journal.run ('rollback-candidate-'+[Guid]::NewGuid().ToString('N')+'.exe'))) } else { [IO.File]::Move($next,$installed) }
    Copy-Item -LiteralPath (Join-AL $Journal.run 'previous-manifest.json') -Destination (Join-AL $Root 'build-manifest.json') -Force
    Invoke-ALDesktopProbe $installed $Data
    $Journal.phase = 'rolled_back'; Write-ALInstallerJournal $JournalPath $Journal
}

function Invoke-ALInstallerDesktop([string]$Root, [string]$Data, [string]$Package, [switch]$Recover) {
    foreach ($path in $Root,$Data) { Assert-ALInstallerPath $path }
    if (Test-ALPathOverlap $Root $Data) { Stop-AL 'Desktop data must be outside its program directory.' }
    if (Test-Path -LiteralPath $Root) { $null = @(Get-ALTreeFiles $Root) }
    $manifest = Get-ALInstallerPackage $Package
    $maintenance = Join-AL $Package 'server\AuthLens.Api.exe'
    Assert-ALDesktopIdle $Data
    $state = Join-AL $Root '.setup-state'
    $journalPath = Join-AL $state 'journal.json'
    if (-not (Test-Path -LiteralPath $Root)) { New-ALInstallerPrivateDirectory $Root }
    if (-not (Test-Path -LiteralPath $state)) { New-ALInstallerPrivateDirectory $state }
    if (-not (Test-Path -LiteralPath $Data)) {
        $parent = Split-Path $Data
        if (-not (Test-Path -LiteralPath $parent)) { New-ALInstallerPrivateDirectory $parent }
        New-ALInstallerPrivateDirectory $Data
    }
    $null = Assert-ALAclPlan @(
        [pscustomobject]@{Path=$Root;Class='binaries';Role='Desktop programs';Recurse=$true},
        [pscustomobject]@{Path=$state;Class='private';Role='installer recovery';Recurse=$true},
        [pscustomobject]@{Path=$Data;Class='private';Role='Desktop data';Recurse=$true}
    ) 'Desktop installer state'
    $lock = [IO.File]::Open((Join-AL $state 'installer.lock'),'OpenOrCreate','ReadWrite','None')
    try {
        if (Test-Path -LiteralPath $journalPath) {
            $prior = Get-Content -LiteralPath $journalPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($prior.install_root -ine [IO.Path]::GetFullPath($Root) -or $prior.data_directory -ine [IO.Path]::GetFullPath($Data)) { Stop-AL 'Installer paths differ from the recorded installation; configuration is never silently replaced.' 4 }
            if ($prior.phase -notin @('complete','rolled_back','aborted')) {
                if (-not $Recover) { Stop-AL 'An interrupted installer operation needs explicit recovery; existing artifacts were preserved.' 4 }
                if (-not (Test-ALPathWithin $prior.run $state)) { Stop-AL 'Invalid recovery run path.' 4 }
                if ($prior.install_root -ine [IO.Path]::GetFullPath($Root) -or $prior.data_directory -ine [IO.Path]::GetFullPath($Data)) { Stop-AL 'Recovery paths differ from the recorded operation.' 4 }
                Restore-ALInstallerDesktop $Root $Data $journalPath $prior $maintenance
                return [pscustomobject]@{ recovered=$true; phase='rolled_back' }
            }
        }
        if ($Recover) { return [pscustomobject]@{ recovered=$false; reason='no incomplete operation' } }
        $schema = Invoke-ALMaintenance $maintenance @('--schema-info','--data-dir',$Data)
        if (-not $schema.compatible) { Stop-AL 'The selected data is incompatible with this package.' }
        $installed = Join-AL $Root 'AuthLens.exe'
        $updating = Test-Path -LiteralPath $installed
        if (-not $schema.database_exists -and (Test-Path -LiteralPath $Data) -and @(Get-ChildItem -LiteralPath $Data -Force).Count) { Stop-AL 'Data exists without its canonical database; inspect it instead of initializing a replacement.' }
        if ($updating -and @($schema.pending).Count) { Stop-AL 'Installer update cannot prove binary rollback across pending schema migrations; nothing was replaced.' }
        if ($updating) {
            $oldManifest = Assert-ALInstalledDesktop $Root
            if ($oldManifest.PSObject.Properties['file_version'] -and $manifest.PSObject.Properties['file_version'] -and
                [version](@($manifest.file_version) -join '.') -lt [version](@($oldManifest.file_version) -join '.')) { Stop-AL 'Installer downgrades are not supported.' }
        } elseif (Test-Path -LiteralPath (Join-AL $Root 'build-manifest.json')) { Stop-AL 'A manifest exists without its installed Desktop; inspect the incomplete installation before proceeding.' }
        $run = Join-AL $state ([Guid]::NewGuid().ToString('N')); New-ALInstallerPrivateDirectory $run
        Save-ALInstallerRecoveryTools $run
        $journal = [pscustomobject]@{ phase='prepared'; run=$run; install_root=[IO.Path]::GetFullPath($Root); data_directory=[IO.Path]::GetFullPath($Data); package_sha=$manifest.source_sha; applied_before=@($schema.applied); previous_sha256=''; previous_manifest_sha256=''; backup=$null; had_previous=[bool]$updating }
        if ($updating) {
            Copy-Item -LiteralPath $installed -Destination (Join-AL $run 'previous.exe')
            Copy-Item -LiteralPath (Join-AL $Root 'build-manifest.json') -Destination (Join-AL $run 'previous-manifest.json')
            $journal.previous_sha256 = (Get-FileHash -LiteralPath (Join-AL $run 'previous.exe') -Algorithm SHA256).Hash
            $journal.previous_manifest_sha256 = (Get-FileHash -LiteralPath (Join-AL $run 'previous-manifest.json') -Algorithm SHA256).Hash
            $journal.phase='backup'; Write-ALInstallerJournal $journalPath $journal
            if ($schema.database_exists) {
                $backup = Invoke-ALMaintenance $maintenance @('--backup-local',$run,'--data-dir',$Data)
                $verified = Invoke-ALMaintenance $maintenance @('--backup-verify',$backup.file,'--data-dir',$Data)
                if (-not $verified.verified -or $verified.sha256 -ne $backup.sha256) { Stop-AL 'Protective backup verification failed; nothing was replaced.' }
                $journal.backup = $backup
            }
            Invoke-ALDesktopProbe $installed $Data # prove the previous version worked before replacement
        }
        Write-ALInstallerJournal $journalPath $journal
        try {
            Assert-ALDesktopIdle $Data
            $journal.phase='replacing'; Write-ALInstallerJournal $journalPath $journal
            $next = Join-AL $Root ('candidate-' + [Guid]::NewGuid().ToString('N') + '.exe')
            Copy-Item -LiteralPath (Join-AL $Package 'desktop\AuthLens.exe') -Destination $next
            if ((Get-FileHash -LiteralPath $next -Algorithm SHA256).Hash -ine (@($manifest.artifacts | Where-Object path -CEQ 'desktop/AuthLens.exe')[0].sha256)) { Stop-AL 'Staged executable changed before replacement.' }
            if ($updating) { [IO.File]::Replace($next,$installed,(Join-AL $run 'replaced.exe')) } else { [IO.File]::Move($next,$installed) }
            Copy-Item -LiteralPath (Join-AL $Package 'build-manifest.json') -Destination (Join-AL $Root 'build-manifest.json') -Force
            $journal.phase='verifying'; Write-ALInstallerJournal $journalPath $journal
            Invoke-ALDesktopProbe $installed $Data
            $journal.phase='complete'; Write-ALInstallerJournal $journalPath $journal
            [pscustomobject]@{ installed=$true; updated=[bool]$updating; backup=$journal.backup; run=$run }
        } catch {
            $failure=$_.Exception.Message
            if ($updating) {
                try { Restore-ALInstallerDesktop $Root $Data $journalPath $journal $maintenance }
                catch { $journal.phase='manual_recovery_required'; Write-ALInstallerJournal $journalPath $journal; Stop-AL 'Installer rollback could not be verified; close Desktop and use explicit recovery. All evidence was preserved.' 4 }
                Stop-AL "Update failed and the previous Desktop was restored and verified: $failure" 1
            }
            $journal.phase='manual_recovery_required'; Write-ALInstallerJournal $journalPath $journal
            Stop-AL 'Fresh Desktop installation did not become ready; files and diagnostics were preserved for review.' 4
        }
    } finally { $lock.Dispose() }
}
