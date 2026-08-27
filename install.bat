@echo off
title GUARDIAN Installer
color 0C

echo.
echo  ========================================
echo       GUARDIAN - INSTALLER
echo  ========================================
echo.

echo  [1/5] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Python is not installed or not in PATH.
    echo.
    echo  Please install Python 3.8+ from:
    echo  https://www.python.org/downloads/
    echo.
    echo  Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%a in ('python --version 2^>^&1') do set PYVER=%%a
echo  Found Python %PYVER%

echo.
echo  [2/5] Creating virtual environment...
if not exist "venv" (
    python -m venv venv
    if %errorlevel% neq 0 (
        echo  ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo  Virtual environment created.
) else (
    echo  Virtual environment already exists.
)

echo.
echo  [3/5] Activating virtual environment...
call venv\Scripts\activate.bat

echo.
echo  [4/5] Installing dependencies...
pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo  ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo  [5/5] Creating directories...
if not exist "config" mkdir config
if not exist "results\history" mkdir results\history
if not exist "logs" mkdir logs

echo.
echo  ========================================
echo   GUARDIAN installed successfully!
echo.
echo   Run start.bat to launch.
echo  ========================================
echo.
pause
