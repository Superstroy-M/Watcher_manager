@echo off
:: Удаление SyncLayer агента
:: ЗАПУСКАТЬ ОТ ИМЕНИ АДМИНИСТРАТОРА

echo ============================================
echo  SyncLayer Uninstaller
echo ============================================
echo.

net session >nul 2>&1
if errorlevel 1 (
    echo ERROR: Run as Administrator
    pause
    exit /b 1
)

set "AGENT_DIR=%ProgramFiles%\SyncLayer"
if exist "%~dp0install_common.ps1" (
    set "COMMON=%~dp0install_common.ps1"
) else if exist "%AGENT_DIR%\install_common.ps1" (
    set "COMMON=%AGENT_DIR%\install_common.ps1"
) else (
    echo ERROR: install_common.ps1 not found
    pause
    exit /b 1
)

echo [1/2] Stop agent, remove service/tasks/run keys...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  ". '%COMMON%'; Remove-LegacySyncLayerInstall -AgentDir '%AGENT_DIR%' -StopProcesses"
if errorlevel 1 (
    echo ERROR: cleanup failed
    pause
    exit /b 1
)

echo [2/2] Verify cleanup...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  ". '%COMMON%'; $r = Test-SyncLayerInstall -ExpectedProcessCount 0 -RequireScheduledTask $false; Write-SyncLayerInstallReport -Result $r; if (-not $r.Ok) { exit 1 }"
if errorlevel 1 (
    echo WARNING: some legacy entries may remain. Check report above.
    pause
    exit /b 1
)

echo.
echo SyncLayer agent removed.
pause
