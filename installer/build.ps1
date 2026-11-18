<#
  Сборка «ИБ ТЕСТ» для Windows 10/11 x64: тесты → PyInstaller → Setup.exe (Inno Setup).

  Требования на компьютере сборки (только на нём; пользователям ничего ставить не нужно):
    - Python 3.12 x64 (python.org), Inno Setup 6.3+ (jrsoftware.org), доступ в интернет для загрузки зависимостей.

  Запуск из корня проекта:
    powershell -ExecutionPolicy Bypass -File installer\build.ps1
    powershell -ExecutionPolicy Bypass -File installer\build.ps1 -Gpu cuda          # сборка llama.cpp с CUDA 12
    powershell -ExecutionPolicy Bypass -File installer\build.ps1 -ModelFile D:\m.gguf -ModelName "Qwen2.5 7B"
#>
param(
  [ValidateSet("cpu", "cuda")] [string]$Gpu = "cpu",
  [string]$Python = "py -3.12",
  [string]$TesseractUrl = "https://digi.bib.uni-mannheim.de/tesseract/tesseract-ocr-w64-setup-5.4.0.20240606.exe",
  [string]$TessdataUrl = "https://github.com/tesseract-ocr/tessdata_best/raw/main",
  [string]$VcRedistUrl = "https://aka.ms/vs/17/release/vc_redist.x64.exe",
  [string]$ModelFile = "",
  [string]$ModelName = "Local model",
  [switch]$SkipTests
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Build = Join-Path $Root "build"
New-Item -ItemType Directory -Force -Path $Build | Out-Null
Start-Transcript -Path (Join-Path $Build "build.log") -Force | Out-Null
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = "SilentlyContinue"   # иначе Invoke-WebRequest качает в десятки раз медленнее

function Step($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Fail($t) { Write-Host "ОШИБКА: $t" -ForegroundColor Red; Stop-Transcript | Out-Null; exit 1 }

Step "0. Проверка компьютера сборки"
if (-not [Environment]::Is64BitOperatingSystem) { Fail "Нужна 64-разрядная Windows." }
$isccProbe = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ }
if (-not $isccProbe) { Fail "Не найден Inno Setup 6. Установите: https://jrsoftware.org/isdl.php (по умолчанию, затем запустите сборку снова)." }
try { Invoke-Expression "$Python --version" | Out-Host } catch { $LASTEXITCODE = 1 }
if ($LASTEXITCODE -ne 0) { Fail "Не найден Python 3.12. Установите с https://www.python.org/downloads/ (галочка 'Add python.exe to PATH' и 'py launcher')." }

Step "1. Виртуальное окружение Python"
$venv = Join-Path $Build "venv"
if (-not (Test-Path "$venv\Scripts\python.exe")) {
  Invoke-Expression "$Python -m venv `"$venv`""
  if ($LASTEXITCODE -ne 0) { Fail "Не найден Python 3.12. Установите его с python.org." }
}
$py = "$venv\Scripts\python.exe"
& $py -m pip install --upgrade pip wheel | Out-Host
$index = if ($Gpu -eq "cuda") { "https://abetlen.github.io/llama-cpp-python/whl/cu124" } else { "https://abetlen.github.io/llama-cpp-python/whl/cpu" }
& $py -m pip install llama-cpp-python --prefer-binary --extra-index-url $index | Out-Host
if ($LASTEXITCODE -ne 0) { Fail "Не удалось установить llama-cpp-python." }
& $py -m pip install -r requirements-dev.txt --prefer-binary --extra-index-url $index | Out-Host
if ($LASTEXITCODE -ne 0) { Fail "Не удалось установить зависимости." }

$version = (& $py -c "import ibtest; print(ibtest.__version__)").Trim()
Write-Host "Версия: $version"

Step "2. Tesseract OCR (rus, kaz, eng)"
$tessDir = Join-Path $Build "tesseract"
if (-not (Test-Path "$tessDir\tesseract.exe")) {
  $tessSetup = Join-Path $Build "tesseract-setup.exe"
  Invoke-WebRequest -Uri $TesseractUrl -OutFile $tessSetup
  Start-Process -FilePath $tessSetup -ArgumentList "/S /D=$tessDir" -Wait -Verb RunAs
  if (-not (Test-Path "$tessDir\tesseract.exe")) { Fail "Tesseract не установлен в $tessDir" }
}
foreach ($l in "rus", "kaz", "eng") {
  $f = "$tessDir\tessdata\$l.traineddata"
  if (-not (Test-Path $f)) { Invoke-WebRequest -Uri "$TessdataUrl/$l.traineddata" -OutFile $f }
}

Step "3. Microsoft Visual C++ Runtime"
$vc = Join-Path $Build "vc_redist.x64.exe"
if (-not (Test-Path $vc)) { Invoke-WebRequest -Uri $VcRedistUrl -OutFile $vc }

if (-not $SkipTests) {
  Step "4. Автотесты"
  $env:PATH = "$tessDir;$env:PATH"
  $env:QT_QPA_PLATFORM = "offscreen"
  & $py -m pytest tests -q
  if ($LASTEXITCODE -ne 0) { Fail "Автотесты не пройдены — сборка остановлена." }
}

Step "5. PyInstaller"
$parts = $version.Split(".")
(Get-Content installer\version_info.template.txt -Raw -Encoding UTF8) `
  -replace "\{V1\}", $parts[0] -replace "\{V2\}", $parts[1] -replace "\{V3\}", $parts[2] -replace "\{VERSION\}", $version |
  ForEach-Object { [IO.File]::WriteAllText((Join-Path $Root "installer\version_info.txt"), $_, (New-Object Text.UTF8Encoding $false)) }
& $py -m PyInstaller installer\ibtest.spec --noconfirm --distpath dist --workpath "$Build\pyi"
if ($LASTEXITCODE -ne 0) { Fail "PyInstaller завершился с ошибкой." }

Step "6. Самопроверка собранной программы"
$report = Join-Path $Build "selftest.txt"
Copy-Item -Recurse -Force $tessDir "dist\IBTest\tesseract"
$p = Start-Process -FilePath "dist\IBTest\IBTest.exe" -ArgumentList "--selftest", "`"$report`"" -Wait -PassThru
Get-Content $report -Encoding UTF8 | Out-Host
Remove-Item -Recurse -Force "dist\IBTest\tesseract"
if ($p.ExitCode -ne 0) { Fail "Самопроверка не пройдена (см. выше)." }

Step "7. Inno Setup"
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { Fail "Не найден Inno Setup 6 (ISCC.exe)." }
& $iscc "/DAppVersion=$version" installer\ibtest.iss
if ($LASTEXITCODE -ne 0) { Fail "Ошибка сборки установщика." }
if ($ModelFile) {
  & $iscc "/DModelFile=$ModelFile" "/DModelName=$ModelName" installer\ibtest_model.iss
  if ($LASTEXITCODE -ne 0) { Fail "Ошибка сборки пакета модели." }
}
Write-Host "`nГотово: dist\installer\IBTest_Setup_$version.exe" -ForegroundColor Green
Stop-Transcript | Out-Null
