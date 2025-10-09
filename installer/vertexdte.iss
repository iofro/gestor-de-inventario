; Vertex DTE installer generated with Inno Setup

#ifndef AppVersion
#define AppVersion "0.0.0"
#endif

[Setup]
AppId={{7ACDE88C-3C97-47F0-A0F1-8BFC734E7373}}
AppName=Vertex DTE
AppVersion={#AppVersion}
DefaultDirName={autopf}\Vertex DTE
UsePreviousAppDir=yes
DirExistsWarning=no
OutputDir=build\installer
OutputBaseFilename=VertexDTE-Setup
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64
AppPublisher=Vertex
MinVersion=10.0
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
AppMutex=VertexDTE_Running
DisableProgramGroupPage=yes

[Files]
Source: "..\dist\InventarioFarmacia\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\svfe-api-firmador\*"; DestDir: "{app}\svfe-api-firmador"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: "uploads\*"

[Dirs]
Name: "{app}\svfe-api-firmador\uploads"; Flags: uninsneveruninstall

[Tasks]
Name: desktopicon; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked

[Icons]
Name: "{autoprograms}\Vertex DTE"; Filename: "{app}\InventarioFarmacia.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Vertex DTE"; Filename: "{app}\InventarioFarmacia.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]

[UninstallDelete]
; No eliminar %APPDATA%\VertexDTE ni la carpeta uploads.

[Code]
var
  IsUpgrade: Boolean;
  DetectedInstallDir: string;
  UpgradeLabel: TNewStaticText;
  DefaultWizardCaption: string;
  DefaultWelcomeLabel1: string;
  DefaultWelcomeLabel2: string;

function QueryInstallLocationForRoot(const RootKey: Integer; const SubKey: string; var Value: string): Boolean;
begin
  Result := RegQueryStringValue(RootKey, SubKey, 'InstallLocation', Value);
  if not Result then
    Result := RegQueryStringValue(RootKey, SubKey, 'Inno Setup: App Path', Value);
end;

function GetRegisteredInstallDir: string;
var
  SubKey: string;
  Value: string;
begin
  Result := '';
  SubKey := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\Vertex DTE_is1';
  Value := '';
  if QueryInstallLocationForRoot(HKLM, SubKey, Value) then
  begin
    Result := Value;
    Exit;
  end;
  if IsWin64 then
  begin
    if QueryInstallLocationForRoot(HKLM64, SubKey, Value) then
    begin
      Result := Value;
      Exit;
    end;
  end;
  if QueryInstallLocationForRoot(HKCU, SubKey, Value) then
  begin
    Result := Value;
    Exit;
  end;
  if IsWin64 then
  begin
    if QueryInstallLocationForRoot(HKCU64, SubKey, Value) then
      Result := Value;
  end;
end;

function GetMarkerInstallDir: string;
var
  MarkerFile: string;
  Buffer: AnsiString;
begin
  MarkerFile := ExpandConstant('{commonappdata}\VertexDTE\install-path.txt');
  Buffer := '';
  if LoadStringFromFile(MarkerFile, Buffer) then
    Result := Trim(string(Buffer))
  else
    Result := '';
end;

function DirContainsExistingInstall(const Dir: string): Boolean;
var
  Path: string;
begin
  Result := False;
  if Dir = '' then
    Exit;
  Path := AddBackslash(Dir);
  if FileExists(Path + 'InventarioFarmacia.exe') then
  begin
    Result := True;
    Exit;
  end;
  if DirExists(Path + 'svfe-api-firmador') then
  begin
    Result := True;
    Exit;
  end;
  if FileExists(Path + '.vertex_install.json') then
    Result := True;
end;

function DetectExistingInstallDir: string;
var
  Candidate: string;
begin
  Result := '';

  Candidate := Trim(GetRegisteredInstallDir);
  if DirContainsExistingInstall(Candidate) then
  begin
    Result := Candidate;
    Exit;
  end;

  Candidate := Trim(GetMarkerInstallDir);
  if DirContainsExistingInstall(Candidate) then
  begin
    Result := Candidate;
    Exit;
  end;

  Candidate := ExpandConstant('{autopf}\Vertex DTE');
  if DirContainsExistingInstall(Candidate) then
  begin
    Result := Candidate;
    Exit;
  end;

  Candidate := ExpandConstant('{commonpf}\Vertex DTE');
  if (Result = '') and DirContainsExistingInstall(Candidate) then
  begin
    Result := Candidate;
    Exit;
  end;

  Candidate := ExpandConstant('{pf}\Vertex DTE');
  if DirContainsExistingInstall(Candidate) then
    Result := Candidate;
end;

procedure UpdateUpgradeCaptionForPage(const PageID: Integer);
begin
  if IsUpgrade then
  begin
    if WizardForm.NextButton.Visible then
      WizardForm.NextButton.Caption := 'Actualizar';
    if WizardForm.InstallButton.Visible then
      WizardForm.InstallButton.Caption := 'Actualizar';
    WizardForm.Caption := DefaultWizardCaption + ' — Actualizar';
  end
  else
  begin
    if WizardForm.NextButton.Visible then
      WizardForm.NextButton.Caption := SetupMessage(msgButtonNext);
    if WizardForm.InstallButton.Visible then
      WizardForm.InstallButton.Caption := SetupMessage(msgButtonInstall);
    WizardForm.Caption := DefaultWizardCaption;
  end;
end;

procedure UpdateUpgradeLabel;
begin
  if IsUpgrade then
  begin
    if DetectedInstallDir = '' then
      DetectedInstallDir := WizardForm.DirEdit.Text;
    UpgradeLabel.Caption := 'Se detectó una instalación existente en: ' + DetectedInstallDir;
    UpgradeLabel.Visible := True;
    WizardForm.WelcomeLabel1.Caption := 'Actualizar Vertex DTE';
    WizardForm.WelcomeLabel2.Caption := 'El instalador actualizará la versión instalada conservando la configuración.';
  end
  else
  begin
    UpgradeLabel.Visible := False;
    WizardForm.WelcomeLabel1.Caption := DefaultWelcomeLabel1;
    WizardForm.WelcomeLabel2.Caption := DefaultWelcomeLabel2;
  end;
end;

procedure RefreshUpgradeState(const Dir: string);
begin
  if DirContainsExistingInstall(Dir) then
  begin
    IsUpgrade := True;
    DetectedInstallDir := Dir;
  end
  else
  begin
    IsUpgrade := False;
    DetectedInstallDir := '';
  end;
  UpdateUpgradeLabel;
  UpdateUpgradeCaptionForPage(WizardForm.CurPageID);
end;

procedure DirEditChange(Sender: TObject);
begin
  RefreshUpgradeState(WizardForm.DirEdit.Text);
end;

procedure InitializeUpgradeLabel;
begin
  UpgradeLabel := TNewStaticText.Create(WizardForm.SelectDirPage);
  UpgradeLabel.Parent := WizardForm.SelectDirPage.Surface;
  UpgradeLabel.Left := WizardForm.SelectDirPage.SelectLabel.Left;
  UpgradeLabel.Top := WizardForm.DirEdit.Top + WizardForm.DirEdit.Height + ScaleY(8);
  UpgradeLabel.Width := WizardForm.SelectDirPage.SurfaceWidth;
  UpgradeLabel.AutoSize := False;
  UpgradeLabel.WordWrap := True;
  UpgradeLabel.Visible := False;
end;

procedure InitializeWizard;
var
  ExistingDir: string;
begin
  DefaultWizardCaption := WizardForm.Caption;
  DefaultWelcomeLabel1 := WizardForm.WelcomeLabel1.Caption;
  DefaultWelcomeLabel2 := WizardForm.WelcomeLabel2.Caption;

  InitializeUpgradeLabel;

  ExistingDir := DetectExistingInstallDir;
  if ExistingDir <> '' then
  begin
    WizardForm.DirEdit.Text := ExistingDir;
    DetectedInstallDir := ExistingDir;
    IsUpgrade := True;
  end
  else
  begin
    IsUpgrade := False;
    DetectedInstallDir := '';
  end;

  WizardForm.DirEdit.OnChange := @DirEditChange;
  RefreshUpgradeState(WizardForm.DirEdit.Text);
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpSelectDir) or (CurPageID = wpReady) or (CurPageID = wpWelcome) then
    RefreshUpgradeState(WizardForm.DirEdit.Text)
  else
    UpdateUpgradeCaptionForPage(CurPageID);
end;

function EscapeForJson(const Value: string): string;
var
  S: string;
begin
  S := Value;
  StringChange(S, '\', '\\');
  StringChange(S, '"', '\"');
  Result := S;
end;

procedure WriteInstallMarkers;
var
  MarkerDir: string;
  MarkerContent: string;
  AppDir: string;
begin
  AppDir := ExpandConstant('{app}');
  MarkerContent := '{'#13#10 +
    '  "app": "VertexDTE",'#13#10 +
    '  "version": "' + ExpandConstant('{#AppVersion}') + '",'#13#10 +
    '  "path": "' + EscapeForJson(AppDir) + '"'#13#10 +
    '}';
  SaveStringToFile(AddBackslash(AppDir) + '.vertex_install.json', MarkerContent, False);

  MarkerDir := ExpandConstant('{commonappdata}\VertexDTE');
  if ForceDirectories(MarkerDir) then
    SaveStringToFile(AddBackslash(MarkerDir) + 'install-path.txt', AppDir, False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    WriteInstallMarkers;
end;
