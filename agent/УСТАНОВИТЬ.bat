@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================
echo  SyncLayer INSTALL
echo ============================================
echo.

net session >nul 2>&1
if errorlevel 1 (
    echo ERROR: Run as Administrator
    echo Right click INSTALL.bat - Run as administrator
    echo.
    pause
    exit /b 1
)

set "SRC=%~dp0"
set "DEST=%ProgramFiles%\SyncLayer"
set "PY_DIR=%ProgramFiles%\Python312"
set "PY=%PY_DIR%\python.exe"
set "PY_SETUP=%TEMP%\python-3.12.10-amd64.exe"
set "LOG=%TEMP%\synclayer-install.log"

echo Log: %LOG%
echo. > "%LOG%"

echo [1/6] Copy files to "%DEST%"
if not exist "%DEST%" mkdir "%DEST%"
xcopy /E /Y /Q /I "%SRC%*" "%DEST%\" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo ERROR: copy failed. See %LOG%
    pause
    exit /b 1
)

echo [2/6] Python
if exist "%PY%" goto HAVE_PY
where python >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%i in ('where python') do (
        set "PY=%%i"
        goto HAVE_PY
    )
)

echo Python not found. Downloading Python 3.12 ...
curl.exe -L --retry 3 -o "%PY_SETUP%" "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" >> "%LOG%" 2>&1
if not exist "%PY_SETUP%" (
    echo ERROR: cannot download Python. Need internet.
    type "%LOG%"
    pause
    exit /b 1
)
echo Installing Python, wait 1-3 minutes...
"%PY_SETUP%" /quiet InstallAllUsers=1 PrependPath=1 Include_pip=1 Include_tcltk=0 Include_test=0 TargetDir="%PY_DIR%"
if not exist "%PY%" (
    echo ERROR: Python install failed
    pause
    exit /b 1
)

:HAVE_PY
echo Using: %PY%

echo [3/6] pip packages
"%PY%" -m pip install --upgrade pip >> "%LOG%" 2>&1
"%PY%" -m pip install -r "%DEST%\requirements.txt" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo ERROR: pip install failed. See %LOG%
    type "%LOG%"
    pause
    exit /b 1
)
"%PY%" -m pywin32_postinstall -install >> "%LOG%" 2>&1

echo [4/6] Windows service
cd /d "%DEST%"
"%PY%" tracker_service.py stop >> "%LOG%" 2>&1
"%PY%" tracker_service.py remove >> "%LOG%" 2>&1
"%PY%" tracker_service.py install
if errorlevel 1 (
    echo ERROR: service install failed
    pause
    exit /b 1
)

echo [5/6] Start service
"%PY%" tracker_service.py start
if errorlevel 1 (
    echo Service start failed. Starting agent in user session...
    schtasks /Create /F /TN "SyncLayerAgent" /TR "\"%PY%\" \"%DEST%\run_test.py\"" /SC ONLOGON /RL HIGHEST /IT >> "%LOG%" 2>&1
    start "SyncLayer" "%PY%" "%DEST%\run_test.py"
    echo.
    echo Agent window opened. Do not close it for this test.
    echo Dashboard: http://201.51.8.127:8000
    echo.
    pause
    exit /b 0
)

echo [6/6] Tray task
schtasks /Create /F /TN "SyncLayerTray" /TR "\"%PY%\" \"%DEST%\tray_app.py\"" /SC ONLOGON /RL HIGHEST >> "%LOG%" 2>&1
attrib +h "%DEST%" >nul 2>&1

echo.
echo ============================================
echo  OK. SyncLayer installed.
echo  Dashboard: http://201.51.8.127:8000
echo  Wait 1-2 minutes then refresh the page.
echo ============================================
echo.
pause
exit /b 0
