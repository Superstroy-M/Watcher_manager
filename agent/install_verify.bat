@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================
echo  SyncLayer INSTALL VERIFY
echo ============================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_verify.ps1"
set "RC=%ERRORLEVEL%"

echo.
if not "%RC%"=="0" (
    echo Install layout check FAILED.
    pause
    exit /b 1
)

echo Install layout check OK.
pause
exit /b 0
