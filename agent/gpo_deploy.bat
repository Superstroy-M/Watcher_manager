@echo off
::
:: SyncLayer — GPO Startup Script
:: Запускать через Group Policy: Computer Configuration → Scripts → Startup
:: ИЛИ вручную от Администратора на каждом ПК
::
:: Что делает:
::   1. Копирует агент с сетевой папки на ПК (если не установлен)
::   2. Устанавливает и запускает Windows Service
::   3. Повторные запуски — ничего не делают (idempotent)
::

:: ──────────────────────────────────────────
:: НАСТРОЙТЕ ЭТИ ПАРАМЕТРЫ ПЕРЕД ЗАПУСКОМ
:: ──────────────────────────────────────────

:: Сетевая папка с файлами агента (UNC путь к share на вашем сервере)
set SOURCE=\\YOUR_SERVER\SyncLayer\agent

:: Куда устанавливать на каждом ПК
set DEST=C:\Program Files\SyncLayer

:: Имя сервиса (должно совпадать с config.py)
set SVC_NAME=SyncLayer

:: Python на целевых машинах (если используете embedded Python — укажите путь)
set PYTHON=python

:: ──────────────────────────────────────────

:: Тихий режим — ничего не показываем пользователю
> nul 2>&1

:: Проверяем, запущен ли уже сервис
sc query "%SVC_NAME%" | find "RUNNING" > nul 2>&1
if %errorLevel% EQU 0 (
    :: Сервис уже работает — обновляем файлы если версия изменилась
    xcopy /E /Y /Q "%SOURCE%\*" "%DEST%\" > nul 2>&1
    exit /b 0
)

:: Проверяем, установлен ли сервис (но не запущен)
sc query "%SVC_NAME%" > nul 2>&1
if %errorLevel% EQU 0 (
    :: Установлен, но не запущен — просто запускаем
    sc start "%SVC_NAME%" > nul 2>&1
    exit /b 0
)

:: Первая установка — копируем файлы
if not exist "%DEST%" mkdir "%DEST%"
xcopy /E /Y /Q "%SOURCE%\*" "%DEST%\" > nul 2>&1
if %errorLevel% NEQ 0 exit /b 1

:: Устанавливаем зависимости Python
%PYTHON% -m pip install -r "%DEST%\requirements.txt" -q > nul 2>&1

:: Устанавливаем сервис
cd /d "%DEST%"
%PYTHON% tracker_service.py install > nul 2>&1
%PYTHON% tracker_service.py start > nul 2>&1

exit /b 0
