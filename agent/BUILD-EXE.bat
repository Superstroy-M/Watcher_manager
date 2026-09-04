@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================
echo  SyncLayer BUILD+PUBLISH
echo ============================================
echo.

net session >nul 2>&1
if errorlevel 1 (
    echo Run as Administrator
    pause
    exit /b 1
)

where python >nul 2>&1
if errorlevel 1 (
    if exist "%ProgramFiles%\Python312\python.exe" (
        set "PY=%ProgramFiles%\Python312\python.exe"
    ) else (
        echo Python not found. Finish install.bat first.
        pause
        exit /b 1
    )
) else (
    set "PY=python"
)

"%PY%" -m pip install pyinstaller -r requirements.txt

set "ICON_ARG="
if exist "%cd%\icon.png" set "ICON_ARG=--icon icon.png --add-data icon.png;."

"%PY%" -m PyInstaller --noconfirm --clean --noconsole --onefile --name SyncLayerAgent %ICON_ARG% app_main.py

if not exist "%cd%\dist\SyncLayerAgent.exe" (
    echo ERROR: build failed, dist\SyncLayerAgent.exe not found
    pause
    exit /b 1
)

set "STATIC_DIR=%~dp0..\server\static"
set "STATIC_EXE=%STATIC_DIR%\SyncLayerAgent.exe"
set "DOWNLOAD_URL=https://watcher.tunellink.ru/static/SyncLayerAgent.exe"

if not exist "%STATIC_DIR%" (
    echo ERROR: server\static folder not found:
    echo %STATIC_DIR%
    pause
    exit /b 1
)

echo.
echo Publishing to server\static ...
copy /Y "%cd%\dist\SyncLayerAgent.exe" "%STATIC_EXE%" >nul
if errorlevel 1 (
    echo ERROR: cannot copy exe to server\static
    pause
    exit /b 1
)

echo Verifying download URL ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r=Invoke-WebRequest -Uri '%DOWNLOAD_URL%' -Method Head -UseBasicParsing; if($r.StatusCode -ge 200 -and $r.StatusCode -lt 400){ exit 0 } else { exit 1 } } catch { exit 1 }"
if errorlevel 1 (
    echo WARNING: URL check failed: %DOWNLOAD_URL%
    echo If server is running on another host or port, update INSTALL-ONE.bat EXE_URL.
    echo.
    echo Local file is ready: %STATIC_EXE%
    pause
    exit /b 0
)

echo.
echo OK. Ready for install.
echo Build:  %cd%\dist\SyncLayerAgent.exe
echo Public: %STATIC_EXE%
echo URL:    %DOWNLOAD_URL%
echo.
echo Next step on employee PC: run INSTALL-ONE.bat as Administrator.
echo.
pause
