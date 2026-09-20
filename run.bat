@echo off
rem One-click launcher for ARAM Picker (uses system Python, no venv needed)
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found in PATH. Please install Python 3.10+ first.
    pause
    exit /b 1
)

rem Install dependencies automatically on first run
python -c "import PyQt6, qfluentwidgets, psutil, requests" >nul 2>nul
if errorlevel 1 (
    echo [SETUP] First run: installing dependencies, please wait...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed. Check your network.
        pause
        exit /b 1
    )
)

echo [OK] Starting ARAM Picker...
python main.py
if errorlevel 1 (
    echo [ERROR] Application exited with an error.
    pause
)
endlocal
