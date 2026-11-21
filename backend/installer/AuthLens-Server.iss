; AuthLens Server (.NET) machine-wide installer. Built by scripts/build-installers.ps1 from a verified release folder (build-release.ps1):
;   ISCC /DFullVersion=2.0.0-alpha.1 /DNumericVersion=2.0.0.1 /DReleaseDir=<release folder> AuthLens-Server.iss
; Stages an immutable payload under {app}\setup. The existing versioned deployment transaction owns service installation/update and readiness.
; The server's --data-dir is outside program files; no earlier-product service or data directory is adopted.
; Configuration is explicit; backup, rollback compatibility and readiness are mandatory. No process is killed.
; Uninstall is refused while a service still runs from {app}.
; Silent: AuthLens-Server-<version>-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART [/LOG=<file>]
#ifndef FullVersion
  #error FullVersion is required
#endif
#ifndef NumericVersion
  #error NumericVersion is required
#endif
#ifndef ReleaseDir
  #error ReleaseDir is required (a release folder verified by verify-release.ps1)
#endif
#ifndef PackageName
  #error PackageName is required
#endif
#ifndef ToolsDir
  #error ToolsDir is required
#endif
#define InstallerMode "Server"
#define RepoRoot AddBackslash(SourcePath) + "..\.."
#define ProductIcon RepoRoot + "\assets\branding\app.ico"
#define AppIdGuid "B961C010-9B53-4514-9D2A-73A4641E4AAF"
#define VersionKey "Software\AuthLens\Server"

[Setup]
AppId={{{#AppIdGuid}}
AppName=AuthLens
AppVersion={#FullVersion}
AppVerName=AuthLens {#FullVersion}
AppPublisher=AuthLens
DefaultDirName={commonappdata}\AuthLens\app
UsePreviousAppDir=yes
DisableDirPage=auto
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
SetupIconFile={#ProductIcon}
UninstallDisplayIcon={app}\setup\{#PackageName}\payload\{#PackageName}\server\AuthLens.Api.exe
UninstallDisplayName=AuthLens Server
CloseApplications=no
RestartApplications=no
VersionInfoVersion={#NumericVersion}
VersionInfoTextVersion={#FullVersion}
VersionInfoProductName=AuthLens
VersionInfoProductVersion={#NumericVersion}
VersionInfoProductTextVersion={#FullVersion}
VersionInfoDescription=AuthLens Server Setup
OutputBaseFilename=AuthLens-Server-{#FullVersion}-Setup

[Files]
Source: "{#ToolsDir}\*"; DestDir: "{tmp}\AuthLensPrerequisites\{#PackageName}\tools"; Flags: dontcopy recursesubdirs noencryption
Source: "{#ReleaseDir}\*"; DestDir: "{app}\setup\{#PackageName}\payload\{#PackageName}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ToolsDir}\*"; DestDir: "{app}\setup\{#PackageName}\tools"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#RepoRoot}\LICENSE.md"; DestDir: "{app}\setup\{#PackageName}"; Flags: ignoreversion

[Icons]
Name: "{group}\AuthLens Service Manager"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -File ""{app}\setup\{#PackageName}\payload\{#PackageName}\Service-Manager.ps1"""; WorkingDir: "{app}"

[Registry]
Root: HKLM; Subkey: "{#VersionKey}"; ValueType: string; ValueName: "FileVersion"; ValueData: "{#NumericVersion}"; Flags: uninsdeletekey

; No [UninstallDelete] and no [InstallDelete]: data directories, certificates, logs and backups are never removed by Setup or uninstall.

[Code]
const
  ServicesKey = 'SYSTEM\CurrentControlSet\Services\';

function ServiceNames(): TArrayOfString;
begin
  // Only AuthLens: services of earlier products (SAP Lens: sap-lens, SapLens, SapLens2) are never stopped, started or inspected.
  SetArrayLength(Result, 1);
  Result[0] := 'AuthLens';
end;

// Whether service Name exists and its executable lies in Directory (case-insensitive prefix of the unquoted ImagePath).
function ServiceRunsFrom(Name, Directory: String): Boolean;
var ImagePath: String;
begin
  Result := False;
  if not RegQueryStringValue(HKLM, ServicesKey + Name, 'ImagePath', ImagePath) then Exit;
  StringChangeEx(ImagePath, '"', '', True);
  Result := Pos(Uppercase(AddBackslash(ExpandFileName(Directory))), Uppercase(ImagePath)) = 1;
end;

function InitializeSetup(): Boolean;
var Installed: String; InstalledVersion, ThisVersion: Int64;
begin
  Result := True;
  if RegQueryStringValue(HKLM, '{#VersionKey}', 'FileVersion', Installed) and StrToVersion(Installed, InstalledVersion) and
     StrToVersion('{#NumericVersion}', ThisVersion) and (ComparePackedVersion(ThisVersion, InstalledVersion) < 0) then begin
    SuppressibleMsgBox('A newer AuthLens Server (' + Installed + ') is installed. Downgrades are not supported; nothing was changed.', mbError, MB_OK, IDOK);
    Result := False;
  end;
end;

function InitializeUninstall(): Boolean;
var Names: TArrayOfString; I: Integer;
begin
  Result := True;
  Names := ServiceNames();
  for I := 0 to GetArrayLength(Names) - 1 do
    if ServiceRunsFrom(Names[I], ExpandConstant('{app}')) then begin
      SuppressibleMsgBox('Service ' + Names[I] + ' runs from this installation. Stop and remove the service first (sc.exe delete ' + Names[I] + '); uninstall never removes a service or data.', mbError, MB_OK, IDOK);
      Result := False;
      Exit;
    end;
end;

#include "AuthLens-Server-Code.iss"
#include "AuthLens-Transaction.iss"
