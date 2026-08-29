@echo off
setlocal
cd /d "%~dp0"

rem  Folder build: "dist\AIO Screen\AIO Screen.exe" plus its libraries beside
rem  it. Less convenient to distribute (zip the folder), but it does not have
rem  to unpack anything at startup, which is what usually trips up pythonnet
rem  and the .NET runtime in a single-file build.

set AIO_ONEDIR=1
echo Building the FOLDER version (dist\AIO Screen\).
echo.
python -m pip install --disable-pip-version-check --quiet pyinstaller
python -m pip install --disable-pip-version-check --quiet -r requirements.txt
python -m PyInstaller --noconfirm --clean aio_screen.spec
if errorlevel 1 (
    echo.
    echo   Build failed -- see the error above.
    pause
    exit /b 1
)
echo.
if exist "dist\AIO Screen\AIO Screen.exe" (
    echo   dist\AIO Screen\AIO Screen.exe
    echo.
    echo   Test it:  "dist\AIO Screen\AIO Screen.exe" --doctor
    echo   To ship it, zip the whole "dist\AIO Screen" folder.
) else (
    echo   Expected dist\AIO Screen\AIO Screen.exe but it is not there.
)
echo.
pause
