BeforeAll {
    $script:Manager = Join-Path $PSScriptRoot '../Service-Manager.ps1'
    $tokens = $null; $errors = $null
    $script:Ast = [Management.Automation.Language.Parser]::ParseFile((Resolve-Path $script:Manager), [ref]$tokens, [ref]$errors)
    if ($errors) { throw 'Service Manager syntax errors' }
    # Load the pure argument builder only. Never execute the menu, a key command or a host process.
    $definition = $script:Ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-AuthLensAdminArguments' }, $true)
    . ([scriptblock]::Create($definition.Extent.Text))
}
Describe 'Packaged local Service Manager' {
    It 'uses packaged maintenance commands with file paths, never secret arguments or SDK projects' {
        @(Get-AuthLensAdminArguments 'ExportKey' 'C:\private\data' 'D:\recovery\copy.key' '') | Should -Be @('--backup-key','export','D:\recovery\copy.key','--data-dir','C:\private\data')
        @(Get-AuthLensAdminArguments 'VerifyKey' 'C:\private\data' 'D:\recovery\copy.key' '') | Should -Be @('--backup-key','verify','D:\recovery\copy.key','--data-dir','C:\private\data')
        @(Get-AuthLensAdminArguments 'RecoveryCode' 'C:\private\data' '' 'admin.synthetic') | Should -Be @('--accounts-code','--recover-administrator','admin.synthetic','--data-dir','C:\private\data')
        { Get-AuthLensAdminArguments 'CreateKey' 'C:\private\data' 'relative.key' '' } | Should -Throw '*absolute*'
        $commands = @($script:Ast.FindAll({ param($node) $node -is [Management.Automation.Language.CommandAst] }, $true) | ForEach-Object { $_.GetCommandName() })
        foreach ($name in 'dotnet', 'Stop-Service', 'Start-Service', 'New-Service', 'Remove-Item', 'Get-Content') { $commands | Should -Not -Contain $name }
    }
    It 'ships with release checksums and the server installer' {
        foreach ($name in 'build-release.ps1','build-release.sh') { Get-Content (Join-Path $PSScriptRoot "../$name") -Raw | Should -Match 'Service-Manager.ps1' }
        Get-Content (Join-Path $PSScriptRoot '../../installer/AuthLens-Server.iss') -Raw | Should -Match 'AuthLens Service Manager'
    }
}
