; Vertex DTE installer generated with Inno Setup

#ifdef AppVersion
#else
#define AppVersion "0.0.0"
#endif

#ifdef BuildOutputDir
#else
#define BuildOutputDir "build\\installer"
#endif

[Setup]
AppId={{7ACDE88C-3C97-47F0-A0F1-8BFC734E7373}}
AppName=Vertex DTE
AppVersion={#AppVersion}
DefaultDirName={autopf}\Vertex DTE
UsePreviousAppDir=yes
DirExistsWarning=no
OutputDir={#BuildOutputDir}
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
Source: "..\dist\InventarioFarmacia\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: "tools\verificador\*"
Source: "..\svfe-api-firmador\*"; DestDir: "{app}\svfe-api-firmador"; Flags: recursesubdirs createallsubdirs ignoreversion

[Dirs]
Name: "{userappdata}\VertexDTE"; Flags: uninsneveruninstall
Name: "{app}\svfe-api-firmador\uploads"; Flags: uninsneveruninstall

[Tasks]
Name: desktopicon; Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked

[Icons]
Name: "{autoprograms}\Vertex DTE"; Filename: "{app}\InventarioFarmacia.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Vertex DTE"; Filename: "{app}\InventarioFarmacia.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Code]
const
  NL = #13#10;

var
  PrevDir: string;
  RequireDifferentDir: Boolean;
  IsUpgrade: Boolean;
  PrevDirEditOnChange: TNotifyEvent;

function NormalizePath(const Value: string): string;
begin
  Result := UpperCase(RemoveBackslashUnlessRoot(ExpandConstant(Trim(Value))));
end;

function IsSamePath(const A, B: string): Boolean;
begin
  Result := NormalizePath(A) = NormalizePath(B);
end;

procedure UpdateDirSelectionState;
begin
  if RequireDifferentDir then
    WizardForm.NextButton.Enabled := not IsSamePath(WizardForm.DirEdit.Text, PrevDir)
  else
    WizardForm.NextButton.Enabled := True;
end;

procedure DirEditChange(Sender: TObject);
begin
  if Assigned(PrevDirEditOnChange) then
    PrevDirEditOnChange(Sender);
  UpdateDirSelectionState;
end;

procedure InitializeWizard;
var
  Response: Integer;
  DefaultInstallDir: string;
begin
  PrevDir := GetPreviousAppDir('{#SetupSetting("AppId")}', '');
  RequireDifferentDir := False;
  IsUpgrade := False;

  DefaultInstallDir := ExpandConstant('{autopf}\Vertex DTE');
  if DefaultInstallDir = '' then
    DefaultInstallDir := WizardForm.DirEdit.Text;

  if WizardSilent then
  begin
    if (PrevDir <> '') and DirExists(PrevDir) then
    begin
      WizardDirValue := PrevDir;
      IsUpgrade := True;
    end
    else
    begin
      WizardDirValue := DefaultInstallDir;
      IsUpgrade := False;
    end;
    Exit;
  end;

  PrevDirEditOnChange := WizardForm.DirEdit.OnChange;
  WizardForm.DirEdit.OnChange := @DirEditChange;

  if (PrevDir <> '') and DirExists(PrevDir) then
  begin
    Response := MsgBox(Format('Se detectó una instalación existente en: %s.%s¿Desea actualizar?', [PrevDir, NL]), mbConfirmation, MB_YESNO or MB_DEFBUTTON1);
    if Response = IDYES then
    begin
      WizardDirValue := PrevDir;
      WizardForm.DirEdit.Text := PrevDir;
      WizardForm.DirEdit.Enabled := False;
      WizardForm.DirBrowseButton.Enabled := False;
      RequireDifferentDir := False;
      IsUpgrade := True;
    end
    else
    begin
      RequireDifferentDir := True;
      IsUpgrade := False;
      WizardForm.DirEdit.Enabled := True;
      WizardForm.DirBrowseButton.Enabled := True;
      WizardForm.DirEdit.Text := DefaultInstallDir;
      WizardDirValue := WizardForm.DirEdit.Text;
      WizardForm.SelectDirLabel.Caption := WizardForm.SelectDirLabel.Caption + NL + 'Para reinstalar en paralelo, seleccione otra carpeta distinta a la instalación existente.';
      MsgBox('Para reinstalar en paralelo, seleccione otra carpeta distinta a la instalación existente.', mbInformation, MB_OK);
    end;
    UpdateDirSelectionState;
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpSelectDir then
    UpdateDirSelectionState;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpSelectDir) and RequireDifferentDir and IsSamePath(WizardForm.DirEdit.Text, PrevDir) then
  begin
    MsgBox('Para reinstalar en paralelo, seleccione otra carpeta distinta a la instalación existente.', mbInformation, MB_OK);
    Result := False;
  end;
end;
