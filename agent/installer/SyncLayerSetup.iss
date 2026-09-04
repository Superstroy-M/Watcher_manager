[Setup]
AppId={{F0C2E465-96FB-4BA8-991F-BD7339FC2F91}
AppName=SyncLayer
AppVersion=1.0
AppPublisher=SyncLayer
DefaultDirName={commonappdata}\SyncLayer
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
OutputDir=..\dist
OutputBaseFilename=SyncLayerSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\SyncLayerAgent.exe

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Files]
Source: "..\dist\SyncLayerAgent.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\install_common.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\install_finalize.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\install_verify.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\install_repair.bat"; DestDir: "{app}"; Flags: ignoreversion

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command "". '{app}\install_common.ps1'; Remove-LegacySyncLayerInstall -AgentDir '{app}' -StopProcesses"""; Flags: runhidden waituntilterminated

[Code]
function RunPowerShellScript(const ScriptPath, Params: String; out ResultCode: Integer): Boolean;
var
  Cmd: String;
begin
  Cmd := '-NoProfile -ExecutionPolicy Bypass -File "' + ScriptPath + '"' + Params;
  Result := Exec('powershell.exe', Cmd, '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  AppDir: String;
  ResultCode: Integer;
  FinalizePath: String;
  VerifyPath: String;
begin
  if CurStep <> ssPostInstall then
    Exit;

  AppDir := ExpandConstant('{app}');
  FinalizePath := AppDir + '\install_finalize.ps1';
  VerifyPath := AppDir + '\install_verify.ps1';

  if not RunPowerShellScript(
    FinalizePath,
    ' -AgentPath "' + AppDir + '\SyncLayerAgent.exe" -AgentDir "' + AppDir + '"',
    ResultCode) then
  begin
    MsgBox('SyncLayer install_finalize failed to start.', mbError, MB_OK);
    Abort;
  end;
  if ResultCode <> 0 then
  begin
    MsgBox(
      'SyncLayer install_finalize failed (exit ' + IntToStr(ResultCode) + ').' + #13#10 +
      'See ' + AppDir + '\install.log',
      mbError, MB_OK);
    Abort;
  end;

  if not RunPowerShellScript(VerifyPath, '', ResultCode) then
  begin
    MsgBox('SyncLayer install_verify failed to start.', mbError, MB_OK);
    Abort;
  end;
  if ResultCode <> 0 then
  begin
    MsgBox('SyncLayer install_verify failed (exit ' + IntToStr(ResultCode) + ').', mbError, MB_OK);
    Abort;
  end;
end;
