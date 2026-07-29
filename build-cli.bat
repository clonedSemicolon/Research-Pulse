@echo off
REM Build ResearchPulse CLI as standalone .exe
REM No Python required on target machine

echo ========================================
echo Building ResearchPulse CLI
echo ========================================

REM Check if PyInstaller is installed
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

REM Install dependencies (no desktop/GUI packages)
echo Installing dependencies...
pip install requests feedparser PyYAML Jinja2 python-dateutil rich --quiet

REM Build the executable
echo.
echo Building executable...
python -m PyInstaller ResearchPulse-CLI.spec --clean --noconfirm

echo.
echo ========================================
echo Build complete!
echo.
echo Executable: dist\research-pulse.exe
echo.
echo Usage:
echo   research-pulse help
echo   research-pulse subscribe email@example.com
echo   research-pulse search "machine learning"
echo.
echo Distribute this single .exe file.
echo No Python installation required.
echo ========================================

pause
