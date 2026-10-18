@echo off
rem Recreates the desktop shortcut so it points to this project folder
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_desktop_shortcut.ps1"
pause
