@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================
echo  SyncLayer EXE INSTALL
echo ============================================
echo.

net session >nul 2>&1
if errorlevel 1 (
    echo ERROR: Run as Administrator
    pause
    exit /b 1
)

if not exist "%~dp0SyncLayerAgent.exe" (
    echo ERROR: SyncLayerAgent.exe not found in this folder.
    echo Copy dist\SyncLayerAgent.exe here or run BUILD-EXE.bat first.
    pause
    exit /b 1
)

set "DEST=%ProgramFiles%\SyncLayer"
set "AGENT=%DEST%\SyncLayerAgent.exe"

if not exist "%DEST%" mkdir "%DEST%"
copy /Y "%~dp0SyncLayerAgent.exe" "%AGENT%" >nul
copy /Y "%~dp0install_common.ps1" "%DEST%\" >nul 2>&1
copy /Y "%~dp0install_finalize.ps1" "%DEST%\" >nul 2>&1
copy /Y "%~dp0install_verify.ps1" "%DEST%\" >nul 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -File "%DEST%\install_finalize.ps1" -AgentPath "%AGENT%" -AgentDir "%DEST%"
if errorlevel 1 (
    echo ERROR: install finalize failed
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%DEST%\install_verify.ps1"
if errorlevel 1 (
    echo ERROR: install verification failed
    pause
    exit /b 1
)

attrib +h "%DEST%" >nul 2>&1

echo.
echo OK. SyncLayerAgent.exe installed and started.
echo Dashboard: http://201.51.8.127:8000
echo.
pause
