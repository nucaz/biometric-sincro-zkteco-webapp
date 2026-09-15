; Inno Setup script for the ZKTeco Attendance System desktop GUI.
; Build with (from the project root, after running PyInstaller first):
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" deploy\windows_desktop\installer.iss
; Produces dist_installer\ZKTecoAttendanceSystem_Setup_<version>.exe

#define MyAppName "ZKTeco Attendance System"
#define MyAppVersion GetVersionNumbersString("..\..\dist\ZKTecoAttendanceSystem.exe")
#define MyAppPublisher "Juan Carlos Aguirre Alvarado - Infraestructura TI & Ciberseguridad Apps"
#define MyAppExeName "ZKTecoAttendanceSystem.exe"

[Setup]
AppId={{B7B6B1F1-6C7C-4B9E-9F0A-3F9E0E2E9A11}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist_installer
OutputBaseFilename=ZKTecoAttendanceSystem_Setup_{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; A real uninstaller entry in "Agregar o quitar programas", and no source
; code/venv on the target machine -- just the compiled exe this installer ships.
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; Ships an EMPTY device list, never the developer's own local devices.json
; (that file holds real site IPs/serials and must never end up in a build).
; onlyifdoesntexist: never overwrite the user's saved device list on an upgrade.
; uninsneveruninstall: keep it if they ever uninstall -- it's their data, not app code.
Source: "devices.default.json"; DestDir: "{app}"; DestName: "devices.json"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "..\..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
