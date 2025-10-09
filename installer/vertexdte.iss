; Vertex DTE installer generated with Inno Setup

#ifndef AppVersion
#define AppVersion "0.0.0"
#endif

#ifndef OutputDir
#define OutputDir "build\\installer"
#endif

[Setup]
AppId={{7ACDE88C-3C97-47F0-A0F1-8BFC734E7373}}
AppName=Vertex DTE
AppVersion={#AppVersion}
DefaultDirName={autopf}\Vertex DTE
UsePreviousAppDir=yes
DirExistsWarning=no
OutputDir={#OutputDir}
OutputBaseFilename=VertexDTE-Setup-{#AppVersion}
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
  ModePage: TWizardPage;
  InstallRadio: TNewRadioButton;
  UpdateRadio: TNewRadioButton;
  DefaultInstallDir: string;
  CurrentDirHasInstall: Boolean;

procedure RefreshUpgradeState(const Dir: string); forward;

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

function HasModeSelection: Boolean;
begin
  Result := ModePage <> nil;
end;

function UserWantsUpgrade: Boolean;
begin
  if not HasModeSelection then
    Result := True
  else if Assigned(UpdateRadio) then
    Result := UpdateRadio.Checked
  else
    Result := False;
end;

procedure UpdateModeControls;
begin
  if not HasModeSelection then
    Exit;

  if Assigned(UpdateRadio) and UpdateRadio.Checked then
  begin
    if (DetectedInstallDir <> '') and (CompareText(WizardForm.DirEdit.Text, DetectedInstallDir) <> 0) then
      WizardForm.DirEdit.Text := DetectedInstallDir;
    if DetectedInstallDir <> '' then
    begin
      WizardForm.DirBrowseButton.Enabled := False;
      WizardForm.DirEdit.Enabled := False;
    end
    else
    begin
      WizardForm.DirBrowseButton.Enabled := True;
      WizardForm.DirEdit.Enabled := True;
    end;
  end
  else
  begin
    WizardForm.DirBrowseButton.Enabled := True;
    WizardForm.DirEdit.Enabled := True;
    if (DetectedInstallDir <> '') and (DefaultInstallDir <> '') then
    begin
      if (CompareText(WizardForm.DirEdit.Text, DetectedInstallDir) = 0)
        and (CompareText(DefaultInstallDir, DetectedInstallDir) <> 0) then
        WizardForm.DirEdit.Text := DefaultInstallDir;
    end;
  end;
end;

procedure HandleModeSelectionChanged(Sender: TObject);
begin
  UpdateModeControls;
  RefreshUpgradeState(WizardForm.DirEdit.Text);
end;

procedure CreateModeSelectionPage;
var
  InfoLabel: TNewStaticText;
  TopOffset: Integer;
begin
  ModePage := CreateCustomPage(
    wpWelcome,
    'Modo de instalación',
    'Selecciona si deseas instalar Vertex DTE desde cero o actualizar la copia existente.'
  );

  InfoLabel := TNewStaticText.Create(ModePage.Surface);
  InfoLabel.Parent := ModePage.Surface;
  InfoLabel.Left := 0;
  InfoLabel.Top := 0;
  InfoLabel.Width := ModePage.SurfaceWidth;
  InfoLabel.Height := ScaleY(48);
  InfoLabel.AutoSize := False;
  InfoLabel.WordWrap := True;
  InfoLabel.Caption :=
    'El asistente detectó una instalación previa de Vertex DTE. ' +
    'Puedes instalar una copia nueva en otra carpeta o actualizar la existente.';

  TopOffset := InfoLabel.Top + InfoLabel.Height + ScaleY(12);

  InstallRadio := TNewRadioButton.Create(ModePage.Surface);
  InstallRadio.Parent := ModePage.Surface;
  InstallRadio.Left := 0;
  InstallRadio.Top := TopOffset;
  InstallRadio.Width := ModePage.SurfaceWidth;
  InstallRadio.Caption := 'Instalar una copia nueva en una carpeta elegida por mí';
  InstallRadio.Checked := False;
  InstallRadio.OnClick := @HandleModeSelectionChanged;

  TopOffset := InstallRadio.Top + InstallRadio.Height + ScaleY(8);

  UpdateRadio := TNewRadioButton.Create(ModePage.Surface);
  UpdateRadio.Parent := ModePage.Surface;
  UpdateRadio.Left := 0;
  UpdateRadio.Top := TopOffset;
  UpdateRadio.Width := ModePage.SurfaceWidth;
  UpdateRadio.Caption := 'Actualizar la instalación existente detectada automáticamente';
  UpdateRadio.Checked := True;
  UpdateRadio.OnClick := @HandleModeSelectionChanged;
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
    if PageID = wpReady then
      WizardForm.NextButton.Caption := 'Actualizar'
    else if PageID = wpFinished then
      WizardForm.NextButton.Caption := SetupMessage(msgButtonFinish)
    else
      WizardForm.NextButton.Caption := SetupMessage(msgButtonNext);
    WizardForm.Caption := DefaultWizardCaption + ' — Actualizar';
  end
  else
  begin
    if PageID = wpReady then
      WizardForm.NextButton.Caption := SetupMessage(msgButtonInstall)
    else if PageID = wpFinished then
      WizardForm.NextButton.Caption := SetupMessage(msgButtonFinish)
    else
      WizardForm.NextButton.Caption := SetupMessage(msgButtonNext);
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
    WizardForm.WelcomeLabel1.Caption := DefaultWelcomeLabel1;
    WizardForm.WelcomeLabel2.Caption := DefaultWelcomeLabel2;
    if CurrentDirHasInstall then
    begin
      UpgradeLabel.Caption :=
        'Se detectó una instalación existente en: ' + WizardForm.DirEdit.Text + #13#10 +
        'Selecciona "Actualizar" o elige otra carpeta para una instalación nueva.';
      UpgradeLabel.Visible := True;
    end
    else if HasModeSelection and UserWantsUpgrade then
    begin
      UpgradeLabel.Caption := 'No se encontró una instalación existente en la carpeta seleccionada.';
      UpgradeLabel.Visible := True;
    end
    else
      UpgradeLabel.Visible := False;
  end;
end;

procedure RefreshUpgradeState(const Dir: string);
begin
  CurrentDirHasInstall := DirContainsExistingInstall(Dir);

  if UserWantsUpgrade and CurrentDirHasInstall then
  begin
    IsUpgrade := True;
    DetectedInstallDir := Dir;
  end
  else
  begin
    IsUpgrade := False;
    if not UserWantsUpgrade then
    begin
      if not CurrentDirHasInstall then
        DetectedInstallDir := '';
    end
    else if CurrentDirHasInstall then
      DetectedInstallDir := Dir
    else if HasModeSelection then
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
var
  ParentControl: TWinControl;
  LeftMargin: Integer;
begin
  ParentControl := WizardForm.DirEdit.Parent;
  if ParentControl = nil then
    ParentControl := WizardForm;
  UpgradeLabel := TNewStaticText.Create(WizardForm);
  UpgradeLabel.Parent := ParentControl;
  LeftMargin := WizardForm.DirEdit.Left;
  UpgradeLabel.Left := LeftMargin;
  UpgradeLabel.Top := WizardForm.DirEdit.Top + WizardForm.DirEdit.Height + ScaleY(8);
  UpgradeLabel.Width := WizardForm.DirEdit.Width;
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

  ModePage := nil;
  InstallRadio := nil;
  UpdateRadio := nil;
  CurrentDirHasInstall := False;

  DefaultInstallDir := ExpandConstant('{autopf}\Vertex DTE');
  if DefaultInstallDir = '' then
    DefaultInstallDir := WizardForm.DirEdit.Text;

  InitializeUpgradeLabel;

  ExistingDir := DetectExistingInstallDir;
  if ExistingDir <> '' then
  begin
    CreateModeSelectionPage;
    WizardForm.DirEdit.Text := ExistingDir;
    DetectedInstallDir := ExistingDir;
    IsUpgrade := True;
  end
  else
  begin
    IsUpgrade := False;
    DetectedInstallDir := '';
  end;

  UpdateModeControls;
  WizardForm.DirEdit.OnChange := @DirEditChange;
  RefreshUpgradeState(WizardForm.DirEdit.Text);
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if HasModeSelection and ((ModePage <> nil) and (CurPageID = ModePage.ID)) then
  begin
    UpdateModeControls;
    RefreshUpgradeState(WizardForm.DirEdit.Text);
  end
  else if (CurPageID = wpSelectDir) or (CurPageID = wpReady) or (CurPageID = wpWelcome) then
  begin
    if HasModeSelection and (CurPageID = wpSelectDir) then
      UpdateModeControls;
    RefreshUpgradeState(WizardForm.DirEdit.Text);
  end
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
