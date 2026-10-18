@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_night_shift.ps1"
if errorlevel 1 (
    echo.
    echo Failed to start the app. Check the error above, then press any key.
    pause >nul
    exit /b 1
)
exit /b 0
