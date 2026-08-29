@echo off
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
    echo Changing autostart entries needs administrator rights. Requesting elevation...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0disable_pc_monitor.ps1"
pause
