#define AppName "Effigy Exporter"
#define AppExe "EffigyExporter.exe"
#define Repository "https://github.com/Prednoxx/Effigy-Exporter"
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef StageDir
  #define StageDir "..\build\dist\EffigyExporter"
#endif

[Setup]
AppId={{BB6CC548-7C36-46DF-ABFD-B2A7C04F6D74}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Prednoxx
AppPublisherURL={#Repository}
AppSupportURL={#Repository}/issues
AppUpdatesURL={#Repository}/releases/latest
DefaultDirName={localappdata}\Programs\Effigy Exporter
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\souls_studio\resources\effigy.ico
UninstallDisplayIcon={app}\{#AppExe}
OutputBaseFilename=EffigyExporter-{#AppVersion}-Setup
WizardStyle=modern
Compression=lzma2/fast
SolidCompression=yes

[Files]
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch Effigy Exporter"; Flags: nowait postinstall skipifsilent
