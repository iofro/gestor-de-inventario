#define VersionFile "..\VERSION"
#define DefaultVersion Trim(StringChange(GetIniString(VersionFile, "VertexDTE", "version", "1.0.0"), "\n", ""))
#define AppVersionParam GetStringParam("AppVersion", "")
#if AppVersionParam == ""
  #define AppVersion DefaultVersion
#else
  #define AppVersion AppVersionParam
#endif
#define OutputDirParam GetStringParam("OutputDir", "")

[Setup]
AppName=Vertex DTE
AppVersion={#AppVersion}
DefaultDirName={pf}\Vertex DTE
DefaultGroupName=Vertex DTE
OutputBaseFilename=VertexDTE-Setup-{#AppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
#if OutputDirParam != ""
OutputDir={#OutputDirParam}
#endif

[Files]
Source: "dist\VertexDTE\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Vertex DTE"; Filename: "{app}\VertexDTE.exe"
Name: "{commondesktop}\Vertex DTE"; Filename: "{app}\VertexDTE.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked

[Run]
Filename: "{app}\VertexDTE.exe"; Description: "Ejecutar Vertex DTE"; Flags: nowait postinstall skipifsilent
