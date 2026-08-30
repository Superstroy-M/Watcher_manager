@echo off
:: Удаление агента WatcherManager
:: ЗАПУСКАТЬ ОТ ИМЕНИ АДМИНИСТРАТОРА

echo ============================================
echo  WatcherManager Agent Uninstaller
echo ============================================
echo.

net session >nul 2>&1
if %errorLevel% NEQ 0 (
    echo ОШИБКА: Запустите скрипт от имени Администратора!
    pause
    exit /b 1
)

set AGENT_DIR=%~dp0
set PYTHON=python

echo [1/3] Остановка сервиса...
%PYTHON% "%AGENT_DIR%tracker_service.py" stop 2>nul
timeout /t 2 /nobreak >nul

echo [2/3] Удаление сервиса...
%PYTHON% "%AGENT_DIR%tracker_service.py" remove

echo [3/3] Удаление задач планировщика...
schtasks /Delete /TN "SyncLayerAgent" /F >nul 2>&1
schtasks /Delete /TN "SyncLayerTray" /F >nul 2>&1

echo.
echo Агент удалён.
pause
