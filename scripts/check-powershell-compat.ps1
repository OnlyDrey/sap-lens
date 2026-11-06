# Static Windows PowerShell 5.1 compatibility check. Runs on PowerShell 7 (Linux included) and on 5.1 itself; this file must stay 5.1-parseable.
# It walks the AST (no text matching) for language features, parameters, variables and .NET APIs that Windows PowerShell 5.1 / .NET Framework 4.x lack.
# LIMITS: static only. It cannot prove a script runs under 5.1 (runtime behaviour, encodings, native-argument quoting and .NET overloads are only
# approximated by the tables below), so native Windows PowerShell 5.1 execution stays a separate acceptance step. Errors fail the check; warnings do not.
[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Path, [switch]$Quiet)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
if (-not $Path) { $Path = @(Get-ChildItem -Path (Join-Path $root 'scripts'), (Join-Path $root 'deploy') -Recurse -Include *.ps1, *.psm1 | ForEach-Object { $_.FullName }) }

# Parameters that exist only in PowerShell 6+/7 (command -> parameters).
$newParameters = @{
    'ConvertFrom-Json' = @('AsHashtable', 'DateKind', 'NoEnumerate'); 'ConvertTo-Json' = @('EscapeHandling'); 'ForEach-Object' = @('Parallel', 'ThrottleLimit', 'TimeoutSeconds')
    'Get-Content' = @('AsByteStream'); 'Set-Content' = @('AsByteStream'); 'Add-Content' = @('AsByteStream'); 'Out-File' = @(); 'Invoke-WebRequest' = @('SkipCertificateCheck', 'SkipHttpErrorCheck', 'Authentication', 'Token', 'NoProxy')
    'Invoke-RestMethod' = @('SkipCertificateCheck', 'SkipHttpErrorCheck', 'Authentication', 'Token', 'NoProxy'); 'Select-String' = @('NoEmphasis'); 'Get-Date' = @()
    'Test-Path' = @('OlderThan', 'NewerThan'); 'Sort-Object' = @('Stable'); 'Format-Hex' = @(); 'Get-ChildItem' = @('Depth_')
}
# Cmdlets that do not exist in 5.1.
$newCommands = @('Get-Error', 'Join-String', 'Test-Json', 'ConvertFrom-Markdown', 'Show-Markdown', 'Remove-Alias_', 'Get-Uptime', 'Clear-Host_')
# Variables that are undefined (null) in 5.1.
$newVariables = @('IsWindows', 'IsLinux', 'IsMacOS', 'IsCoreCLR', 'PSNativeCommandArgumentPassing', 'PSNativeCommandUseErrorActionPreference', 'ErrorView_')
# Static .NET members that .NET Framework 4.x does not have.
$newMembers = @{
    'System.IO.Path' = @('GetRelativePath', 'Join', 'TrimEndingDirectorySeparator', 'EndsInDirectorySeparator'); 'IO.Path' = @('GetRelativePath', 'Join', 'TrimEndingDirectorySeparator', 'EndsInDirectorySeparator')
    'Path' = @('GetRelativePath', 'Join'); 'Convert' = @('ToHexString', 'FromHexString'); 'System.Convert' = @('ToHexString', 'FromHexString')
    'Environment' = @('ProcessPath'); 'System.Environment' = @('ProcessPath'); 'Math' = @('Clamp'); 'System.Math' = @('Clamp')
    'System.Security.Cryptography.SHA256' = @('HashData'); 'Security.Cryptography.SHA256' = @('HashData'); 'System.Security.Cryptography.RandomNumberGenerator' = @('GetBytes_', 'GetInt32')
    'System.IO.File' = @('ReadAllBytesAsync', 'ReadAllTextAsync', 'WriteAllTextAsync', 'WriteAllBytesAsync', 'ReadLinesAsync'); 'IO.File' = @('ReadAllBytesAsync', 'ReadAllTextAsync', 'WriteAllTextAsync', 'WriteAllBytesAsync')
    'System.Runtime.InteropServices.RuntimeInformation' = @(); 'System.Text.Json.JsonSerializer' = @('Serialize', 'Deserialize')
}
$unsafeEncodings = @('utf8NoBOM', 'utf8BOM', 'utf32', 'oem_')
$cmdletWriters = @('Set-Content', 'Add-Content', 'Out-File', 'Export-Csv')

