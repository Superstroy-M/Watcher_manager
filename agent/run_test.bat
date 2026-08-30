@echo off
cd /d "%~dp0"
echo ============================================
echo  SyncLayer — тестовый запуск (без службы)
echo ============================================
echo.
python --version >nul 2>&1
if %errorLevel% NEQ 0 (
    echo Python не найден. Установите Python 3.10+ и поставьте галку Add to PATH.
    pause
    exit /b 1
)

echo Установка зависимостей...
python -m pip install -r requirements.txt
python -m pywin32_postinstall -install >nul 2>&1

echo.
echo Запуск агента. Окно не закрывать. Ctrl+C — стоп.
echo.
python run_test.py
pause
