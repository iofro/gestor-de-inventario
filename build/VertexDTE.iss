#define VersionFile "..\\VERSION"
#define AppVersion Trim(StringChange(GetIniString(VersionFile, "VertexDTE", "version", "1.0.0"), "\n", ""))

[Setup]
AppName=Vertex DTE
AppVersion={#AppVersion}
DefaultDirName={pf}\\Vertex DTE
DefaultGroupName=Vertex DTE
OutputBaseFilename=VertexDTE-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "dist\\VertexDTE\\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\\Vertex DTE"; Filename: "{app}\\VertexDTE.exe"
Name: "{commondesktop}\\Vertex DTE"; Filename: "{app}\\VertexDTE.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked

[Run]
Filename: "{app}\\VertexDTE.exe"; Description: "Ejecutar Vertex DTE"; Flags: nowait postinstall skipifsilent