$findings = New-Object System.Collections.ArrayList
function Add-Finding([string]$File, $Node, [string]$Severity, [string]$Rule, [string]$Message) {
    [void]$findings.Add([pscustomobject]@{ File = $File; Line = $Node.Extent.StartLineNumber; Severity = $Severity; Rule = $Rule; Message = $Message })
}
function Get-TypeName($node) { if ($node -is [System.Management.Automation.Language.TypeExpressionAst]) { return $node.TypeName.FullName }; return $null }

foreach ($file in $Path) {
    $display = $file
    if ($file.StartsWith($root)) { $display = $file.Substring($root.Length).TrimStart('/', '\') }
    $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($file, [ref]$null, [ref]$errors)
    if ($errors.Count) { foreach ($e in $errors) { [void]$findings.Add([pscustomobject]@{ File = $display; Line = $e.Extent.StartLineNumber; Severity = 'Error'; Rule = 'Syntax'; Message = $e.Message }) }; continue }
    foreach ($node in $ast.FindAll({ param($n) $true }, $true)) {
        $kind = $node.GetType().Name
        if ($kind -eq 'TernaryExpressionAst') { Add-Finding $display $node 'Error' 'PS7-Ternary' 'The ternary operator (?:) needs PowerShell 7; use if/else.' }
        elseif ($kind -eq 'PipelineChainAst') { Add-Finding $display $node 'Error' 'PS7-PipelineChain' 'Pipeline chain operators (&& and ||) need PowerShell 7; test $LASTEXITCODE or $? instead.' }
        elseif ($kind -eq 'BinaryExpressionAst' -and ("$($node.Operator)" -eq 'QuestionQuestion')) { Add-Finding $display $node 'Error' 'PS7-NullCoalescing' 'The null-coalescing operator (??) needs PowerShell 7.' }
        elseif ($kind -eq 'AssignmentStatementAst' -and ("$($node.Operator)" -eq 'QuestionQuestionEquals')) { Add-Finding $display $node 'Error' 'PS7-NullCoalescingAssign' 'The ??= operator needs PowerShell 7.' }
        elseif (($kind -eq 'MemberExpressionAst' -or $kind -eq 'InvokeMemberExpressionAst' -or $kind -eq 'IndexExpressionAst') -and $node.PSObject.Properties['NullConditional'] -and $node.NullConditional) {
            Add-Finding $display $node 'Error' 'PS7-NullConditional' 'Null-conditional access (?. or ?[]) needs PowerShell 7.'
        }
        elseif ($kind -eq 'VariableExpressionAst') {
            $name = $node.VariablePath.UserPath
            if ($newVariables -contains $name) { Add-Finding $display $node 'Error' 'PS7-Variable' ('$' + $name + ' does not exist in Windows PowerShell 5.1 (it is $null, or an error under strict mode); test $env:OS instead.') }
        }
        elseif ($kind -eq 'InvokeMemberExpressionAst' -or $kind -eq 'MemberExpressionAst') {
            $typeName = Get-TypeName $node.Expression
            if ($typeName -and $node.Static -and $node.Member -is [System.Management.Automation.Language.StringConstantExpressionAst] -and $newMembers.ContainsKey($typeName) -and ($newMembers[$typeName] -contains $node.Member.Value)) {
                Add-Finding $display $node 'Error' 'NetCore-Api' ('[' + $typeName + ']::' + $node.Member.Value + ' is not available in .NET Framework 4.x (Windows PowerShell 5.1).')
            }
        }
        elseif ($kind -eq 'CommandAst') {
            $name = $node.GetCommandName()
            if (-not $name) { continue }
            if ($newCommands -contains $name) { Add-Finding $display $node 'Error' 'PS7-Cmdlet' ($name + ' does not exist in Windows PowerShell 5.1.') }
            $elements = @($node.CommandElements)
            for ($i = 1; $i -lt $elements.Count; $i++) {
                $element = $elements[$i]
                if ($element -isnot [System.Management.Automation.Language.CommandParameterAst]) { continue }
                $parameter = $element.ParameterName
                if ($newParameters.ContainsKey($name) -and ($newParameters[$name] -contains $parameter)) {
                    Add-Finding $display $node 'Error' 'PS7-Parameter' ($name + ' -' + $parameter + ' does not exist in Windows PowerShell 5.1.')
                }
                if ($parameter -eq 'Encoding' -and ($cmdletWriters -contains $name -or $name -eq 'Get-Content')) {
                    $argument = $element.Argument
                    if (-not $argument -and ($i + 1) -lt $elements.Count) { $argument = $elements[$i + 1] }
                    if ($argument -is [System.Management.Automation.Language.StringConstantExpressionAst] -and ($unsafeEncodings -contains $argument.Value)) {
                        Add-Finding $display $node 'Error' 'PS7-Encoding' ('-Encoding ' + $argument.Value + ' is not accepted by Windows PowerShell 5.1 (and utf8 writes a BOM there, unlike 7).')
                    }
                    if ($argument -is [System.Management.Automation.Language.StringConstantExpressionAst] -and $argument.Value -ieq 'utf8' -and $cmdletWriters -contains $name) {
                        Add-Finding $display $node 'Warning' 'Encoding-BOM' ($name + ' -Encoding utf8 writes a UTF-8 BOM in 5.1 but not in 7; use [IO.File]::WriteAllText with UTF8Encoding($false) when a BOM matters.')
                    }
                }
            }
            if ($cmdletWriters -contains $name -and -not (@($elements | Where-Object { $_ -is [System.Management.Automation.Language.CommandParameterAst] -and $_.ParameterName -eq 'Encoding' }))) {
                Add-Finding $display $node 'Warning' 'Encoding-Default' ($name + ' without -Encoding uses UTF-16 (Out-File) or the ANSI code page (Set-Content) in 5.1 and UTF-8 in 7.')
            }
            if ($name -eq 'Start-Process') {
                $hasArguments = $elements | Where-Object { $_ -is [System.Management.Automation.Language.CommandParameterAst] -and $_.ParameterName -like 'Arg*' }
                if ($hasArguments) { Add-Finding $display $node 'Warning' 'StartProcess-Arguments' 'Start-Process -ArgumentList joins items with spaces without quoting in 5.1; quote each item that can contain spaces.' }
            }
            # A native executable (no verb-noun name) given an argument that contains a double quote: 5.1 strips or re-splits it, 7.3+ passes it through.
            if ($name -notmatch '-' -and $name -notmatch '^(\.|&|exit|if|foreach|cd|echo|ls|cat|type|where|sort|select|set|get|new)$') {
                foreach ($element in $elements | Select-Object -Skip 1) {
                    if (($element -is [System.Management.Automation.Language.StringConstantExpressionAst] -or $element -is [System.Management.Automation.Language.ExpandableStringExpressionAst]) -and $element.Value -match '"') {
                        Add-Finding $display $node 'Warning' 'Native-Quotes' ('A literal double quote passed to native command ' + $name + ' is handled differently by 5.1; avoid quotes in native arguments.')
                    }
                }
            }
        }
        elseif ($kind -eq 'FileRedirectionAst' -and $node.Location -ne $null -and -not ($node.Location -is [System.Management.Automation.Language.VariableExpressionAst] -and $node.Location.VariablePath.UserPath -eq 'null')) {
            Add-Finding $display $node 'Warning' 'Redirect-Encoding' 'File redirection (>) writes UTF-16 in 5.1 and UTF-8 in 7; use Set-Content -Encoding or .NET file APIs.'
        }
    }
    $requires = $ast.ScriptRequirements
    if ($requires -and $requires.RequiredPSVersion -and $requires.RequiredPSVersion.Major -ge 6) {
        [void]$findings.Add([pscustomobject]@{ File = $display; Line = 1; Severity = 'Error'; Rule = 'PS7-Requires'; Message = '#requires -Version ' + $requires.RequiredPSVersion + ' excludes Windows PowerShell 5.1.' })
    }
}
$failed = @($findings | Where-Object { $_.Severity -eq 'Error' })
if (-not $Quiet) {
    foreach ($f in $findings | Sort-Object File, Line) { Write-Output ('{0}:{1} {2} [{3}] {4}' -f $f.File, $f.Line, $f.Severity, $f.Rule, $f.Message) }
    Write-Output ('PowerShell 5.1 static compatibility: {0} files, {1} errors, {2} warnings (static analysis only; native 5.1 execution is not verified).' -f @($Path).Count, $failed.Count, @($findings | Where-Object { $_.Severity -eq 'Warning' }).Count)
}
if ($failed.Count) { exit 1 }
exit 0
