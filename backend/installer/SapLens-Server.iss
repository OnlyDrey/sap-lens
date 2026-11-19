; SAP Lens Server (.NET) machine-wide installer. Built by scripts/build-installers.ps1 from a verified release folder (build-release.ps1):
;   ISCC /DFullVersion=2.0.0-alpha.1 /DNumericVersion=2.0.0.1 /DReleaseDir=<release folder> SapLens-Server.iss
; Installs the server files into {app}\server. It never creates, reconfigures or deletes a Windows service and never touches a data directory (the
; server's --data-dir is always outside {app}). On upgrade, a sap-lens (or historical SapLens/SapLens2) service whose executable is in {app} is stopped through the
; Service Control Manager before the files are replaced and started again afterwards; no process is ever killed. A service that runs a managed
; release elsewhere (scripts/deploy) is left alone. Uninstall is refused while a service still runs from {app}.
; Silent: SAP-Lens-Server-<version>-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART [/LOG=<file>]
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
#define AppIdGuid "F11EE7F5-465D-42C3-9781-85149985043C"
#define VersionKey "Software\SAP Lens\Server"

[Setup]
AppId={{{#AppIdGuid}}
AppName=SAP Lens
AppVersion={#FullVersion}
AppVerName=SAP Lens {#FullVersion}
AppPublisher=SAP Lens
DefaultDirName=C:\sap-lens
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
UninstallDisplayIcon={app}\server\SapLens.Api.exe
UninstallDisplayName=SAP Lens Server
CloseApplications=no
RestartApplications=no
VersionInfoVersion={#NumericVersion}
VersionInfoTextVersion={#FullVersion}
VersionInfoProductName=SAP Lens
VersionInfoProductVersion={#NumericVersion}
VersionInfoProductTextVersion={#FullVersion}
VersionInfoDescription=SAP Lens Server Setup
OutputBaseFilename=SAP-Lens-Server-{#FullVersion}-Setup

[Files]
Source: "{#ReleaseDir}\server\SapLens.Api.exe"; DestDir: "{app}\server"; Flags: ignoreversion
Source: "{#ReleaseDir}\server\e_sqlite3.dll"; DestDir: "{app}\server"; Flags: ignoreversion
Source: "{#ReleaseDir}\server\libSkiaSharp.dll"; DestDir: "{app}\server"; Flags: ignoreversion
Source: "{#ReleaseDir}\README.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ReleaseDir}\Service-Manager.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ReleaseDir}\build-manifest.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}\LICENSE.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\SAP Lens Service Manager"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -File ""{app}\Service-Manager.ps1"""; WorkingDir: "{app}"

[Registry]
Root: HKLM; Subkey: "{#VersionKey}"; ValueType: string; ValueName: "FileVersion"; ValueData: "{#NumericVersion}"; Flags: uninsdeletekey

; No [UninstallDelete] and no [InstallDelete]: data directories, certificates, logs and backups are never removed by Setup or uninstall.

[Code]
const
  ServicesKey = 'SYSTEM\CurrentControlSet\Services\';
var
  StoppedServices: TArrayOfString;

function ServiceNames(): TArrayOfString;
begin
  SetArrayLength(Result, 3);
  Result[0] := 'sap-lens';
  Result[1] := 'SapLens';
  Result[2] := 'SapLens2';
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
    SuppressibleMsgBox('A newer SAP Lens Server (' + Installed + ') is installed. Downgrades are not supported; nothing was changed.', mbError, MB_OK, IDOK);
    Result := False;
  end;
end;

// Stops (graceful, through the Service Control Manager; net stop waits for the stop) every SAP Lens service that runs from {app}.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var Names: TArrayOfString; I, ExitCode: Integer;
begin
  Result := '';
  SetArrayLength(StoppedServices, 0);
  Names := ServiceNames();
  for I := 0 to GetArrayLength(Names) - 1 do
    if ServiceRunsFrom(Names[I], ExpandConstant('{app}')) then begin
      Log('Service ' + Names[I] + ' runs from ' + ExpandConstant('{app}') + '; stopping it before the upgrade.');
      if not Exec(ExpandConstant('{sys}\net.exe'), 'stop ' + Names[I], '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then ExitCode := -1;
      // 0 stopped now; 2 it was not running. Anything else: leave every file as it is.
      if ExitCode = 0 then begin
        SetArrayLength(StoppedServices, GetArrayLength(StoppedServices) + 1);
        StoppedServices[GetArrayLength(StoppedServices) - 1] := Names[I];
      end else if ExitCode <> 2 then begin
        Result := 'Service ' + Names[I] + ' could not be stopped (net stop exit ' + IntToStr(ExitCode) + '). Nothing was changed; it was not terminated. Stop it yourself, then run Setup again.';
        Exit;
      end;
    end else if ServiceRunsFrom(Names[I], 'C:\') then
      Log('Service ' + Names[I] + ' runs from another folder (for example a managed release); it is left unchanged.');
end;

procedure CurStepChanged(CurStep: TSetupStep);
var I, ExitCode: Integer;
begin
  if CurStep <> ssPostInstall then Exit;
  for I := 0 to GetArrayLength(StoppedServices) - 1 do begin
    if not Exec(ExpandConstant('{sys}\net.exe'), 'start ' + StoppedServices[I], '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then ExitCode := -1;
    if ExitCode = 0 then Log('Service ' + StoppedServices[I] + ' started again.')
    else SuppressibleMsgBox('Service ' + StoppedServices[I] + ' did not start again (net start exit ' + IntToStr(ExitCode) + '). Its data is unchanged; see <data-dir>\logs\server-*.log and the Windows event log.', mbError, MB_OK, IDOK);
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
