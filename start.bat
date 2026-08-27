@echo off
title GUARDIAN
cd /d "%~dp0"

if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe guardian.py %*
) else (
    echo.
    echo  ERROR: Virtual environment not found.
    echo  Please run install.bat first.
    echo.
)

echo.
echo GUARDIAN exited.
pause
