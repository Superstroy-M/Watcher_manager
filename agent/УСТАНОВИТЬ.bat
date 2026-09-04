@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ============================================
echo  SyncLayer INSTALL (alias)
echo ============================================
echo.
echo Redirecting to install.bat ...
echo.

call "%~dp0install.bat"
exit /b %ERRORLEVEL%
