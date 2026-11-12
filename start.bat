@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo NetWatch is not set up yet. Running setup first...
    echo.
    call setup.bat --no-pause
    if errorlevel 1 (
        echo.
        echo [ERROR] Setup failed. NetWatch cannot start.
        pause
        exit /b 1
    )
)

echo.
echo  ============================================================
echo    NETWATCH - Network Operations Console
echo    Dashboard: http://127.0.0.1:8000/
echo    Press Ctrl+C to stop the server.
echo  ============================================================
echo.

".venv\Scripts\python.exe" run.py
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo NetWatch stopped with exit code %EXIT_CODE%.
    echo Check logs\netwatch.log for details.
    pause
)
exit /b %EXIT_CODE%
