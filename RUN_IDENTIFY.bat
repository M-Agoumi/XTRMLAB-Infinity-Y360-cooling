@echo off
cd /d "%~dp0"
taskkill /F /IM "PC_Monitor.exe" /T >nul 2>&1
echo.
echo  Each readout will show its own ID number. Look at the panel (or photograph it).
echo.
python -u identify.py %*
pause
