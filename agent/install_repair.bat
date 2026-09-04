@echo off
setlocal EnableExtensions
echo ============================================
echo  SyncLayer REPAIR / DIAGNOSTIC
echo ============================================
echo.

net session >nul 2>&1
if errorlevel 1 (
    echo ERROR: Run as Administrator
    pause
    exit /b 1
)

set "DIR="
if exist "%ProgramData%\SyncLayer\SyncLayerAgent.exe" set "DIR=%ProgramData%\SyncLayer"
if not defined DIR if exist "%ProgramFiles%\SyncLayer\SyncLayerAgent.exe" set "DIR=%ProgramFiles%\SyncLayer"

if not defined DIR (
    echo ERROR: SyncLayerAgent.exe not found in:
    echo   %ProgramData%\SyncLayer
    echo   %ProgramFiles%\SyncLayer
    echo Re-run SyncLayerSetup.exe as Administrator.
    pause
    exit /b 1
)

echo Agent folder: %DIR%
echo.

echo [1/3] Manual start test (5 sec)...
start "" /B "%DIR%\SyncLayerAgent.exe"
timeout /t 5 /nobreak >nul
tasklist | findstr /I SyncLayerAgent
if errorlevel 1 (
    echo WARNING: process not visible after manual start
) else (
    echo OK: SyncLayerAgent.exe is running
)
echo.

echo [2/3] Re-register task and start...
powershell -NoProfile -ExecutionPolicy Bypass -File "%DIR%\install_finalize.ps1" -AgentPath "%DIR%\SyncLayerAgent.exe" -AgentDir "%DIR%"
if errorlevel 1 (
    echo ERROR: install_finalize failed — see messages above
    goto SHOW_LOG
)

echo [3/3] Verify...
powershell -NoProfile -ExecutionPolicy Bypass -File "%DIR%\install_verify.ps1"
if errorlevel 1 (
    echo ERROR: verification failed
    goto SHOW_LOG
)

echo.
echo OK: SyncLayer should be running.
echo Dashboard: https://watcher.tunellink.ru
goto SHOW_LOG

:SHOW_LOG
echo.
echo === agent.log (last 30 lines) ===
if exist "%DIR%\agent.log" (
    powershell -NoProfile -Command "Get-Content -Path '%DIR%\agent.log' -Tail 30 -Encoding UTF8"
) else (
    echo (agent.log not found — exe likely blocked before first log write^)
)
echo.
echo === Scheduled task ===
schtasks /Query /TN "SyncLayerAgent" /V /FO LIST 2>nul
if errorlevel 1 echo Task SyncLayerAgent: NOT FOUND
echo.
pause
exit /b 0
