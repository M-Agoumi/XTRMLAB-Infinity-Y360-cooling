@echo off
cd /d "%~dp0"
taskkill /F /IM "PC_Monitor.exe" /T >nul 2>&1
echo.
echo  12 steps, 6 seconds each. Note the BIG number for each row.
echo.
python -u calibrate_temp.py
pause
