@echo off
cd /d "%~dp0"
echo.
echo  15 steps, self-paced. Read the SMALL number each time.
echo  (Quit the daemon from the tray first, or this will refuse to start.)
echo.
python -u calibrate_fan.py
pause
