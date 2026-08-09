[Setup]
AppName=Acasmart
AppVersion=1.1.25
DefaultDirName={pf}\AcaSmart
DefaultGroupName=AcaSmart
OutputDir=dist
OutputBaseFilename=setup_Acasmart
Compression=lzma
SolidCompression=yes
LicenseFile=AcaSmart-repo\LICENSE
; Windows 7 compatibility
MinVersion=6.1
; Additional Windows 7 compatibility settings
PrivilegesRequired=admin
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "AcaSmart-repo\dist\AcaSmart\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs
Source: "Setup_files\VC_redist.x64.exe"; DestDir: "{tmp}"; Flags: ignoreversion
; Note: python3.dll and python38.dll are already included by PyInstaller, so we don't need to copy them separately

[Icons]
Name: "{group}\AcaSmart"; Filename: "{app}\AcaSmart.exe"
Name: "{commondesktop}\AcaSmart"; Filename: "{app}\AcaSmart.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts"
Name: "installvc"; Description: "Install Visual C++ Redistributable (Required for Windows 7)"; GroupDescription: "Components"

[Run]
Filename: "{tmp}\VC_redist.x64.exe"; Parameters: "/quiet /norestart"; StatusMsg: "Installing Visual C++ Redistributable..."; Flags: waituntilterminated; Tasks: installvc
Filename: "{app}\AcaSmart.exe"; Description: "Launch the application"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{localappdata}\AcaSmart\acasmart.db"
Type: files; Name: "{localappdata}\AcaSmart\.last_cleanup.txt"
Type: files; Name: "{localappdata}\AcaSmart\error.log"
Type: dirifempty; Name: "{localappdata}\AcaSmart"

[Code]
var
  LicenseKeyPage: TInputQueryWizardPage;

procedure InitializeWizard;
begin
  LicenseKeyPage := CreateInputQueryPage(wpWelcome,
    '🔑 Activation Required', 'Enter License Code',
    'To install this software, please enter a valid license code:');
  LicenseKeyPage.Add('License Code:', False);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  EnteredKey: String;
begin
  Result := True;
  if CurPageID = LicenseKeyPage.ID then
  begin
    EnteredKey := Trim(LicenseKeyPage.Values[0]);

    if not (
      (EnteredKey = 'AMG-9DL2-239D-2024') or
      (EnteredKey = 'AMG-Q3X8-748K-2024')
    ) then
    begin
      MsgBox('❌ Invalid license code. Please enter a valid key to continue.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;
