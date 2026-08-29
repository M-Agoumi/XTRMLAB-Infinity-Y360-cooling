@echo off
cd /d "%~dp0"
set LOG=%~dp0test_output.log
echo ==== AIO screen test %DATE% %TIME% ====> "%LOG%"
call :body >> "%LOG%" 2>&1
type "%LOG%"
echo.
echo ============================================
echo DONE. Output also saved to test_output.log
echo ============================================
pause
goto :eof

:body
echo ==== step 1: closing the vendor "PC Monitor" app ====
taskkill /F /IM "PC_Monitor.exe" /T
taskkill /F /IM "allComputerInfoGetPro.exe" /T
timeout /t 1 >nul
echo.
echo ==== step 2: dependencies ====
pip install psutil
echo.
echo ==== step 3: what HID devices are present? ====
python -u list_hid.py
echo.
echo ==== step 4: posting a test frame -- WATCH THE SCREEN ====
python -u test_send.py
goto :eof
