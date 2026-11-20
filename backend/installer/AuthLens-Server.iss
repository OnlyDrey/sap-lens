; AuthLens Server (.NET) machine-wide installer. Built by scripts/build-installers.ps1 from a verified release folder (build-release.ps1):
;   ISCC /DFullVersion=2.0.0-alpha.1 /DNumericVersion=2.0.0.1 /DReleaseDir=<release folder> AuthLens-Server.iss
; Installs the server files into {app}\server. It never creates, reconfigures or deletes a Windows service and never touches a data directory (the
; server's --data-dir is always outside {app}). In-place updates are refused before any service/file change because native installer rollback
; acceptance is not complete. Use the existing versioned deployment procedure for controlled updates. No process is killed.
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
#define RepoRoot AddBackslash(SourcePath) + "..\.."
#define ProductIcon RepoRoot + "\assets\sap-lens.ico"
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
UninstallDisplayIcon={app}\server\AuthLens.Api.exe
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
Source: "{#ReleaseDir}\server\AuthLens.Api.exe"; DestDir: "{app}\server"; Flags: ignoreversion
Source: "{#ReleaseDir}\server\e_sqlite3.dll"; DestDir: "{app}\server"; Flags: ignoreversion
Source: "{#ReleaseDir}\server\libSkiaSharp.dll"; DestDir: "{app}\server"; Flags: ignoreversion
Source: "{#ReleaseDir}\README.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ReleaseDir}\Service-Manager.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ReleaseDir}\build-manifest.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}\LICENSE.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\AuthLens Service Manager"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -File ""{app}\Service-Manager.ps1"""; WorkingDir: "{app}"

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

// An in-place overwrite cannot promise verified database rollback. Refuse it before any service or program file changes.
// Versioned deployments provide the existing backup/readiness/rollback procedure until installer update acceptance is implemented.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var Names: TArrayOfString; I: Integer;
begin
  Result := '';
  Names := ServiceNames();
  for I := 0 to GetArrayLength(Names) - 1 do
    if RegKeyExists(HKLM, ServicesKey + Names[I]) then begin
      Result := 'An AuthLens service already exists. This installer will not stop it or overwrite its files. Use the verified versioned deployment and rollback procedure; installer-managed updates are not yet accepted.';
      Exit;
    end;
  if FileExists(ExpandConstant('{app}\server\AuthLens.Api.exe')) then
    Result := 'AuthLens Server program files already exist. In-place installer updates are refused until verified backup, readiness and rollback acceptance is implemented. Keep the existing installation and use versioned deployment.';
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
