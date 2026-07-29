@echo off
setlocal EnableDelayedExpansion

echo.
echo ========================================
echo   ResearchPulse Installer
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Python is installed.
    goto :install
)

echo [!] Python is not installed.
echo.

REM Try to install Python via winget (Windows 10/11)
winget --version >nul 2>&1
if %errorlevel% equ 0 (
    echo [*] Installing Python via winget...
    winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    if %errorlevel% equ 0 (
        echo [OK] Python installed successfully.
        REM Refresh PATH
        set "PATH=%LOCALAPPDATA%\Programs\Python\Python312\;%LOCALAPPDATA%\Programs\Python\Python312\Scripts\;%PATH%"
        goto :install
    )
)

REM Try chocolatey
choco --version >nul 2>&1
if %errorlevel% equ 0 (
    echo [*] Installing Python via Chocolatey...
    choco install python -y
    if %errorlevel% equ 0 (
        echo [OK] Python installed successfully.
        goto :install
    )
)

REM Manual install
echo.
echo [X] Could not install Python automatically.
echo.
echo Please install Python manually:
echo   1. Go to https://www.python.org/downloads/
echo   2. Download Python 3.10 or newer
echo   3. Run installer and CHECK "Add Python to PATH"
echo   4. Run this script again after installation
echo.
pause
exit /b 1

:install
echo.
echo [*] Installing ResearchPulse...
echo.

pip install research-pulse --quiet

if %errorlevel% neq 0 (
    echo [X] Installation failed. Trying with --user flag...
    pip install research-pulse --user --quiet
)

echo.
echo ========================================
echo   Installation Complete!
echo ========================================
echo.
echo Usage:
echo   research-pulse help              Show all commands
echo   research-pulse                   Today's papers
echo   research-pulse subscribe         Subscribe to newsletter
echo   research-pulse search "query"    Search papers
echo.
echo Run: research-pulse help
echo.

pause
