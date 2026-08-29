@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem  Publish a release: push, then create it on GitHub with the .exe attached.
rem  Finds gh.exe even when winget's PATH update has not reached this shell,
rem  which is the usual reason "gh is not recognized" survives a relaunch.

rem  Default to the most recent tag rather than a hardcoded one, so this does
rem  not quietly re-publish an old version after the next bump.
set TAG=%1
if "%TAG%"=="" for /f "delims=" %%T in ('git describe --tags --abbrev^=0 2^>nul') do set TAG=%%T
if "%TAG%"=="" (
    echo   No tag given and none found. Usage: PUBLISH_RELEASE.bat vX.Y.Z
    pause
    exit /b 1
)

echo ============================================================
echo  Publishing %TAG%
echo ============================================================
echo.

rem --- 1. find gh -----------------------------------------------------------
set GH=
where gh >nul 2>&1 && set GH=gh
if not defined GH if exist "%ProgramFiles%\GitHub CLI\gh.exe" set GH=%ProgramFiles%\GitHub CLI\gh.exe
if not defined GH if exist "%ProgramFiles(x86)%\GitHub CLI\gh.exe" set GH=%ProgramFiles(x86)%\GitHub CLI\gh.exe
if not defined GH if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\gh.exe" set GH=%LOCALAPPDATA%\Microsoft\WinGet\Links\gh.exe
if not defined GH (
    for /f "delims=" %%G in ('dir /b /s "%LOCALAPPDATA%\Microsoft\WinGet\Packages\gh.exe" 2^>nul') do set GH=%%G
)
if not defined GH (
    echo   Could not find gh.exe anywhere obvious.
    echo   Use the web UI instead:
    echo     1. git push origin main ^&^& git push origin %TAG%
    echo     2. open the repo's Releases page, "Draft a new release"
    echo     3. choose tag %TAG%, paste RELEASE_NOTES_%TAG%.md, drag the .exe in
    pause
    exit /b 1
)
echo   using: %GH%

rem --- 2. find the built exe ------------------------------------------------
set APP=
if exist "dist\AIO Screen.exe" set APP=dist\AIO Screen.exe
if not defined APP if exist "dist\AIO Screen\AIO Screen.exe" (
    echo   folder build found -- zipping it for upload
    powershell -NoProfile -Command "Compress-Archive -Path 'dist\AIO Screen\*' -DestinationPath 'dist\AIO-Screen-%TAG%-folder.zip' -Force"
    set APP=dist\AIO-Screen-%TAG%-folder.zip
)
if not defined APP (
    echo   No built app found. Run BUILD_EXE.bat first.
    pause
    exit /b 1
)
echo   attaching: !APP!

rem --- 3. auth --------------------------------------------------------------
"%GH%" auth status >nul 2>&1
if errorlevel 1 (
    echo.
    echo   Not signed in to GitHub. A browser will open...
    "%GH%" auth login
    if errorlevel 1 ( echo   sign-in failed. & pause & exit /b 1 )
)

rem --- 4. push --------------------------------------------------------------
echo.
echo   pushing main and %TAG% ...
git push origin main
if errorlevel 1 ( echo   push failed. & pause & exit /b 1 )
git push origin %TAG%
if errorlevel 1 ( echo   tag push failed. & pause & exit /b 1 )

rem --- 5. release -----------------------------------------------------------
echo.
set NOTES=--notes-from-tag
if exist "..\RELEASE_NOTES_%TAG%.md" set NOTES=--notes-file "..\RELEASE_NOTES_%TAG%.md"
if exist "RELEASE_NOTES_%TAG%.md"    set NOTES=--notes-file "RELEASE_NOTES_%TAG%.md"

"%GH%" release create %TAG% --title "%TAG%" %NOTES% "!APP!"
if errorlevel 1 (
    echo.
    echo   Release creation failed -- if it already exists, upload the asset with:
    echo       "%GH%" release upload %TAG% "!APP!" --clobber
    pause
    exit /b 1
)

echo.
echo   Published. Opening the release page...
"%GH%" release view %TAG% --web
echo.
pause
