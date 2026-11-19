; SAP Lens Desktop (.NET) per-user installer. Built by scripts/build-installers.ps1 from a verified release folder (build-release.ps1):
;   ISCC /DFullVersion=2.0.0-alpha.1 /DNumericVersion=2.0.0.1 /DReleaseDir=<release folder> AuthLens-Desktop.iss
; Its own AppId: it never upgrades, replaces or removes SAP Lens v1 (deploy/windows/desktop-installer.iss, %LOCALAPPDATA%\Programs\SAP Lens and
; %LOCALAPPDATA%\SAP Lens). Data lives in %LOCALAPPDATA%\SAP Lens Desktop (or a kept %LOCALAPPDATA%\SAP Lens 2 Prototype) and is never deleted:
; upgrades replace the executable only, the application backs the database up itself before any schema migration, and uninstall removes only the
; installed files. Silent: SAP-Lens-<version>-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART [/LOG=<file>]
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
#define AppIdGuid "869E2A71-839D-4F08-A626-CD87F1021A39"
#define V1AppIdGuid "5DB5BC51-A860-44CA-93CA-09AE85812DF0"
#define VersionKey "Software\SAP Lens\Desktop"
#define V1UninstallPath "Software\Microsoft\Windows\CurrentVersion\Uninstall\{" + V1AppIdGuid + "}_is1"

[Setup]
AppId={{{#AppIdGuid}}
AppName=SAP Lens
AppVersion={#FullVersion}
AppVerName=SAP Lens Desktop {#FullVersion}
AppPublisher=SAP Lens
DefaultDirName={localappdata}\Programs\SAP Lens Desktop
UsePreviousAppDir=yes
DisableDirPage=auto
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.18362
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
SetupIconFile={#ProductIcon}
UninstallDisplayIcon={app}\AuthLens.exe
UninstallDisplayName=SAP Lens Desktop
; The running Desktop (current or earlier prototype folder) must close first; Setup never terminates it.
AppMutex=Local\AuthLensDotnetDesktop,Local\SapLens2Prototype
CloseApplications=no
RestartApplications=no
VersionInfoVersion={#NumericVersion}
VersionInfoTextVersion={#FullVersion}
VersionInfoProductName=SAP Lens
VersionInfoProductVersion={#NumericVersion}
VersionInfoProductTextVersion={#FullVersion}
VersionInfoDescription=SAP Lens Desktop Setup
OutputBaseFilename=SAP-Lens-{#FullVersion}-Setup

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#ReleaseDir}\desktop\AuthLens.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ReleaseDir}\README.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ReleaseDir}\build-manifest.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}\LICENSE.md"; DestDir: "{app}"; Flags: ignoreversion

[Registry]
; Installed numeric version, read by the next Setup to refuse a downgrade. Removed on uninstall; it holds no data.
Root: HKCU; Subkey: "{#VersionKey}"; ValueType: string; ValueName: "FileVersion"; ValueData: "{#NumericVersion}"; Flags: uninsdeletekey

[Icons]
Name: "{autoprograms}\SAP Lens"; Filename: "{app}\AuthLens.exe"
Name: "{autodesktop}\SAP Lens"; Filename: "{app}\AuthLens.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AuthLens.exe"; Description: "Launch SAP Lens"; Flags: nowait postinstall skipifsilent

; No [UninstallDelete] and no [InstallDelete]: the data folder, logs, WebView2 profile and backups are never removed by Setup or uninstall.

[Code]
const
  WebViewKey = 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  V1UninstallKey = '{#V1UninstallPath}';

function RuntimeVersion(Root: Integer): Boolean;
var Value: String; Actual, Minimum: Int64;
begin
  Result := RegQueryStringValue(Root, WebViewKey, 'pv', Value) and StrToVersion(Value, Actual) and StrToVersion('86.0.622.0', Minimum);
  if Result then Result := ComparePackedVersion(Actual, Minimum) >= 0;
end;

function InitializeSetup(): Boolean;
var Installed: String; InstalledVersion, ThisVersion: Int64;
begin
  Result := RuntimeVersion(HKCU) or RuntimeVersion(HKLM32) or RuntimeVersion(HKLM64);
  if not Result then begin
    SuppressibleMsgBox('Microsoft Edge WebView2 Runtime 86.0.622.0 or newer is required. Install the Evergreen Runtime through your approved software distribution, then run Setup again. Nothing was installed.', mbError, MB_OK, IDOK);
    Exit;
  end;
  if RegQueryStringValue(HKCU, '{#VersionKey}', 'FileVersion', Installed) and StrToVersion(Installed, InstalledVersion) and
     StrToVersion('{#NumericVersion}', ThisVersion) and (ComparePackedVersion(ThisVersion, InstalledVersion) < 0) then begin
    SuppressibleMsgBox('A newer SAP Lens Desktop (' + Installed + ') is installed. Downgrades are not supported; nothing was changed.', mbError, MB_OK, IDOK);
    Result := False;
    Exit;
  end;
  if RegKeyExists(HKCU, V1UninstallKey) then
    SuppressibleMsgBox('SAP Lens v1 is installed on this account. It stays installed and unchanged, with its own data; this Setup installs SAP Lens Desktop (.NET) beside it.', mbInformation, MB_OK, IDOK);
end;
