@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo Install SyncLayer.exe  (no Python on this PC)
echo.

net session >nul 2>&1
if errorlevel 1 (
    echo Run as Administrator
    pause
    exit /b 1
)

if not exist "%~dp0SyncLayer.exe" (
    echo ERROR: SyncLayer.exe not found in this folder.
    echo Copy the whole dist\SyncLayer folder here.
    pause
    exit /b 1
)

set "DEST=%ProgramFiles%\SyncLayer"
if not exist "%DEST%" mkdir "%DEST%"
xcopy /E /Y /Q /I "%~dp0*" "%DEST%\" >nul

schtasks /Create /F /TN "SyncLayer" /TR "\"%DEST%\SyncLayer.exe\"" /SC ONLOGON /RL HIGHEST /IT
start "" "%DEST%\SyncLayer.exe"
attrib +h "%DEST%" >nul 2>&1

echo.
echo OK. SyncLayer.exe started.
echo Dashboard: http://201.51.8.127:8000
echo.
pause
