// Shared Pascal Script include: both installers include this inside their [Code] section.
// Application replacement uses the existing verified deployment/backup adapters after payload extraction.
#if InstallerMode == "Desktop"
function DesktopData(Param: String): String;
begin
  Result := ExpandConstant('{param:DATADIR|}');
  if Result = '' then RegQueryStringValue(HKCU, '{#VersionKey}', 'DataDirectory', Result);
  if Result = '' then Result := ExpandConstant('{localappdata}\AuthLens\data');
end;
#endif
procedure CurStepChanged(CurStep: TSetupStep);
var Arguments, Config, Data: String; Code: Integer;
begin
  if CurStep <> ssPostInstall then Exit;
  Arguments := '-NoProfile -NonInteractive -File "' + ExpandConstant('{app}\setup\{#PackageName}\tools\Install-AuthLens.ps1') +
    '" -Mode {#InstallerMode} -Package "' + ExpandConstant('{app}\setup\{#PackageName}\payload\{#PackageName}') + '" -Yes';
  #if InstallerMode == "Server"
  Config := ExpandConstant('{param:CONFIGFILE|}');
  Arguments := Arguments + ' -ConfigFile "' + Config + '" -InstallRoot "' + ExpandConstant('{app}') + '"';
  #else
  Data := DesktopData('');
  Arguments := Arguments + ' -InstallRoot "' + ExpandConstant('{app}') + '" -DataDirectory "' + Data + '"';
  #endif
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Arguments, '', SW_HIDE, ewWaitUntilTerminated, Code) then Code := 4;
  if Code <> 0 then
    RaiseException('AuthLens transaction failed (exit ' + IntToStr(Code) + '). The previous version was restored when safe. If recovery is required, retain the installation journal and its recovery tools; no data is deleted.');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var Arguments, Config: String; Code: Integer;
begin
  Result := '';
  if DirExists(ExpandConstant('{app}\setup\{#PackageName}')) then begin
    Result := 'This exact Setup payload already exists. It is never overwritten. Review its recovery journal or use another verified package.';
    Exit;
  end;
  #if InstallerMode == "Server"
  Config := ExpandConstant('{param:CONFIGFILE|}');
  if Config = '' then begin
    Result := 'Server Setup requires /CONFIGFILE="absolute deployment configuration path". Configuration, credentials, TLS and keys are never inferred or replaced.';
    Exit;
  end;
  // Provision the dedicated root with its protected DACL before Inno creates payload directories underneath it.
  ExtractTemporaryFiles('{tmp}\AuthLensPrerequisites\{#PackageName}\tools\*');
  Arguments := '-NoProfile -NonInteractive -File "' + ExpandConstant('{tmp}\AuthLensPrerequisites\{#PackageName}\tools\Install-AuthLens.ps1') +
    '" -Mode Server -PrepareOnly -ConfigFile "' + Config + '" -InstallRoot "' + ExpandConstant('{app}') + '" -Yes';
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Arguments, '', SW_HIDE, ewWaitUntilTerminated, Code) then Code := 4;
  if Code <> 0 then Result := 'Server root security preparation refused (exit ' + IntToStr(Code) + '). No service was changed.';
  #endif
end;
