@echo off
cd /d "%~dp0"

net session >nul 2>&1
if errorlevel 1 (
    echo Reading CPU temperature and fan RPM needs administrator rights.
    echo Requesting elevation...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo Running as administrator.
echo.
taskkill /F /IM "PC_Monitor.exe" /T >nul 2>&1
python -m pip install --quiet pythonnet psutil
echo.
echo  CPU temperature -^> big readout,  fan RPM -^> small readout,  1 Hz.
echo  Ctrl+C to stop.
echo.
python -u demo_stats.py --admin-sensors --big cpu_temp --small cpu_fan --hz 1 %*
pause
