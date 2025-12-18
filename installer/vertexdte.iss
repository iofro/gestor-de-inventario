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
  PARALLEL_INSTALL_HINT = 'Para reinstalar en paralelo, seleccione otra carpeta distinta a la instalacion existente.';

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
  ShouldBackup: Boolean;
  BackupTarget: string;

function CopyDirRecursive(const Source, Dest: string): Boolean;
var
  FindRec: TFindRec;
  SrcPath, DestPath: string;
begin
  Result := False;
  if not DirExists(Source) then
    Exit;
  if not ForceDirectories(Dest) then
    Exit;

  if FindFirst(Source + '\*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name = '.') or (FindRec.Name = '..') then
          Continue;

        SrcPath := Source + '\' + FindRec.Name;
        DestPath := Dest + '\' + FindRec.Name;
        if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
        begin
          if not CopyDirRecursive(SrcPath, DestPath) then
            Exit;
        end
        else
        begin
          if not FileCopy(SrcPath, DestPath, False) then
            Exit;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;

  Result := True;
end;

function MakeUniqueDir(const BasePath: string): string;
var
  Candidate: string;
  Suffix: Integer;
begin
  Candidate := BasePath;
  Suffix := 1;
  while DirExists(Candidate) do
  begin
    Candidate := BasePath + '_' + IntToStr(Suffix);
    Suffix := Suffix + 1;
  end;
  Result := Candidate;
end;

procedure EnsurePrevDirInitialized;
begin
  if PrevDirInitialized then
    Exit;

  DefaultInstallDir := ExpandConstant('{autopf}\Vertex DTE');
  PrevDir := FindPreviousAppDir(APP_ID, DefaultInstallDir);
  PrevDirInitialized := True;
end;

function HasValidPrevDir: Boolean;
begin
  Result := (PrevDir <> '') and DirExists(PrevDir);
end;

function GetDefaultDirName(Default: string): string;
begin
  EnsurePrevDirInitialized;

  if HasValidPrevDir then
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
    // No tocar el directorio aquí; GetDefaultDirName ya lo decide.
    IsUpgrade := HasValidPrevDir;
    Exit;
  end;

  WizardForm.DirEdit.OnChange := @DirEditChange;
  UpdateDirSelectionState;

  if HasValidPrevDir then
  begin
    Response := MsgBox('Se detecto una instalacion existente en: ' + PrevDir + NL + 'Desea actualizar?', mbConfirmation, MB_YESNO or MB_DEFBUTTON1);
    if Response = IDYES then
    begin
      WizardForm.DirEdit.Text := PrevDir;
      WizardForm.DirEdit.Enabled := False;
      WizardForm.DirBrowseButton.Enabled := False;
      RequireDifferentDir := False;
      IsUpgrade := True;
      ShouldBackup := MsgBox(
        'Desea crear una copia de seguridad en el escritorio antes de actualizar?',
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2
      ) = IDYES;
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

procedure CurStepChanged(CurStep: TSetupStep);
var
  DesktopBase: string;
begin
  if (CurStep = ssInstall) and IsUpgrade and ShouldBackup and DirExists(PrevDir) then
  begin
    DesktopBase := ExpandConstant('{userdesktop}\Vertex DTE Backup');
    BackupTarget := MakeUniqueDir(DesktopBase);
    Log(Format('Creando copia de seguridad desde %s hacia %s', [PrevDir, BackupTarget]));
    if CopyDirRecursive(PrevDir, BackupTarget) then
      Log(Format('Copia de seguridad creada en: %s', [BackupTarget]))
    else
      MsgBox('No se pudo crear la copia de seguridad en: ' + BackupTarget, mbError, MB_OK);
  end;
end;
