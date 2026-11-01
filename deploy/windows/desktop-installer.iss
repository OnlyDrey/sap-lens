; Canonical per-user installer; application packaging remains build-windows.ps1.
#ifndef FullVersion
  #error FullVersion is required
#endif
#ifndef NumericVersion
  #error NumericVersion is required
#endif
#ifndef SourceExe
  #error SourceExe is required
#endif
#ifndef ProductLicense
  #error ProductLicense is required
#endif
#ifndef ProductIcon
  #error ProductIcon is required
#endif
[Setup]
AppId={{5DB5BC51-A860-44CA-93CA-09AE85812DF0}
AppName=SAP Lens
AppVersion={#FullVersion}
AppVerName=SAP Lens {#FullVersion}
DefaultDirName={localappdata}\Programs\SAP Lens
DefaultGroupName=SAP Lens
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
Compression=lzma2
SolidCompression=yes
SetupIconFile={#ProductIcon}
UninstallDisplayIcon={app}\SAP-Lens.exe
UninstallDisplayName=SAP Lens
AppMutex=Local\SAPLensDesktop
CloseApplications=no
RestartApplications=no
VersionInfoVersion={#NumericVersion}
VersionInfoTextVersion={#FullVersion}
VersionInfoProductVersion={#NumericVersion}
VersionInfoProductTextVersion={#FullVersion}
VersionInfoProductName=SAP Lens
VersionInfoDescription=SAP Lens Setup
VersionInfoOriginalFileName=SAP-Lens-Setup.exe
OutputBaseFilename=SAP-Lens-Setup
[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked
[Files]
Source: "{#SourceExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProductLicense}"; DestDir: "{app}"; DestName: "LICENSE.md"; Flags: ignoreversion
[Icons]
Name: "{autoprograms}\SAP Lens"; Filename: "{app}\SAP-Lens.exe"
Name: "{autodesktop}\SAP Lens"; Filename: "{app}\SAP-Lens.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\SAP-Lens.exe"; Description: "Launch SAP Lens"; Flags: nowait postinstall skipifsilent
[Code]
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{5DB5BC51-A860-44CA-93CA-09AE85812DF0}_is1';
  WebViewKey = 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
function RuntimeVersion(Root: Integer): Boolean;
var Value: String; Actual, Minimum: Int64;
begin
  Result := RegQueryStringValue(Root, WebViewKey, 'pv', Value) and
    StrToVersion(Value, Actual) and StrToVersion('86.0.622.0', Minimum);
  if Result then Result := ComparePackedVersion(Actual, Minimum) >= 0;
end;
function InitializeSetup(): Boolean;
begin
  Result := RuntimeVersion(HKCU) or RuntimeVersion(HKLM32) or RuntimeVersion(HKLM64);
  if not Result then
    SuppressibleMsgBox('Microsoft Edge WebView2 Runtime 86.0.622.0 or newer is required. Install the Evergreen Runtime using your approved software-distribution process, then run Setup again. Setup does not download or disable security controls.', mbError, MB_OK, IDOK);
end;
function Quoted(Value: String): String;
begin
  Result := '"' + Value + '"';
end;
function HasFiles(Directory: String): Boolean;
var Found: TFindRec;
begin
  Result := False;
  if FindFirst(AddBackslash(Directory) + '*', Found) then begin
    try
      repeat
        if (Found.Name <> '.') and (Found.Name <> '..') then begin
          Result := True;
          Break;
        end;
      until not FindNext(Found);
    finally
      FindClose(Found);
    end;
  end;
end;
function PrepareToInstall(var NeedsRestart: Boolean): String;
var PreviousVersion, DataDirectory, BackupDirectory, BackupFile, TemporaryExe, Parameters: String;
    ExitCode: Integer;
begin
  Result := '';
  RegQueryStringValue(HKCU, UninstallKey, 'DisplayVersion', PreviousVersion);
  if FileExists(ExpandConstant('{app}\SAP-Lens.exe')) and (PreviousVersion = '') then begin
    Result := 'The target contains an unmanaged SAP Lens executable. Choose an empty installation directory; existing files will not be overwritten.';
    Exit;
  end;
  ExtractTemporaryFile('SAP-Lens.exe');
  TemporaryExe := ExpandConstant('{tmp}\SAP-Lens.exe');
  if PreviousVersion <> '' then begin
    Parameters := '--maintenance version-check --application-version ' + Quoted(PreviousVersion) + ' --target-version ' + Quoted('{#FullVersion}');
    if not Exec(TemporaryExe, Parameters, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) or (ExitCode <> 0) then begin
      Result := 'Version compatibility could not be verified. Downgrades are not supported; no installed application files were replaced.';
      Exit;
    end;
  end;
  DataDirectory := GetEnv('SAP_LENS_CONFIG_DIR');
  if DataDirectory = '' then DataDirectory := ExpandConstant('{localappdata}\SAP Lens');
  DataDirectory := RemoveBackslashUnlessRoot(DataDirectory);
  if Pos('"', DataDirectory) <> 0 then begin Result := 'Invalid data-directory override.'; Exit; end;
  if DirExists(DataDirectory) and HasFiles(DataDirectory) then begin
    BackupDirectory := GetEnv('SAP_LENS_BACKUP_DIR');
    if BackupDirectory = '' then BackupDirectory := ExpandConstant('{localappdata}\SAP Lens Backups');
    if Pos('"', BackupDirectory) <> 0 then begin Result := 'Invalid backup-directory override.'; Exit; end;
    if not ForceDirectories(BackupDirectory) then begin Result := 'Cannot create the private upgrade-backup directory.'; Exit; end;
    BackupFile := AddBackslash(BackupDirectory) + 'SAP-Lens-' + GetDateTimeString('yyyymmdd-hhnnss-zzz', '-', ':') + '.tar.gz';
    if PreviousVersion = '' then PreviousVersion := '{#FullVersion}';
    Parameters := '--maintenance backup --mode desktop --allow-legacy --data ' + Quoted(DataDirectory) +
      ' --output ' + Quoted(BackupFile) + ' --application-version ' + Quoted(PreviousVersion);
    if not Exec(TemporaryExe, Parameters, '', SW_HIDE, ewWaitUntilTerminated, ExitCode) or (ExitCode <> 0) then
      Result := 'Private data backup failed. Close all SAP Lens sessions and review data ownership/permissions. No installed application files were replaced.';
  end;
end;
// No [UninstallDelete]: application data and private backups are preserved.
