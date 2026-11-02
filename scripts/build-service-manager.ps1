<# Build a .NET Framework 4.8 GUI; PowerShell is a build dependency only. #>
[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference='Stop'
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
& $compiler /nologo /target:winexe /platform:x64 /optimize+ "/out:$output" `
    "/win32icon:$(Join-Path $root 'assets/sap-lens.ico')" `
    "/win32manifest:$(Join-Path $root 'deploy/windows/service-manager.manifest')" `
    /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Xml.Linq.dll `
    /reference:System.Web.Extensions.dll /reference:System.ServiceProcess.dll `
    (Join-Path $root 'deploy/windows/ServiceManager.cs') $attributes
if ($LASTEXITCODE -ne 0) { throw 'Service manager compilation failed.' }
$process=Start-Process -FilePath $output -ArgumentList '--self-test' -PassThru -Wait
if ($process.ExitCode -ne 0) { throw 'Service manager self-test failed.' }
