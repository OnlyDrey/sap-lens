<# Build a .NET Framework 4.8 GUI; PowerShell is a build dependency only. #>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$root=Split-Path $PSScriptRoot -Parent
$compiler=Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
if (-not (Test-Path $compiler)) { throw 'Install .NET Framework 4.8 on the Windows builder.' }
$identity=Get-Content (Join-Path $root 'backend/build/build-version.json') -Raw | ConvertFrom-Json
$numbers=$identity.file_version -join '.'
$attributes=Join-Path $root 'backend/build/service-manager-version.cs'
@"
using System.Reflection;
[assembly: AssemblyTitle("SAP Lens Service Manager")]
[assembly: AssemblyProduct("SAP Lens")]
[assembly: AssemblyCompany("SAP Lens contributors")]
[assembly: AssemblyVersion("$numbers")]
[assembly: AssemblyFileVersion("$numbers")]
[assembly: AssemblyInformationalVersion("$($identity.version)")]
"@ | Set-Content -LiteralPath $attributes -Encoding UTF8
$output=Join-Path $OutputDirectory 'SAP-Lens-Service-Manager.exe'
$references=@('/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll', '/reference:System.Xml.Linq.dll', '/reference:System.Web.Extensions.dll', '/reference:System.ServiceProcess.dll')
$source=Join-Path $root 'deploy/windows/ServiceManager.cs'
& $compiler /nologo /target:winexe /platform:x64 /optimize+ "/out:$output" `
    "/win32icon:$(Join-Path $root 'assets/sap-lens.ico')" `
    "/win32manifest:$(Join-Path $root 'deploy/windows/service-manager.manifest')" `
    @references $source $attributes
if ($LASTEXITCODE -ne 0) { throw 'Service manager compilation failed.' }
# The shipped manager requires elevation for SCM operations. Exercise the exact
# same SelfTest implementation through a disposable asInvoker harness instead of
# launching that elevated GUI during ordinary non-admin packaging.
$temporary=Join-Path $root ('backend/build/service-manager-check-'+[guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $temporary | Out-Null
try {
    $harness=Join-Path $temporary 'SelfTest.cs'
    $manifest=Join-Path $temporary 'self-test.manifest'
    $check=Join-Path $temporary 'SelfTest.exe'
    'class SapLensSelfTest { public static int Main() { try { SapLens.ServiceSetup.SelfTest(); return 0; } catch { return 1; } } }' | Set-Content -LiteralPath $harness -Encoding UTF8
    '<assembly manifestVersion="1.0" xmlns="urn:schemas-microsoft-com:asm.v1"><trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges><requestedExecutionLevel level="asInvoker" uiAccess="false"/></requestedPrivileges></security></trustInfo></assembly>' | Set-Content -LiteralPath $manifest -Encoding UTF8
    & $compiler /nologo /target:exe /platform:x64 /main:SapLensSelfTest "/out:$check" "/win32manifest:$manifest" @references $source $harness
    if ($LASTEXITCODE -ne 0) { throw 'Service manager self-test harness compilation failed.' }
    $process=Start-Process -FilePath $check -PassThru -Wait
    if ($process.ExitCode -ne 0) { throw 'Service manager self-test failed.' }
} finally {
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
