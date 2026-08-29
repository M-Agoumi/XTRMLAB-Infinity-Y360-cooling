@echo off
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
    echo Listing sensors needs administrator rights. Requesting elevation...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
python -m pip install --quiet pythonnet
set LOG=%~dp0sensors.txt
python -u sensors.py > "%LOG%" 2>&1
type "%LOG%"
echo.
echo Saved to sensors.txt
pause
