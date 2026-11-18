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
#define ProductionAppId "5DB5BC51-A860-44CA-93CA-09AE85812DF0"
#ifdef AcceptanceId
  #ifndef AcceptanceRootHex
    #error AcceptanceRootHex is required for test-only installers
  #endif
  #if AcceptanceId == ProductionAppId
    #error AcceptanceId must differ from the production AppId
  #endif
  #define EffectiveAppId AcceptanceId
  #define InstallerName "SAP Lens Acceptance " + AcceptanceId
#else
  #define EffectiveAppId ProductionAppId
  #define InstallerName "SAP Lens"
#endif
#define UninstallRegistryPath "Software\Microsoft\Windows\CurrentVersion\Uninstall\{" + EffectiveAppId + "}_is1"
#define ProductionRegistryPath "Software\Microsoft\Windows\CurrentVersion\Uninstall\{" + ProductionAppId + "}_is1"
[Setup]
AppId={{{#EffectiveAppId}}
AppName={#InstallerName}
AppVersion={#FullVersion}
AppVerName={#InstallerName} {#FullVersion}
#ifdef AcceptanceId
DefaultDirName={code:AcceptanceDirectory}
DisableDirPage=yes
UsePreviousAppDir=no
#else
DefaultDirName={localappdata}\Programs\SAP Lens
UsePreviousAppDir=yes
#endif
DefaultGroupName={#InstallerName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
DisableProgramGroupPage=yes
Compression=lzma2
SolidCompression=yes
SetupIconFile={#ProductIcon}
UninstallDisplayIcon={app}\SAP-Lens.exe
UninstallDisplayName={#InstallerName}
AppMutex=Local\SAPLensDesktop
CloseApplications=no
RestartApplications=no
VersionInfoVersion={#NumericVersion}
VersionInfoTextVersion={#FullVersion}
VersionInfoProductVersion={#NumericVersion}
VersionInfoProductTextVersion={#FullVersion}
VersionInfoProductName=SAP Lens
#ifdef AcceptanceId
VersionInfoDescription=SAP Lens Acceptance {#AcceptanceId}
#else
VersionInfoDescription=SAP Lens Setup
#endif
VersionInfoOriginalFileName=SAP-Lens-Setup.exe
OutputBaseFilename=SAP-Lens-Setup
#ifndef AcceptanceId
[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked
#endif
[Files]
Source: "{#SourceExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProductLicense}"; DestDir: "{app}"; DestName: "LICENSE.md"; Flags: ignoreversion
#ifndef AcceptanceId
[Icons]
Name: "{autoprograms}\SAP Lens"; Filename: "{app}\SAP-Lens.exe"
Name: "{autodesktop}\SAP Lens"; Filename: "{app}\SAP-Lens.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\SAP-Lens.exe"; Description: "Launch SAP Lens"; Flags: nowait postinstall skipifsilent
#endif
[Code]
const
  UninstallKey = '{#UninstallRegistryPath}';
  WebViewKey = 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
#ifdef AcceptanceId
function BoundAcceptanceRoot(): String;
var Encoded: String; Index: Integer;
begin
  // Hex UTF-16 avoids injecting filesystem characters into Pascal source strings.
  Encoded := '{#AcceptanceRootHex}';
  Result := '';
  for Index := 1 to Length(Encoded) div 4 do
    Result := Result + Chr(StrToInt('$' + Copy(Encoded, (Index-1)*4+1, 4)));
end;
function AcceptanceAttributes(Path: String): LongWord;
  external 'GetFileAttributesW@kernel32.dll stdcall';
function NoAcceptanceLinks(Path: String): Boolean;
var Next: String; Attributes: LongWord;
begin
  Result := False;
  Path := ExpandFileName(Path);
  while Path <> '' do begin
    Attributes := AcceptanceAttributes(Path);
    if (Attributes <> $FFFFFFFF) and ((Attributes and $400) <> 0) then Exit;
    Next := ExtractFileDir(RemoveBackslashUnlessRoot(Path));
    if CompareText(Next, Path) = 0 then Break;
    Path := Next;
  end;
  Result := True;
end;
function AcceptanceRoot(): String;
begin
  Result := RemoveBackslashUnlessRoot(GetEnv('SAP_LENS_INSTALLER_ACCEPTANCE_ROOT'));
end;
function AcceptanceDirectory(Param: String): String;
begin
  Result := AddBackslash(AcceptanceRoot()) + 'application';
end;
function AcceptanceBoundary(AppDirectory: String): Boolean;
var Root, Marker, ProductionDirectory: String; Owner: AnsiString;
begin
  Result := False;
  Root := ExtractFileDir(RemoveBackslashUnlessRoot(AppDirectory));
  if CompareText(ExpandFileName(Root), ExpandFileName(BoundAcceptanceRoot())) <> 0 then Exit;
  if CompareText(ExtractFileName(Root), 'sap-lens-installer-{#AcceptanceId}') <> 0 then Exit;
  if CompareText(ExpandFileName(AppDirectory), AddBackslash(ExpandFileName(Root)) + 'application') <> 0 then Exit;
  if not NoAcceptanceLinks(AppDirectory) or not NoAcceptanceLinks(AddBackslash(Root) + 'data') or
     not NoAcceptanceLinks(AddBackslash(Root) + 'backups') then Exit;
  Marker := AddBackslash(Root) + '.owner';
  if not NoAcceptanceLinks(Marker) or not LoadStringFromFile(Marker, Owner) then Exit;
  if String(Owner) <> '{#AcceptanceId}' then Exit;
  RegQueryStringValue(HKCU, '{#ProductionRegistryPath}', 'InstallLocation', ProductionDirectory);
  if ProductionDirectory <> '' then begin
    ProductionDirectory := AddBackslash(ExpandFileName(ProductionDirectory));
    if Pos(Uppercase(ProductionDirectory), Uppercase(AddBackslash(ExpandFileName(Root)))) = 1 then Exit;
  end;
  Result := True;
end;
function InitializeUninstall(): Boolean;
begin
  Result := AcceptanceBoundary(ExpandConstant('{app}'));
  if not Result then SuppressibleMsgBox('Test-only uninstall boundary differs. Preserve the acceptance workspace and inspect its ownership marker.', mbError, MB_OK, IDOK);
end;
#endif
function RuntimeVersion(Root: Integer): Boolean;
var Value: String; Actual, Minimum: Int64;
begin
  Result := RegQueryStringValue(Root, WebViewKey, 'pv', Value) and
    StrToVersion(Value, Actual) and StrToVersion('86.0.622.0', Minimum);
  if Result then Result := ComparePackedVersion(Actual, Minimum) >= 0;
end;
function InitializeSetup(): Boolean;
begin
#ifdef AcceptanceId
  Result := (AcceptanceRoot() <> '') and AcceptanceBoundary(AcceptanceDirectory('')) and
    (CompareText(ExtractFileDir(ExpandConstant('{srcexe}')), AcceptanceRoot()) = 0);
  if not Result then begin
    SuppressibleMsgBox('Test-only Setup requires its isolated acceptance workspace. No installed application will be changed.', mbError, MB_OK, IDOK);
    Exit;
  end;
#endif
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
#ifdef AcceptanceId
  if not AcceptanceBoundary(ExpandConstant('{app}')) or
     (CompareText(ExtractFileDir(RemoveBackslashUnlessRoot(ExpandConstant('{app}'))), AcceptanceRoot()) <> 0) then begin
    Result := 'Test-only installation directory differs. No installed files were changed.';
    Exit;
  end;
#endif
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
#ifdef AcceptanceId
  DataDirectory := AddBackslash(AcceptanceRoot()) + 'data';
#else
  DataDirectory := GetEnv('SAP_LENS_CONFIG_DIR');
  if DataDirectory = '' then DataDirectory := ExpandConstant('{localappdata}\SAP Lens');
#endif
  DataDirectory := RemoveBackslashUnlessRoot(DataDirectory);
  if Pos('"', DataDirectory) <> 0 then begin Result := 'Invalid data-directory override.'; Exit; end;
  if DirExists(DataDirectory) and HasFiles(DataDirectory) then begin
    // The pre-upgrade backup is always encrypted and needs a protected key outside the data directory. Check that first and say so before anything
    // changes. There is no unencrypted fallback and the backup is never skipped.
    if not Exec(TemporaryExe, '--maintenance check-backup-key --data ' + Quoted(DataDirectory), '', SW_HIDE, ewWaitUntilTerminated, ExitCode) or (ExitCode <> 0) then begin
      Result := 'Setup needs a protected backup key before it can back up your data. Open SAP Lens, go to Settings > Backup & Restore, create or select the backup key, then run Setup again. Nothing was installed or changed and your data is intact. Setup never skips this backup and never creates an unencrypted one.';
      Exit;
    end;
#ifdef AcceptanceId
    BackupDirectory := AddBackslash(AcceptanceRoot()) + 'backups';
#else
    BackupDirectory := GetEnv('SAP_LENS_BACKUP_DIR');
    if BackupDirectory = '' then BackupDirectory := ExpandConstant('{localappdata}\SAP Lens Backups');
#endif
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
