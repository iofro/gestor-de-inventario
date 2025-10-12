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
Source: "..\svfe-api-firmador\*"; DestDir: "{app}\svfe-api-firmador"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: "uploads\*"

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
  APP_ID = '{7ACDE88C-3C97-47F0-A0F1-8BFC734E7373}';
  PARALLEL_INSTALL_HINT = 'Para reinstalar en paralelo, seleccione otra carpeta distinta a la instalación existente.';

function ReadPrevDirFromKey(RootKey: Integer; const SubKey, ValueName: string; var OutDir: string): Boolean;
begin
  Result := RegQueryStringValue(RootKey, SubKey, ValueName, OutDir) and DirExists(OutDir);
end;

function FindPreviousAppDir(const AppId, DefaultDir: string): string;
var
  Key, D: string;
begin
  Key := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + AppId + '_is1';
  D := '';

  if ReadPrevDirFromKey(HKLM, Key, 'Inno Setup: App Path', D) then
  begin
    Result := D;
    Exit;
  end;

  if ReadPrevDirFromKey(HKLM, Key, 'InstallLocation', D) then
  begin
    Result := D;
    Exit;
  end;

  if IsWin64 and ReadPrevDirFromKey(HKLM64, Key, 'Inno Setup: App Path', D) then
  begin
    Result := D;
    Exit;
  end;

  if IsWin64 and ReadPrevDirFromKey(HKLM64, Key, 'InstallLocation', D) then
  begin
    Result := D;
    Exit;
  end;

  if ReadPrevDirFromKey(HKCU, Key, 'Inno Setup: App Path', D) then
  begin
    Result := D;
    Exit;
  end;

  if ReadPrevDirFromKey(HKCU, Key, 'InstallLocation', D) then
  begin
    Result := D;
    Exit;
  end;

  Result := DefaultDir;
end;

var
  PrevDir: string;
  RequireDifferentDir: Boolean;
  IsUpgrade: Boolean;
  PrevDirInitialized: Boolean;
  DefaultInstallDir: string;

procedure EnsurePrevDirInitialized;
begin
  if PrevDirInitialized then
    Exit;

  DefaultInstallDir := ExpandConstant('{autopf}\Vertex DTE');
  PrevDir := FindPreviousAppDir(APP_ID, DefaultInstallDir);
  PrevDirInitialized := True;
end;

function GetDefaultDirName(Default: string): string;
begin
  EnsurePrevDirInitialized;

  if (PrevDir <> '') and DirExists(PrevDir) then
    Result := PrevDir
  else
    Result := DefaultInstallDir;
end;

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
    WizardForm.NextButton.Enabled := WizardForm.DirEdit.Text <> '';
end;

procedure DirEditChange(Sender: TObject);
begin
  UpdateDirSelectionState;
end;

procedure InitializeWizard;
var
  Response: Integer;
begin
  EnsurePrevDirInitialized;
  RequireDifferentDir := False;
  IsUpgrade := False;

  WizardForm.DirEdit.Text := GetDefaultDirName('');

  if WizardSilent then
  begin
    if (PrevDir <> '') and DirExists(PrevDir) then
      IsUpgrade := True
    else
      IsUpgrade := False;
    Exit;
  end;

  WizardForm.DirEdit.OnChange := @DirEditChange;
  UpdateDirSelectionState;

  if (PrevDir <> '') and DirExists(PrevDir) then
  begin
    Response := MsgBox('Se detectó una instalación existente en: ' + PrevDir + NL + '¿Desea actualizar?', mbConfirmation, MB_YESNO or MB_DEFBUTTON1);
    if Response = IDYES then
    begin
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
      WizardForm.SelectDirLabel.Caption := WizardForm.SelectDirLabel.Caption + NL + PARALLEL_INSTALL_HINT;
      MsgBox(PARALLEL_INSTALL_HINT, mbInformation, MB_OK);
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
    MsgBox(PARALLEL_INSTALL_HINT, mbInformation, MB_OK);
    Result := False;
  end;
end;
