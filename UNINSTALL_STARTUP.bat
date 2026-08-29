@echo off
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
echo Stopping and removing the AIO_Screen task...
schtasks /End /TN "AIO_Screen" >nul 2>&1
schtasks /Delete /TN "AIO_Screen" /F
taskkill /F /IM pythonw.exe /FI "WINDOWTITLE eq aio*" >nul 2>&1
echo.
echo Removed. The panel will fade out shortly.
echo (If a tray icon is still showing, right-click it and choose Quit.)
pause
