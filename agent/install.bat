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
    echo Right click install.bat - Run as administrator
    echo.
    pause
    exit /b 1
)

set "SRC=%~dp0"
set "DEST=%ProgramFiles%\SyncLayer"
set "AGENT=%DEST%\SyncLayerAgent.exe"
set "PY_DIR=%ProgramFiles%\Python312"
set "PY=%PY_DIR%\python.exe"
set "PY_SETUP=%TEMP%\python-3.12.10-amd64.exe"
set "LOG=%TEMP%\synclayer-install.log"

echo Log: %LOG%
echo. > "%LOG%"

echo [1/7] Copy files to "%DEST%"
if not exist "%DEST%" mkdir "%DEST%"
xcopy /E /Y /Q /I "%SRC%*" "%DEST%\" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo ERROR: copy failed. See %LOG%
    pause
    exit /b 1
)

echo [2/7] Python
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

echo [3/7] pip packages
"%PY%" -m pip install --upgrade pip >> "%LOG%" 2>&1
"%PY%" -m pip install -r "%DEST%\requirements.txt" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo ERROR: pip install failed. See %LOG%
    type "%LOG%"
    pause
    exit /b 1
)
"%PY%" -m pywin32_postinstall -install >> "%LOG%" 2>&1

echo [4/7] Build SyncLayerAgent.exe
cd /d "%DEST%"
"%PY%" -m pip install pyinstaller >> "%LOG%" 2>&1
set "ICON_ARG="
if exist "%DEST%\icon.png" set "ICON_ARG=--icon icon.png --add-data icon.png;."
"%PY%" -m PyInstaller --noconfirm --clean --noconsole --onefile --name SyncLayerAgent %ICON_ARG% --distpath "%DEST%" --workpath "%TEMP%\synclayer-build" --specpath "%TEMP%\synclayer-build" app_main.py >> "%LOG%" 2>&1
if not exist "%AGENT%" (
    echo ERROR: SyncLayerAgent.exe build failed. See %LOG%
    pause
    exit /b 1
)

echo [5/7] Remove legacy service/task/run entries
powershell -NoProfile -ExecutionPolicy Bypass -File "%DEST%\install_finalize.ps1" -AgentPath "%AGENT%" -AgentDir "%DEST%" -CleanupOnly >> "%LOG%" 2>&1

echo [6/7] Register SyncLayerAgent task and start agent
powershell -NoProfile -ExecutionPolicy Bypass -File "%DEST%\install_finalize.ps1" -AgentPath "%AGENT%" -AgentDir "%DEST%" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo ERROR: install finalize failed. See %LOG%
    type "%LOG%"
    pause
    exit /b 1
)

echo [7/7] Verify install layout
powershell -NoProfile -ExecutionPolicy Bypass -File "%DEST%\install_verify.ps1" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo ERROR: install verification failed. See %LOG%
    type "%LOG%"
    pause
    exit /b 1
)

attrib +h "%DEST%" >nul 2>&1

echo.
echo ============================================
echo  OK. SyncLayer installed.
echo  Process : 1 x SyncLayerAgent.exe
echo  Autostart: task SyncLayerAgent on user logon
echo  Dashboard: https://watcher.tunellink.ru
echo  Wait 1-2 minutes then refresh the page.
echo ============================================
echo.
pause
exit /b 0
