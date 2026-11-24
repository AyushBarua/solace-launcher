; The release workflow passes the version: ISCC /DAppVersion=1.2.3 installer.iss
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppName=Solace
AppVersion={#AppVersion}
DefaultDirName={autopf}\Solace
DefaultGroupName=Solace
OutputDir=dist
OutputBaseFilename=Solace_Setup
LicenseFile=license.txt
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
DisableWelcomePage=no

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\Solace\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Solace"; Filename: "{app}\Solace.exe"
Name: "{autodesktop}\Solace"; Filename: "{app}\Solace.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Solace.exe"; Description: "Launch Solace now"; Flags: nowait postinstall skipifsilent
; An in-app update runs this installer silently; open Solace again when it is done.
Filename: "{app}\Solace.exe"; Flags: nowait runasoriginaluser; Check: WizardSilent

[Code]
var
  DownloadPage: TDownloadWizardPage;
  GamesDirPage: TInputDirWizardPage;

function IsVCRedistInstalled(): Boolean;
var
  Major: Cardinal;
begin
  // Check if VC++ 2015-2022 redist is installed
  Result := RegQueryDWordValue(HKLM, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Major', Major);
end;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  if Progress = ProgressMax then
    Log(Format('Successfully downloaded %s to %s', [Url, FileName]));
  Result := True;
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing), SetupMessage(msgPreparingDesc), @OnDownloadProgress);
  
  GamesDirPage := CreateInputDirPage(wpSelectDir,
    'Select Games Library Location', 'Where should Solace store downloaded games?',
    'Select the folder where downloaded games will be installed and stored, then click Next.',
    False, '');
  GamesDirPage.Add('');
  GamesDirPage.Values[0] := ExpandConstant('{autodocs}\Solace Games');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;

  if (CurPageID = wpReady) and not IsVCRedistInstalled() then begin
    DownloadPage.Clear;
    DownloadPage.Add('https://aka.ms/vs/17/release/vc_redist.x64.exe', 'vc_redist.x64.exe', '');
    DownloadPage.Show;
    try
      try
        DownloadPage.Download;
      except
        if DownloadPage.AbortedByUser then
          Log('Aborted by user.')
        else
          SuppressibleMsgBox(AddPeriod(GetExceptionMessage), mbCriticalError, MB_OK, IDOK);
        Result := False;
      end;
    finally
      DownloadPage.Hide;
    end;
  end;
end;

procedure WriteSettingsJSON(DataDir, GamesDir: String);
var
  JSONStr: String;
begin
  StringChangeEx(DataDir, '\', '\\', True);
  StringChangeEx(GamesDir, '\', '\\', True);
  JSONStr := '{' + #13#10 +
             '  "difficulty_multiplier": 1.0,' + #13#10 +
             '  "games_dir": "' + GamesDir + '",' + #13#10 +
             '  "data_dir": "' + DataDir + '"' + #13#10 +
             '}';
  ForceDirectories(ExpandConstant('{localappdata}\Solace'));
  SaveStringToFile(ExpandConstant('{localappdata}\Solace\global_settings.json'), JSONStr, False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then begin
    // Only on a first install. An update must keep the user's settings.
    if not FileExists(ExpandConstant('{localappdata}\Solace\global_settings.json')) then
      WriteSettingsJSON(ExpandConstant('{localappdata}\Solace'), GamesDirPage.Values[0]);

    if not IsVCRedistInstalled() then begin
      if FileExists(ExpandConstant('{tmp}\vc_redist.x64.exe')) then begin
        Exec(ExpandConstant('{tmp}\vc_redist.x64.exe'), '/install /quiet /norestart', '', SW_SHOW, ewWaitUntilTerminated, ResultCode);
      end;
    end;
  end;
end;
