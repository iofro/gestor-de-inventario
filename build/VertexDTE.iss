#define VersionFile "..\\VERSION"
#define DefaultAppVersion Trim(StringChange(GetIniString(VersionFile, "VertexDTE", "version", "1.0.0"), "\n", ""))
#define AppVersion GetStringParam("AppVersion", DefaultAppVersion)
#define OutputDirParam GetStringParam("OutputDir", "build\\Output")

[Setup]
AppName=Vertex DTE
AppVersion={#AppVersion}
DefaultDirName={pf}\\Vertex DTE
DefaultGroupName=Vertex DTE
OutputDir={#OutputDirParam}
OutputBaseFilename=VertexDTE-Setup-{#AppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "dist\\VertexDTE\\*"; DestDir: "{app}"; Flags: recursesubdirs

[Icons]
Name: "{group}\\Vertex DTE"; Filename: "{app}\\VertexDTE.exe"
Name: "{commondesktop}\\Vertex DTE"; Filename: "{app}\\VertexDTE.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked

[Run]
Filename: "{app}\\VertexDTE.exe"; Description: "Ejecutar Vertex DTE"; Flags: nowait postinstall skipifsilent

[Code]
function GetSignerPath(): string;
var
  SignerDir: string;
  FindRec: TFindRec;
begin
  SignerDir := ExpandConstant('{app}\extras\firmador');
  Result := '';
  if FindFirst(SignerDir + '\*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) = 0 then
        begin
          Result := SignerDir + '\' + FindRec.Name;
          Break;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;

  if Result = '' then
    Result := SignerDir;
end;

procedure CreateDefaultSettings();
var
  AppDataDir: string;
  JsonPath: string;
  SignerEntry: string;
begin
  AppDataDir := ExpandConstant('{userappdata}\VertexDTE');
  if not DirExists(AppDataDir) then
    ForceDirectories(AppDataDir);

  SignerEntry := GetSignerPath();
  SignerEntry := StringChange(SignerEntry, '\', '\\');
  JsonPath := AppDataDir + '\settings.json';
  SaveStringToFile(JsonPath, Format('{"firmador_path": "%s"}', [SignerEntry]), False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    CreateDefaultSettings();
end;
