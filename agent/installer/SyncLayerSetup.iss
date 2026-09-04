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

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install_finalize.ps1"" -AgentPath ""{app}\SyncLayerAgent.exe"" -AgentDir ""{app}"""; Flags: runhidden waituntilterminated
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install_verify.ps1"""; Flags: runhidden waituntilterminated

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command "". '{app}\install_common.ps1'; Remove-LegacySyncLayerInstall -AgentDir '{app}' -StopProcesses"""; Flags: runhidden waituntilterminated
