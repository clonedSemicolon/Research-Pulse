@echo off
echo.
echo ========================================
echo   ResearchPulse Updater
echo ========================================
echo.

REM Check current version
echo [*] Current version:
research-pulse --version 2>nul
echo.

REM Update via pip
echo [*] Updating ResearchPulse...
echo.

pip install research-pulse --upgrade --quiet

if %errorlevel% neq 0 (
    echo [!] Trying with --user flag...
    pip install research-pulse --upgrade --user --quiet
)

echo.
echo [*] New version:
research-pulse --version
echo.

echo ========================================
echo   Update Complete!
echo ========================================
echo.

pause
