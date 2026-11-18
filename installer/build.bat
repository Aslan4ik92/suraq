@echo off
rem IBTest build: tests, EXE, Setup.exe. Arguments are passed to build.ps1.
chcp 65001 >nul
cd /d "%~dp0\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1" %*
if errorlevel 1 (
  echo.
  echo BUILD FAILED. Log: %CD%\build\build.log
  pause
  exit /b 1
)
echo.
echo OK: %CD%\dist\installer
pause
