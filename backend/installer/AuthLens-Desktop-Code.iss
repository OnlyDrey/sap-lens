// Desktop-only callbacks; Server never includes this file.
function DesktopData(Param: String): String;
begin
  Result := ExpandConstant('{param:DATADIR|}');
  if Result = '' then RegQueryStringValue(HKCU, '{#VersionKey}', 'DataDirectory', Result);
  if Result = '' then Result := ExpandConstant('{localappdata}\AuthLens\data');
end;

function InstallerArguments(): String;
begin
  Result := ' -InstallRoot "' + ExpandConstant('{app}') + '" -DataDirectory "' + DesktopData('') + '"';
end;

function PrepareInstaller(): String;
begin
  Result := '';
end;
