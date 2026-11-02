; JARVIS per-user Windows installer.
; Compile with Inno Setup 6.4 or newer from the staged build directory:
;   iscc JarvisSetup.iss
; The staged directory must contain payload\, scripts\, and prereqs.json.

#define AppName "JARVIS"
#define AppVersion "0.1.0"
#define AppPublisher "Sean Shaffer"
#define AppId "{{8F8D8C44-9B6F-4A3E-9E73-6A5D9D3C5F71}"
#define AppUserModelID "SeanShaffer.Jarvis.Windows"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppCopyright=Copyright (c) 2026 Sean Shaffer
DefaultDirName={localappdata}\Programs\Jarvis
DefaultGroupName=JARVIS
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyMemo=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
AllowNoIcons=yes
MinVersion=10.0.17763
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=JarvisSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
UninstallDisplayName=JARVIS (per-user)
UninstallFilesDir={app}\.uninstall
CloseApplications=no
UsedUserAreasWarnings=no
VersionInfoVersion=0.1.0.0
VersionInfoCompany={#AppPublisher}
VersionInfoDescription=JARVIS Windows installer and compatibility overlay

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Dirs]
Name: "{app}\data"; Flags: uninsneveruninstall
Name: "{app}\logs"; Flags: uninsneveruninstall
Name: "{app}\private"; Flags: uninsneveruninstall
Name: "{app}\installer\scripts"

[Files]
; The generated private payload: upstream JARVIS, pre-built frontend/dist,
; Windows overlay, Windows requirements, notices, and optional openssl.exe.
Source: "payload\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

; Helpers are installed for runtime use...
Source: "scripts\*.ps1"; DestDir: "{app}\installer\scripts"; Flags: ignoreversion
Source: "scripts\prereqs.json"; DestDir: "{app}\installer"; Flags: ignoreversion

; ...and extracted to {tmp} for wizard pages that run before file installation.
Source: "scripts\Check-System.ps1"; DestDir: "{tmp}"; Flags: dontcopy
Source: "scripts\InstallPrereqs.ps1"; DestDir: "{tmp}"; Flags: dontcopy
Source: "scripts\SetSecretAcl.ps1"; DestDir: "{tmp}"; Flags: dontcopy
Source: "scripts\Stop-Jarvis.ps1"; DestDir: "{tmp}"; Flags: dontcopy
Source: "scripts\OpenClaudeLogin.ps1"; DestDir: "{tmp}"; Flags: dontcopy
Source: "scripts\Set-Startup.ps1"; DestDir: "{tmp}"; Flags: dontcopy
Source: "scripts\prereqs.json"; DestDir: "{tmp}"; Flags: dontcopy

