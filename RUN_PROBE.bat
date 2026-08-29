@echo off
cd /d "%~dp0"
taskkill /F /IM "PC_Monitor.exe" /T >nul 2>&1
echo.
echo  Each phase COUNTS UP once a second. Watch which readout ticks along.
echo  Phase 0 sends all zeros - anything still lit is the panel's own sensor.
echo.
python -u probe_display.py %*
pause
