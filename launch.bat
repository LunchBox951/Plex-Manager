@echo off
setlocal enabledelayedexpansion

REM Change to script directory
cd /d "%~dp0"

REM Check if .env exists (info only - setup wizard will handle if missing)
if not exist .env (
    echo No .env file found - setup wizard will launch automatically.
    echo.
)

REM Check if Python is installed
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Please install Python 3 from python.org
    pause
    exit /b 2
)

REM Check Python version (should be 3.x)
python --version 2>&1 | findstr /R "Python 3\." >nul
if errorlevel 1 (
    echo ERROR: Python 3 is required. Please install Python 3 from python.org
    pause
    exit /b 2
)

REM Create virtual environment if missing
if not exist "venv\" (
    echo Creating virtual environment in .\venv...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        echo Make sure Python venv module is installed.
        pause
        exit /b 3
    )
)

REM Activate virtual environment
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment.
    pause
    exit /b 3
)

REM Upgrade pip in venv
echo Upgrading pip...
python -m pip install --upgrade pip >nul 2>&1

REM Install dependencies
if exist requirements.txt (
    echo Installing dependencies from requirements.txt...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Failed to install dependencies.
        call venv\Scripts\deactivate.bat
        pause
        exit /b 4
    )
) else (
    echo ERROR: requirements.txt not found!
    call venv\Scripts\deactivate.bat
    pause
    exit /b 4
)

REM Start Plex Manager
echo.
echo Starting Plex Manager...
python main.py

REM Deactivate venv after
call venv\Scripts\deactivate.bat

pause
