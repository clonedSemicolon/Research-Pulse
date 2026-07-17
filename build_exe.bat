@echo off
REM Build ResearchPulse Desktop App as .exe
REM Requirements: pip install pyinstaller

echo ========================================
echo Building ResearchPulse Desktop App
echo ========================================

REM Check if PyInstaller is installed
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

REM Install dependencies
echo Installing dependencies...
pip install research-pulse[desktop] --quiet

REM Build the executable
echo.
echo Building executable...
python -m PyInstaller ResearchPulse.spec --clean --noconfirm

echo.
echo ========================================
echo Build complete!
echo.
echo Executable: dist\ResearchPulse.exe
echo.
echo You can distribute this single .exe file.
echo No Python installation required on target machine.
echo ========================================

pause
