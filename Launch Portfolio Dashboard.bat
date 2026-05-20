@echo off
cd /d "%~dp0"

REM Try the installed version first (Start Menu / per-user install)
set INSTALLED="%LOCALAPPDATA%\Programs\Portfolio Dashboard\Portfolio Dashboard.exe"
if exist %INSTALLED% (
    start "" %INSTALLED%
    exit /b
)

REM Fall back to win-unpacked (dev/portable mode)
set UNPACKED="%~dp0release\win-unpacked\Portfolio Dashboard.exe"
if exist %UNPACKED% (
    start "" %UNPACKED%
    exit /b
)

echo Portfolio Dashboard is not installed.
echo Please run: release\Portfolio Dashboard Setup 0.3.0.exe
pause
