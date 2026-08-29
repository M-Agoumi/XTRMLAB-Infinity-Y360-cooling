@echo off
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
    echo Re-running elevated so the sensor checks are meaningful...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
python -u doctor.py
echo.
pause
