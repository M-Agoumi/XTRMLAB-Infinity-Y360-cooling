@echo off
cd /d "%~dp0"
echo.
echo  Making the fan slot display exactly 8008.
echo  Read the SMALL number each time, type it, press Enter.
echo  (Quit the daemon from the tray first, or this will refuse to start.)
echo.
python -u fan_tune.py %*
pause
