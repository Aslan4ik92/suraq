; Установщик «ИБ ТЕСТ» (Inno Setup 6.3+)
; Сборка: ISCC.exe /DAppVersion=1.0.0 installer\ibtest.iss  (выполняется из installer\build.ps1)

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "ИБ ТЕСТ"
#define AppExe "IBTest.exe"
#define DataDir "{commonappdata}\IBTest"

[Setup]
AppId={{6F1E2B4C-8A3D-4E57-9B21-7C0D5A9E3F11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=IBTest
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\IBTest
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=IBTest_Setup_{#AppVersion}
SetupIconFile=..\ibtest\assets\ibtest.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} {#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
PrivilegesRequired=admin
CloseApplications=yes
RestartApplications=no
; Обновление поверх установленной версии сохраняет все данные: они хранятся в ProgramData.
UsePreviousAppDir=yes

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
ru.DesktopIcon=Ярлык на рабочем столе
ru.KioskIcon=Ярлык «Режим тестирования сотрудников»
ru.ModelComponent=Локальная языковая модель (если файл .gguf лежит в папке models рядом с установщиком)
ru.AppComponent=Программа «ИБ ТЕСТ»
ru.KioskName=ИБ ТЕСТ — тестирование сотрудников
ru.DeleteData=Удалить также базу данных, документы, результаты тестирования и резервные копии?%n%nПапка: %1%n%nРекомендуется ответить «Нет».
ru.VCRedist=Установка Microsoft Visual C++ Runtime…
ru.NoData=Не удалось создать папку данных %1.
en.DesktopIcon=Desktop shortcut
en.KioskIcon=Shortcut "Employee testing mode"
en.ModelComponent=Local language model (if a .gguf file is in the models folder next to the installer)
en.AppComponent=IBTest application
en.KioskName=IBTest — employee testing
en.DeleteData=Also delete the database, documents, test results and backups?%n%nFolder: %1
en.VCRedist=Installing Microsoft Visual C++ Runtime…
en.NoData=Cannot create data folder %1.

[Types]
Name: "full"; Description: "Full"
Name: "custom"; Description: "Custom"; Flags: iscustom

[Components]
Name: "app"; Description: "{cm:AppComponent}"; Types: full custom; Flags: fixed
Name: "model"; Description: "{cm:ModelComponent}"; Types: full; Check: ModelNextToSetup

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "kioskicon"; Description: "{cm:KioskIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Dirs]
; Общая папка данных: доступна на запись всем пользователям компьютера (сотрудники проходят тест под своими учётными записями).
; Не удаляется при удалении/обновлении программы.
Name: "{#DataDir}"; Permissions: users-modify; Flags: uninsneveruninstall
Name: "{#DataDir}\models"; Permissions: users-modify; Flags: uninsneveruninstall
Name: "{#DataDir}\backups"; Permissions: users-modify; Flags: uninsneveruninstall

[Files]
Source: "..\dist\IBTest\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: app
Source: "..\build\tesseract\*"; DestDir: "{app}\tesseract"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist; Components: app
Source: "..\build\vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall skipifsourcedoesntexist; Components: app
; Модель не входит в Setup.exe (несколько ГБ): копируется из папки models рядом с установщиком.
Source: "{src}\models\*.gguf"; DestDir: "{#DataDir}\models"; Flags: external skipifsourcedoesntexist ignoreversion; Components: model

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:KioskName}"; Filename: "{app}\{#AppExe}"; Parameters: "--kiosk"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
Name: "{autodesktop}\{cm:KioskName}"; Filename: "{app}\{#AppExe}"; Parameters: "--kiosk"; Tasks: kioskicon

[Run]
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "{cm:VCRedist}"; Flags: waituntilterminated; Check: VCRedistNeeded
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
function ModelNextToSetup(): Boolean;
var
  FindRec: TFindRec;
begin
  Result := FindFirst(ExpandConstant('{src}\models\*.gguf'), FindRec);
  if Result then FindClose(FindRec);
end;

function VCRedistNeeded(): Boolean;
var
  Installed: Cardinal;
begin
  Result := True;
  if RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Installed', Installed) then
    Result := (Installed <> 1);
  if Result then
    Result := FileExists(ExpandConstant('{tmp}\vc_redist.x64.exe'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if not DirExists(ExpandConstant('{#DataDir}')) then
      MsgBox(FmtMessage(CustomMessage('NoData'), [ExpandConstant('{#DataDir}')]), mbError, MB_OK);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Dir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Dir := ExpandConstant('{#DataDir}');
    if DirExists(Dir) and not UninstallSilent() then
      if MsgBox(FmtMessage(CustomMessage('DeleteData'), [Dir]), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Dir, True, True, True);
  end;
end;
