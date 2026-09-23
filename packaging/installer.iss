; Inno Setup script for the Windows installer (per-user, no admin rights needed).
; Build: iscc /DAppVersion=0.3.0 packaging\installer.iss   (after running PyInstaller)

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8F6C2B1E-4E57-4B7A-9D3C-6A1F0E2B7C55}
AppName=Video Transcriber
AppVersion={#AppVersion}
AppPublisher=Lucas Coqueiro
AppPublisherURL=https://github.com/coqueiroz/video-transcriber
DefaultDirName={localappdata}\Programs\Video Transcriber
DefaultGroupName=Video Transcriber
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=VideoTranscriber-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\VideoTranscriber.exe
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\VideoTranscriber\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Video Transcriber"; Filename: "{app}\VideoTranscriber.exe"
Name: "{autodesktop}\Video Transcriber"; Filename: "{app}\VideoTranscriber.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\VideoTranscriber.exe"; Description: "{cm:LaunchProgram,Video Transcriber}"; Flags: nowait postinstall skipifsilent
