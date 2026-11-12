@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python not found. Install Python 3.11+ from https://www.python.org/downloads/
    echo Tick "Add python.exe to PATH" during installation.
    pause
    exit /b 1
)

where node >nul 2>nul
if errorlevel 1 (
    echo Node.js not found. Install Node.js LTS from https://nodejs.org/
    echo It is needed for the public HTTPS link.
    pause
    exit /b 1
)

if not exist ".env" (
    if exist ".env.example" copy ".env.example" ".env" >nul
)

echo Installing Python dependencies...
python -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo Dependency installation failed. Check the error above.
    pause
    exit /b 1
)

echo Starting the demo...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\start_demo.ps1"
pause
