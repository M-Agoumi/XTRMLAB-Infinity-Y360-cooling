@echo off
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
    echo Some checks need administrator rights. Requesting elevation...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
pause
