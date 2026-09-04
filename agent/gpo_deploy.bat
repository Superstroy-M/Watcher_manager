@echo off
::
:: SyncLayer — GPO Startup Script
:: Запускать через Group Policy: Computer Configuration -> Scripts -> Startup
:: ИЛИ вручную от Администратора на каждом ПК
::
:: Целевая схема: 1 x SyncLayerAgent.exe + 1 x Scheduled Task + 0 services
::

set SOURCE=\\YOUR_SERVER\SyncLayer\agent
set DEST=C:\Program Files\SyncLayer
set AGENT=%DEST%\SyncLayerAgent.exe

> nul 2>&1

if not exist "%SOURCE%\SyncLayerAgent.exe" exit /b 1
if not exist "%DEST%" mkdir "%DEST%"

copy /Y "%SOURCE%\SyncLayerAgent.exe" "%AGENT%" > nul 2>&1
copy /Y "%SOURCE%\install_common.ps1" "%DEST%\" > nul 2>&1
copy /Y "%SOURCE%\install_finalize.ps1" "%DEST%\" > nul 2>&1
copy /Y "%SOURCE%\install_verify.ps1" "%DEST%\" > nul 2>&1
if not exist "%AGENT%" exit /b 1

powershell -NoProfile -ExecutionPolicy Bypass -File "%DEST%\install_finalize.ps1" -AgentPath "%AGENT%" -AgentDir "%DEST%" -SkipStart
if errorlevel 1 exit /b 1

exit /b 0
