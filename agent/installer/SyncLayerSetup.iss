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
Source: "..\dist\SyncLayerService.exe"; DestDir: "{app}"; Flags: ignoreversion

[Registry]
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "SyncLayerAgent"; ValueData: """{app}\SyncLayerAgent.exe"""; Flags: uninsdeletevalue

[Run]
Filename: "{cmd}"; Parameters: "/C sc stop SyncLayer"; Flags: runhidden waituntilterminated
Filename: "{cmd}"; Parameters: "/C sc delete SyncLayer"; Flags: runhidden waituntilterminated
Filename: "{app}\SyncLayerService.exe"; Parameters: "install"; Flags: runhidden waituntilterminated
Filename: "{cmd}"; Parameters: "/C sc config SyncLayer start= auto"; Flags: runhidden waituntilterminated
Filename: "{app}\SyncLayerService.exe"; Parameters: "start"; Flags: runhidden waituntilterminated
Filename: "{app}\SyncLayerAgent.exe"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C schtasks /Delete /TN SyncLayerAgent /F"; Flags: runhidden waituntilterminated
Filename: "{app}\SyncLayerService.exe"; Parameters: "stop"; Flags: runhidden waituntilterminated
Filename: "{app}\SyncLayerService.exe"; Parameters: "remove"; Flags: runhidden waituntilterminated
Filename: "{cmd}"; Parameters: "/C sc delete SyncLayer"; Flags: runhidden waituntilterminated
