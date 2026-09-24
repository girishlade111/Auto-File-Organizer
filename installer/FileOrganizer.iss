; Inno Setup script — Auto File Organizer
; Build order: PyInstaller (--onedir) -> this script -> Setup-FileOrganizer.exe
;
; Autostart uses a Startup-folder shortcut, NOT a registry Run key.
; Registry Run-key writes are the most heavily weighted AV/Defender heuristic
; for persistence malware; a shell:startup .lnk has the same auto-launch
; effect on login without tripping that signal.

#define MyAppName "Auto File Organizer"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "LadeStack"
#define MyAppExeName "FileOrganizer.exe"

[Setup]
AppId={{8A3F2C1D-4B5E-4F6A-9C7D-1E2F3A4B5C6D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Auto File Organizer
DisableProgramGroupPage=yes
OutputBaseFilename=Setup-FileOrganizer
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupicon"; Description: "Start automatically when Windows starts"; GroupDescription: "Auto-start:"; Flags: checkedonce

[Files]
; PyInstaller --onedir output goes here (keep the folder layout intact —
; --onedir trades a messier folder for near-instant cold-start, worth it
; for a background tray app).
; NOTE: relative Source paths resolve against this script's directory
; (installer\), not the repo root — hence the ..\ prefix. Run iscc from the
; repo root exactly as README documents: iscc installer\FileOrganizer.iss
Source: "..\dist\FileOrganizer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Auto File Organizer"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Auto File Organizer"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
; Startup-folder shortcut = autostart mechanism (passes --tray: straight to
; tray background mode, no window). No registry Run key.
Name: "{userstartup}\Auto File Organizer"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--tray"; Tasks: startupicon

[Run]
; Auto-launch immediately after install so the user never needs to open it manually.
Filename: "{app}\{#MyAppExeName}"; Parameters: "--tray"; Description: "Launch Auto File Organizer"; Flags: nowait postinstall skipifsilent
