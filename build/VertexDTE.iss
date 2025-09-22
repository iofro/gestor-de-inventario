#define AppVersion Trim(ReadIni("..\\app_version.ini", "VertexDTE", "version", "1.0.0"))

[Setup]
AppName=Vertex DTE
AppVersion={#AppVersion}
DefaultDirName={pf}\Vertex DTE
DefaultGroupName=Vertex DTE
OutputBaseFilename=VertexDTE-Setup
Compression=lzma
SolidCompression=yes
SetupIconFile=..\assets\app.ico

[Files]
Source: "dist\VertexDTE\*"; DestDir: "{app}"; Flags: recursesubdirs

[Icons]
Name: "{group}\Vertex DTE"; Filename: "{app}\VertexDTE.exe"
Name: "{commondesktop}\Vertex DTE"; Filename: "{app}\VertexDTE.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Run]
Filename: "{app}\VertexDTE.exe"; Description: "Ejecutar Vertex DTE"; Flags: nowait postinstall skipifsilent
