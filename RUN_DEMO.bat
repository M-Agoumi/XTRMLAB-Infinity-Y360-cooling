@echo off
cd /d "%~dp0"
taskkill /F /IM "PC_Monitor.exe" /T >nul 2>&1
echo Streaming live stats to the AIO panel. Close this window or press Ctrl+C to stop.
python -u demo_stats.py %*
pause
