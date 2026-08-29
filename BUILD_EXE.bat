@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  Building "AIO Screen.exe"  (standalone, no Python needed)
echo ============================================================
echo.

echo [1/4] build dependencies
python -m pip install --disable-pip-version-check --quiet pyinstaller
python -m pip install --disable-pip-version-check --quiet -r requirements.txt
if errorlevel 1 (
    echo   pip failed -- is python on PATH?
    pause
    exit /b 1
)

echo.
echo [2/4] sensor library
if not exist "%~dp0lib\LibreHardwareMonitorLib.dll" (
    echo   lib\LibreHardwareMonitorLib.dll not found.
    echo   Fetching it so the .exe can read CPU temperature without any install.
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -DllOnly
)
if exist "%~dp0lib\LibreHardwareMonitorLib.dll" (
    echo   will bundle: lib\LibreHardwareMonitorLib.dll
) else (
    echo   WARNING: not found. The .exe will still build, but CPU temperature
    echo            and fan RPM will read 0 unless the vendor app is installed.
)

echo.
echo [3/4] running PyInstaller  (this takes a minute or two)
rem  No --onefile here: the .spec decides that, and passing both is an error.
rem  BUILD_EXE_FOLDER.bat sets AIO_ONEDIR for the folder build instead.
python -m PyInstaller --noconfirm --clean aio_screen.spec
if errorlevel 1 (
    echo.
    echo   Build failed -- see the error above.
    echo   If it mentions pythonnet, clr or the .NET runtime, try the folder
    echo   build, which does not have to unpack the runtime at startup:
    echo       BUILD_EXE_FOLDER.bat
    pause
    exit /b 1
)

echo.
echo [4/4] done
if exist "dist\AIO Screen.exe" (
    for %%A in ("dist\AIO Screen.exe") do echo   dist\AIO Screen.exe   %%~zA bytes
    echo.
    echo   Test it:  "dist\AIO Screen.exe"            (tray icon, UAC prompt^)
    echo   Check it: "dist\AIO Screen.exe" --doctor   (writes doctor_report.txt^)
    echo.
    echo   Upload that .exe to the GitHub release.
) else (
    echo   Expected dist\AIO Screen.exe but it is not there -- see the log above.
)
echo.
pause
