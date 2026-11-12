@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo  ============================================================
echo    NETWATCH - first-time setup
echo  ============================================================
echo.

set "PYTHON_CMD="
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=python"

if not defined PYTHON_CMD (
    py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=py -3.12"
)

if not defined PYTHON_CMD (
    echo [ERROR] Python 3.12 or newer was not found.
    echo.
    echo Install Python from https://www.python.org/downloads/windows/
    echo and enable "Add python.exe to PATH" during installation.
    goto :failed
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creating the project virtual environment...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 goto :failed
) else (
    echo [1/4] Reusing the existing .venv
)

".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] .venv uses Python older than 3.12.
    echo Delete the .venv folder and run setup.bat again.
    goto :failed
)

echo [2/4] Installing runtime dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo [3/4] Preparing runtime folders...
if not exist "data" mkdir "data"
if not exist "logs" mkdir "logs"
if not exist "data\.gitkeep" type nul > "data\.gitkeep"
if not exist "logs\.gitkeep" type nul > "logs\.gitkeep"

echo [4/4] Verifying the environment...
".venv\Scripts\python.exe" scripts\verify_env.py
if errorlevel 1 goto :verify_failed

echo.
echo  ============================================================
echo    Setup complete.
echo.
echo    Start NetWatch with:  start.bat
echo    Then open:            http://127.0.0.1:8000/
echo  ============================================================
echo.
if /i not "%~1"=="--no-pause" pause
exit /b 0

:verify_failed
echo.
echo [WARNING] Setup installed the packages, but the environment check
echo reported failures. Review the output above before starting NetWatch.
if /i not "%~1"=="--no-pause" pause
exit /b 1

:failed
echo.
echo [ERROR] Setup did not complete. Review the message above.
if /i not "%~1"=="--no-pause" pause
exit /b 1
