@echo off
setlocal
cd /d "%~dp0"

net session >nul 2>&1
if errorlevel 1 (
    echo Creating a scheduled task needs administrator rights. Requesting elevation...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ============================================================
echo  Installing the AIO screen daemon to start at logon
echo ============================================================
echo.

echo [1/3] dependencies
python -m pip install --quiet pythonnet pystray pillow psutil
if errorlevel 1 (
    echo   pip failed -- check that python is on PATH.
    pause
    exit /b 1
)

echo [2/3] locating pythonw.exe
for /f "delims=" %%P in ('python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set PYW=%%P
if not exist "%PYW%" (
    echo   could not find pythonw.exe next to python.exe
    pause
    exit /b 1
)
echo   %PYW%

echo [3/3] registering scheduled task "AIO_Screen"
rem  ONLOGON + RL HIGHEST is how a background app gets admin rights at startup
rem  WITHOUT a UAC prompt every boot. Task Scheduler holds the elevation.
schtasks /Create /TN "AIO_Screen" /SC ONLOGON /RL HIGHEST /F ^
  /TR "\"%PYW%\" \"%~dp0aio_daemon.pyw\""
if errorlevel 1 (
    echo   failed to create the task.
    pause
    exit /b 1
)

echo.
echo Done. Starting it now so you do not have to log out...
schtasks /Run /TN "AIO_Screen" >nul
echo Creating a desktop shortcut for restarting it after a Quit...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0create_shortcut.ps1"

echo.
echo   * look for the tray icon (it may be under the ^^ overflow arrow)
echo   * settings:  config.json     log:  aio_daemon.log
echo   * remove it: UNINSTALL_STARTUP.bat
echo.
pause
