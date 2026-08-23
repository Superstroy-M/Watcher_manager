@echo off
:: Установка агента WatcherManager
:: ЗАПУСКАТЬ ОТ ИМЕНИ АДМИНИСТРАТОРА

echo ============================================
echo  WatcherManager Agent Installer
echo ============================================
echo.

:: Проверка прав администратора
net session >nul 2>&1
if %errorLevel% NEQ 0 (
    echo ОШИБКА: Запустите скрипт от имени Администратора!
    echo Правая кнопка на install.bat → "Запуск от имени администратора"
    pause
    exit /b 1
)

set AGENT_DIR=%~dp0
set PYTHON=python

:: Проверка Python
%PYTHON% --version >nul 2>&1
if %errorLevel% NEQ 0 (
    echo ОШИБКА: Python не найден. Установите Python 3.10+ и добавьте в PATH
    pause
    exit /b 1
)

echo [1/4] Установка зависимостей...
%PYTHON% -m pip install -r "%AGENT_DIR%requirements.txt" --quiet
if %errorLevel% NEQ 0 (
    echo ОШИБКА при установке зависимостей!
    pause
    exit /b 1
)

echo [2/4] Регистрация Windows Service...
cd /d "%AGENT_DIR%"
%PYTHON% tracker_service.py install
if %errorLevel% NEQ 0 (
    echo ОШИБКА при установке сервиса!
    pause
    exit /b 1
)

echo [3/4] Запуск сервиса...
%PYTHON% tracker_service.py start
if %errorLevel% NEQ 0 (
    echo ОШИБКА при запуске сервиса!
    pause
    exit /b 1
)

echo [4/4] Настройка автозапуска трея при входе пользователя...
schtasks /Create /F /TN "WatcherManagerTray" /TR "\"%PYTHON%\" \"%AGENT_DIR%tray_app.py\"" /SC ONLOGON /RL HIGHEST >nul

echo.
echo ============================================
echo  Установка завершена успешно!
echo  Сервис запущен и будет стартовать автоматически.
echo  Пользователь видит иконку в трее.
echo  Остановить сервис может только Администратор.
echo ============================================
echo.
pause
