@echo off
cd /d "%~dp0"
echo.
echo  10 readings across the whole range, self-paced.
echo  (Quit the daemon from the tray first, or this will refuse to start.)
echo.
python -u fan_map.py
pause