[Icons]
; A non-packaged app needs an AppUserModelID on a Start-menu shortcut for toasts.
Name: "{group}\JARVIS"; Filename: "{app}\.venv\Scripts\pythonw.exe"; \
  Parameters: """{app}\jarvis_win\launcher.py"" --app-root ""{app}"" start"; \
  WorkingDir: "{app}"; IconFilename: "{app}\.venv\Scripts\pythonw.exe"; \
  AppUserModelID: "{#AppUserModelID}"; Comment: "Start JARVIS and open the voice page"
Name: "{group}\JARVIS Dashboard"; Filename: "{app}\.venv\Scripts\pythonw.exe"; \
  Parameters: """{app}\jarvis_win\launcher.py"" --app-root ""{app}"" start --open dashboard"; \
  WorkingDir: "{app}"; IconFilename: "{app}\.venv\Scripts\pythonw.exe"; \
  AppUserModelID: "{#AppUserModelID}"; Comment: "Open the JARVIS dashboard"
Name: "{group}\Stop JARVIS"; Filename: "{app}\.venv\Scripts\pythonw.exe"; \
  Parameters: """{app}\jarvis_win\launcher.py"" --app-root ""{app}"" stop"; \
  WorkingDir: "{app}"; IconFilename: "{app}\.venv\Scripts\pythonw.exe"; \
  AppUserModelID: "{#AppUserModelID}"; Comment: "Stop the hidden JARVIS server"

[UninstallRun]
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ""{app}\installer\scripts\Stop-Jarvis.ps1"" -AppRoot ""{app}"""; \
  Flags: runhidden; RunOnceId: "JarvisStopServer"
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ""{app}\installer\scripts\Set-Startup.ps1"" -Disable"; \
  Flags: runhidden; RunOnceId: "JarvisRemoveStartup"

[UninstallDelete]
; Only transient setup markers. .env, data\, certs, memory, logs, and the venv
; are deliberately left in place so an uninstall/reinstall resumes cleanly.
Type: files; Name: "{app}\logs\setup.cancel"
Type: files; Name: "{app}\logs\setup.exitcode"
Type: files; Name: "{app}\logs\setup.progress"
Type: dirifempty; Name: "{app}\private"

[Code]
const
  SetupTimeoutTicks = 7200;  // 30 minutes at 250 ms per tick

var
  ChecksPage: TWizardPage;
  ChecksMemo: TNewMemo;
  PrereqPage: TWizardPage;
  PrereqMemo: TNewMemo;
  KeysPage: TInputQueryWizardPage;
  LoginPage: TWizardPage;
  LoginMemo: TNewMemo;
  FinishOptionsPage: TWizardPage;
  StartNowBox: TNewCheckBox;
  StartWithWindowsBox: TNewCheckBox;
  ChecksOK, ChecksRan, PrereqsDone: Boolean;
  SetupRunning, SetupCancelled: Boolean;
  PythonPath, ClaudePath, JobPath: String;
  ChecksOutputPath, PrereqOutputPath: String;
  SetupExitFile, SetupProgressFile, SetupCancelFile: String;

function Quote(const S: String): String;
begin
  Result := '"' + S + '"';
end;

procedure LogSetup(const Msg: String);
var
  LogPath: String;
begin
  LogPath := ExpandConstant('{app}\logs\install.log');
  ForceDirectories(ExtractFileDir(LogPath));
  SaveStringToFile(LogPath, Msg + #13#10, True);
  Log(Msg);
end;

function ReadValue(const FileName, Key: String): String;
var
  Lines: TStringList;
  I, P: Integer;
  Line: String;
begin
  Result := '';
  if FileExists(FileName) then
  begin
    Lines := TStringList.Create;
    try
      Lines.LoadFromFile(FileName);
      for I := 0 to Lines.Count - 1 do
      begin
        Line := Lines[I];
        P := Pos('=', Line);
        if (P > 0) and (CompareText(Trim(Copy(Line, 1, P - 1)), Key) = 0) then
        begin
          Result := Trim(Copy(Line, P + 1, Length(Line)));
          Break;
        end;
      end;
    finally
      Lines.Free;
    end;
  end;
end;

function RunPowerShell(const Script, Params: String; var ExitCode: Integer): Boolean;
var
  Command: String;
begin
  LogSetup('Running helper ' + ExtractFileName(Script));
  Command := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ' + Quote(Script);
  if Params <> '' then
    Command := Command + ' ' + Params;
  Result := Exec('powershell.exe', Command, ExpandConstant('{tmp}'),
                 SW_HIDE, ewWaitUntilTerminated, ExitCode);
end;

function HasExistingFishKey: Boolean;
var
  EnvPath: String;
  Lines: TStringList;
  I, P: Integer;
  Line, Key, Value: String;
begin
  Result := False;
  EnvPath := ExpandConstant('{app}\.env');
  if FileExists(EnvPath) then
  begin
    Lines := TStringList.Create;
    try
      Lines.LoadFromFile(EnvPath);
      for I := 0 to Lines.Count - 1 do
      begin
        Line := Trim(Lines[I]);
        if (Line = '') or (Copy(Line, 1, 1) = '#') then
          continue;
        P := Pos('=', Line);
        if P > 0 then
        begin
          Key := Trim(Copy(Line, 1, P - 1));
          Value := Trim(Copy(Line, P + 1, Length(Line)));
          if (CompareText(Key, 'FISH_API_KEY') = 0) and (Value <> '') and
             (Pos('your-fish-audio-api-key-here', Value) = 0) then
            Result := True;
        end;
      end;
    finally
      Lines.Free;
    end;
  end;
end;

function JsonEscape(const S: String): String;
begin
  Result := S;
  StringChangeEx(Result, '\', '\\', True);
  StringChangeEx(Result, '"', '\"', True);
  StringChangeEx(Result, #13, '\r', True);
  StringChangeEx(Result, #10, '\n', True);
  StringChangeEx(Result, #9, '\t', True);
end;

function BuildJobJson: String;
begin
  // The key is written to a user-only temp file; it is NEVER logged or passed
  // on a command line. setup_runtime.py overwrites and deletes that file.
  Result := '{' +
    '"fish_api_key": "' + JsonEscape(Trim(KeysPage.Values[0])) + '", ' +
    '"user_name": "' + JsonEscape(Trim(KeysPage.Values[1])) + '", ' +
    '"brain_model": "' + JsonEscape(Trim(KeysPage.Values[2])) + '", ' +
    '"voice_id": "' + JsonEscape(Trim(KeysPage.Values[3])) + '"' +
    '}';
end;

function WriteJobFile: Boolean;
var
  Script, Params: String;
  ExitCode: Integer;
begin
  Result := False;
  JobPath := ExpandConstant('{tmp}\jarvis-setup-input.json');
  Script := ExpandConstant('{tmp}\SetSecretAcl.ps1');
  Params := '-Path ' + Quote(JobPath);
  if not RunPowerShell(Script, Params, ExitCode) or (ExitCode <> 0) then
  begin
    MsgBox('JARVIS could not protect the temporary settings file. Setup will stop.',
           mbError, MB_OK);
    LogSetup('Secret ACL helper failed');
    Exit;
  end;
  if not SaveStringToFile(JobPath, BuildJobJson, False) then
  begin
    MsgBox('JARVIS could not write the temporary settings file. Setup will stop.',
           mbError, MB_OK);
    LogSetup('Secret job write failed');
    Exit;
  end;
  LogSetup('Temporary settings file prepared; contents are not logged');
  Result := True;
end;

procedure RunSystemChecks;
var
  Script, Params, Status, Message, DiskGB: String;
  ExitCode: Integer;
begin
  ChecksOutputPath := ExpandConstant('{tmp}\jarvis-checks.txt');
  Script := ExpandConstant('{tmp}\Check-System.ps1');
  Params := '-OutputPath ' + Quote(ChecksOutputPath);
  ChecksOK := False;
  ChecksRan := True;
  if not RunPowerShell(Script, Params, ExitCode) or (ExitCode <> 0) then
  begin
    Message := 'The PC check did not finish. Chrome, Windows 10 1809 or newer, and about 1 GB of free space are required.';
    ChecksMemo.Text := Message;
    LogSetup('System check helper failed');
    Exit;
  end;
  Status := ReadValue(ChecksOutputPath, 'Status');
  Message := ReadValue(ChecksOutputPath, 'Message');
  DiskGB := ReadValue(ChecksOutputPath, 'DiskGB');
  ChecksOK := CompareText(Status, 'OK') = 0;
  ChecksMemo.Text := Message + #13#10 + 'Free space: ' + DiskGB + ' GB.';
  LogSetup('System checks: ' + Status);
end;

function RunPrereqs: Boolean;
var
  Script, Params, Status, Message: String;
  ExitCode: Integer;
begin
  if PrereqsDone then
  begin
    Result := True;
    Exit;
  end;
  PrereqOutputPath := ExpandConstant('{tmp}\jarvis-prereqs.txt');
  Script := ExpandConstant('{tmp}\InstallPrereqs.ps1');
  Params := '-OutputPath ' + Quote(PrereqOutputPath) +
            ' -ManifestPath ' + Quote(ExpandConstant('{tmp}\prereqs.json')) +
            ' -Strategy winget-user';
  Result := False;
  if not RunPowerShell(Script, Params, ExitCode) then
  begin
    MsgBox('JARVIS could not start the prerequisite installer.', mbError, MB_OK);
    LogSetup('Prerequisite helper did not start');
    Exit;
  end;
  Status := ReadValue(PrereqOutputPath, 'Status');
  Message := ReadValue(PrereqOutputPath, 'Message');
  PythonPath := ReadValue(PrereqOutputPath, 'Python');
  ClaudePath := ReadValue(PrereqOutputPath, 'Claude');
  if (CompareText(Status, 'OK') <> 0) or (PythonPath = '') or (ClaudePath = '') then
  begin
    MsgBox('Prerequisites are not ready:' + #13#10 + Message, mbError, MB_OK);
    LogSetup('Prerequisites failed: ' + Message);
    Exit;
  end;
  PrereqMemo.Text := Message;
  PrereqsDone := True;
  LogSetup('Prerequisites ready');
  Result := True;
end;

procedure RefreshPreflight(Sender: TObject);
var
  Python, Launcher, Params, Text, App: String;
  ExitCode: Integer;
begin
  App := ExpandConstant('{app}');
  Python := App + '\.venv\Scripts\python.exe';
  Launcher := App + '\jarvis_win\launcher.py';
  Params := Quote(Launcher) + ' --app-root ' + Quote(App) + ' preflight';
  if not Exec(Python, Params, App, SW_HIDE, ewWaitUntilTerminated, ExitCode) then
    Text := 'Preflight could not run. The install log has more detail.'
  else if LoadStringFromFile(App + '\logs\preflight.txt', Text) then
    Text := Text
  else
    Text := 'Preflight finished, but its plain-words report was not found.';
  LoginMemo.Text := Text;
end;

procedure OpenClaudeLogin(Sender: TObject);
var
  Script, Params: String;
  ExitCode: Integer;
begin
  Script := ExpandConstant('{app}\installer\scripts\OpenClaudeLogin.ps1');
  Params := '-ClaudePath ' + Quote(ClaudePath);
  if not RunPowerShell(Script, Params, ExitCode) or (ExitCode <> 0) then
    MsgBox('JARVIS could not open the Claude login window. Open a terminal and run claude yourself.',
           mbError, MB_OK);
end;

procedure StopRunningJarvis;
var
  Script, Params: String;
  ExitCode: Integer;
begin
  Script := ExpandConstant('{tmp}\Stop-Jarvis.ps1');
  Params := '-AppRoot ' + Quote(ExpandConstant('{app}'));
  RunPowerShell(Script, Params, ExitCode);
end;

procedure RunSetup;
var
  ProgressPage: TOutputProgressWizardPage;
  Python, Script, Params, App, LogFile, Line, Message, ExitText: String;
  Dummy, ExitCode, I, Percent, P: Integer;
begin
  App := ExpandConstant('{app}');
  Python := PythonPath;
  Script := App + '\jarvis_win\setup_runtime.py';
  LogFile := App + '\logs\setup.log';
  SetupExitFile := App + '\logs\setup.exitcode';
  SetupProgressFile := ExpandConstant('{tmp}\jarvis-setup.progress');
  SetupCancelFile := ExpandConstant('{tmp}\jarvis-setup.cancel');
  ForceDirectories(App + '\logs');
  DeleteFile(SetupExitFile);
  DeleteFile(SetupProgressFile);
  DeleteFile(SetupCancelFile);
  SaveStringToFile(SetupProgressFile, '2|Preparing the private setup' + #13#10, False);

  Params := Quote(Script) +
            ' --app-root ' + Quote(App) +
            ' --job-file ' + Quote(JobPath) +
            ' --python ' + Quote(Python) +
            ' --progress-file ' + Quote(SetupProgressFile) +
            ' --cancel-file ' + Quote(SetupCancelFile) +
            ' --exit-file ' + Quote(SetupExitFile) +
            ' --log-file ' + Quote(LogFile);
  LogSetup('Starting cancellable runtime setup');
  if not Exec(Python, Params, App, SW_HIDE, ewNoWait, Dummy) then
  begin
    MsgBox('JARVIS could not start its runtime setup.', mbError, MB_OK);
    DeleteFile(JobPath);
    Abort;
  end;

  SetupRunning := True;
  SetupCancelled := False;
  Percent := 2;
  Message := 'Preparing the private setup';
  ProgressPage := CreateOutputProgressPage('Setting up JARVIS',
    'Creating the environment, installing Chromium, and checking the result.');
  ProgressPage.SetProgress(0, 100);
  ProgressPage.SetText(Message, 'Press Cancel to stop safely.');
  ProgressPage.Show;
  try
    for I := 0 to SetupTimeoutTicks do
    begin
      if SetupCancelled or FileExists(SetupExitFile) then
        Break;
      if FileExists(SetupProgressFile) and LoadStringFromFile(SetupProgressFile, Line) then
      begin
        P := Pos('|', Line);
        if P > 0 then
        begin
          Percent := StrToIntDef(Trim(Copy(Line, 1, P - 1)), Percent);
          Message := Trim(Copy(Line, P + 1, Length(Line)));
        end;
      end;
      ProgressPage.SetProgress(Percent, 100);
      ProgressPage.SetText(Message, 'Press Cancel to stop safely.');
      Sleep(250);
    end;
  finally
    SetupRunning := False;
    ProgressPage.Hide;
    ProgressPage.Free;
  end;

  if SetupCancelled then
  begin
    DeleteFile(JobPath);
    DeleteFile(SetupCancelFile);
    DeleteFile(SetupProgressFile);
    Abort;
  end;
  ExitText := '';
  if not FileExists(SetupExitFile) then
  begin
    DeleteFile(JobPath);
    MsgBox('Runtime setup timed out. See logs\setup.log for the redacted details.',
           mbError, MB_OK);
    Abort;
  end;
  LoadStringFromFile(SetupExitFile, ExitText);
  ExitCode := StrToIntDef(Trim(ExitText), -1);
  if ExitCode <> 0 then
  begin
    DeleteFile(JobPath);
    MsgBox('Runtime setup failed. See logs\setup.log for the redacted details.',
           mbError, MB_OK);
    Abort;
  end;
  LogSetup('Runtime setup completed');
end;

procedure ApplyFinishOptions;
var
  Script, Params, Pythonw, Launcher, App: String;
  ExitCode, Dummy: Integer;
begin
  App := ExpandConstant('{app}');
  Script := App + '\installer\scripts\Set-Startup.ps1';
  Pythonw := App + '\.venv\Scripts\pythonw.exe';
  Launcher := App + '\jarvis_win\launcher.py';
  if StartWithWindowsBox.Checked then
    Params := '-Enable -AppRoot ' + Quote(App) + ' -Pythonw ' + Quote(Pythonw)
  else
    Params := '-Disable';
  if not RunPowerShell(Script, Params, ExitCode) or (ExitCode <> 0) then
    MsgBox('The Start-with-Windows setting could not be changed.', mbInformation, MB_OK);
  if StartNowBox.Checked then
    Exec(Pythonw, Quote(Launcher) + ' --app-root ' + Quote(App) + ' start',
         App, SW_HIDE, ewNoWait, Dummy);
end;

procedure InitializeWizard;
var
  LoginButton, CheckAgainButton: TButton;
begin
  ChecksOK := False;
  ChecksRan := False;
  PrereqsDone := False;
  SetupRunning := False;
  SetupCancelled := False;
  PythonPath := '';
  ClaudePath := '';
  JobPath := '';

  ExtractTemporaryFile('Check-System.ps1');
  ExtractTemporaryFile('InstallPrereqs.ps1');
  ExtractTemporaryFile('SetSecretAcl.ps1');
  ExtractTemporaryFile('Stop-Jarvis.ps1');
  ExtractTemporaryFile('OpenClaudeLogin.ps1');
  ExtractTemporaryFile('Set-Startup.ps1');
  ExtractTemporaryFile('prereqs.json');

  ChecksPage := CreateCustomPage(wpWelcome, 'Checking your PC',
    'Chrome, a supported Windows version, and enough disk space.');
  ChecksMemo := TNewMemo.Create(ChecksPage);
  ChecksMemo.Parent := ChecksPage.Surface;
  ChecksMemo.SetBounds(0, 0, ChecksPage.Surface.Width, ChecksPage.Surface.Height);
  ChecksMemo.ReadOnly := True;
  ChecksMemo.ScrollBars := ssVertical;
  ChecksMemo.Text := 'Checking your PC...';

  PrereqPage := CreateCustomPage(ChecksPage.ID, 'Prerequisites',
    'Only missing pieces are installed, in your user profile.');
  PrereqMemo := TNewMemo.Create(PrereqPage);
  PrereqMemo.Parent := PrereqPage.Surface;
  PrereqMemo.SetBounds(0, 0, PrereqPage.Surface.Width, PrereqPage.Surface.Height);
  PrereqMemo.ReadOnly := True;
  PrereqMemo.ScrollBars := ssVertical;
  PrereqMemo.Text :=
    'JARVIS will check for and, only if missing, install:' + #13#10 + #13#10 +
    '- Python 3.11 or newer (official package, per-user)' + #13#10 +
    '- Git for Windows (projects JARVIS builds need it; it also supplies OpenSSL)' + #13#10 +
    '- Native Claude Code 2.1.224 or newer' + #13#10 + #13#10 +
    'Node.js and the npm claude.cmd shim are never installed. No administrator rights are needed.';

  KeysPage := CreateInputQueryPage(PrereqPage.ID, 'Voice settings',
    'One required key and three optional settings.',
    'The Fish Audio key is written to a user-only .env file and never appears in the install log.');
  KeysPage.Add('Fish Audio API key (required on a first install)', True);
  KeysPage.Add('Your name (optional, e.g. Sean)', False);
  KeysPage.Add('Brain model (optional, default sonnet)', False);
  KeysPage.Add('Fish voice ID (optional, default JARVIS)', False);

  LoginPage := CreateCustomPage(wpInstalling, 'Claude Code sign-in',
    'JARVIS cannot sign in for you; this is the one manual step.');
  LoginMemo := TNewMemo.Create(LoginPage);
  LoginMemo.Parent := LoginPage.Surface;
  LoginMemo.SetBounds(0, 44, LoginPage.Surface.Width, LoginPage.Surface.Height - 44);
  LoginMemo.ReadOnly := True;
  LoginMemo.ScrollBars := ssVertical;
  LoginButton := TButton.Create(LoginPage);
  LoginButton.Parent := LoginPage.Surface;
  LoginButton.Left := 0;
  LoginButton.Top := 8;
  LoginButton.Width := 200;
  LoginButton.Height := 28;
  LoginButton.Caption := 'Open Claude Code to sign in';
  LoginButton.OnClick := @OpenClaudeLogin;
  CheckAgainButton := TButton.Create(LoginPage);
  CheckAgainButton.Parent := LoginPage.Surface;
  CheckAgainButton.Left := 208;
  CheckAgainButton.Top := 8;
  CheckAgainButton.Width := 120;
  CheckAgainButton.Height := 28;
  CheckAgainButton.Caption := 'Check again';
  CheckAgainButton.OnClick := @RefreshPreflight;

  FinishOptionsPage := CreateCustomPage(LoginPage.ID, 'Finish',
    'Start now, or add JARVIS to your Windows sign-in.');
  StartNowBox := TNewCheckBox.Create(FinishOptionsPage);
  StartNowBox.Parent := FinishOptionsPage.Surface;
  StartNowBox.Left := 0;
  StartNowBox.Top := 16;
  StartNowBox.Width := FinishOptionsPage.Surface.Width;
  StartNowBox.Caption := 'Start JARVIS now (opens the voice page in Chrome)';
  StartNowBox.Checked := True;
  StartWithWindowsBox := TNewCheckBox.Create(FinishOptionsPage);
  StartWithWindowsBox.Parent := FinishOptionsPage.Surface;
  StartWithWindowsBox.Left := 0;
  StartWithWindowsBox.Top := 48;
  StartWithWindowsBox.Width := FinishOptionsPage.Surface.Width;
  StartWithWindowsBox.Caption := 'Start JARVIS when I sign in to Windows';
  StartWithWindowsBox.Checked := FileExists(ExpandConstant('{userstartup}\JARVIS.lnk'));

  RunSystemChecks;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = LoginPage.ID then
    RefreshPreflight(nil);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = ChecksPage.ID then
  begin
    if not ChecksOK then
    begin
      MsgBox('JARVIS cannot install until every PC check passes. Chrome is required for voice input.',
             mbError, MB_OK);
      Result := False;
    end;
  end
  else if CurPageID = PrereqPage.ID then
    Result := RunPrereqs
  else if CurPageID = KeysPage.ID then
  begin
    if (Trim(KeysPage.Values[0]) = '') and not HasExistingFishKey then
    begin
      MsgBox('A Fish Audio API key is required. There is no voice without it.',
             mbError, MB_OK);
      Result := False;
    end
    else
      Result := WriteJobFile;
  end
  else if CurPageID = LoginPage.ID then
  begin
    MsgBox('If preflight still says Claude Code needs sign-in, finish the install, sign in, then use Check again later from a terminal.',
           mbInformation, MB_OK);
  end
  else if CurPageID = FinishOptionsPage.ID then
    ApplyFinishOptions;
end;

function BackButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = LoginPage.ID) or (CurPageID = FinishOptionsPage.ID) then
    Result := False;  // never step back across file installation
end;

procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  if SetupRunning then
  begin
    SetupCancelled := True;
    SaveStringToFile(SetupCancelFile, 'cancel', False);
    DeleteFile(JobPath);
    Cancel := True;
    Confirm := False;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    StopRunningJarvis
  else if CurStep = ssPostInstall then
    RunSetup
  else if CurStep = ssDone then
  begin
    DeleteFile(JobPath);
    DeleteFile(SetupCancelFile);
    DeleteFile(SetupProgressFile);
    LogSetup('Installer finished; user data was preserved');
  end;
end;
