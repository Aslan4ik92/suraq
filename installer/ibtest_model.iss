; Отдельный пакет локальной языковой модели для «ИБ ТЕСТ» (Inno Setup 6.3+)
; Сборка: ISCC.exe /DModelFile="D:\models\qwen2.5-7b-instruct-q4_k_m.gguf" /DModelName="Qwen2.5 7B Instruct Q4_K_M" installer\ibtest_model.iss
; Пакет копирует GGUF-файл в общую папку моделей; программа подключает модель автоматически при запуске.
; Для файлов больше 4 ГБ используется DiskSpanning (несколько файлов setup-*.bin рядом с установщиком).

#ifndef ModelFile
  #error Укажите /DModelFile=путь_к_модели.gguf
#endif
#ifndef ModelName
  #define ModelName "Local model"
#endif
#define DataDir "{commonappdata}\IBTest"

[Setup]
AppId={{9A47C3E1-2D6B-4F80-8E15-3B9C0F7D2A64}
AppName=ИБ ТЕСТ — языковая модель ({#ModelName})
AppVersion=1.0
DefaultDirName={#DataDir}\models
DisableDirPage=yes
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=IBTest_Model_Setup
Compression=none
DiskSpanning=yes
DiskSliceSize=max
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
PrivilegesRequired=admin
Uninstallable=yes
UninstallDisplayName=ИБ ТЕСТ — языковая модель ({#ModelName})
SetupIconFile=..\ibtest\assets\ibtest.ico

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Dirs]
Name: "{#DataDir}\models"; Permissions: users-modify; Flags: uninsneveruninstall

[Files]
Source: "{#ModelFile}"; DestDir: "{#DataDir}\models"; Flags: ignoreversion nocompression

[Code]
function InitializeSetup(): Boolean;
var
  Free, Total: Cardinal;
begin
  Result := True;
  if GetSpaceOnDisk(ExtractFileDrive(ExpandConstant('{commonappdata}')) + '\', True, Free, Total) and (Free < 12000) then
    Result := MsgBox('На системном диске меньше 12 ГБ свободного места. Продолжить установку модели?',
                     mbConfirmation, MB_YESNO) = IDYES;
end;
