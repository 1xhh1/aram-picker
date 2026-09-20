@echo off
rem One-click packaging script for ARAM Picker
rem Usage:
rem   build.bat            -> package with current version in aram_picker/_version.py
rem   build.bat 1.4.1      -> set version then package
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found in PATH. Please install Python 3.10+ first.
    pause
    exit /b 1
)

rem Ensure PyInstaller is available
python -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo [SETUP] Installing PyInstaller, please wait...
    python -m pip install "pyinstaller>=6.0,<7"
    if errorlevel 1 (
        echo [ERROR] PyInstaller installation failed. Check your network.
        pause
        exit /b 1
    )
)

echo [OK] Building ARAM Picker executable...
python build_exe.py %*
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. See messages above.
) else (
    echo.
    echo [DONE] Check the dist\ folder for the versioned exe.
)
pause
endlocal
