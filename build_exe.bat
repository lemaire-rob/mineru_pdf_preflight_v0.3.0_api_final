@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo MinerU PDF Preflight Windows EXE build

echo Checking Python...
where py >nul 2>nul
if %errorlevel%==0 (
    set PY=py -3
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set PY=python
    ) else (
        echo.
        echo ERROR: Python was not found. Use GitHub Actions cloud build if this PC cannot install Python.
        echo.
        pause
        exit /b 1
    )
)

if not exist .venv (
    %PY% -m venv .venv
)
if not exist .venv\Scripts\activate.bat (
    echo ERROR: failed to create virtual environment.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name MinerU_PDF_Preflight ^
  --collect-all PySide6 ^
  --collect-all fitz ^
  --collect-all mineru ^
  app.py

if errorlevel 1 (
    echo.
    echo Build failed.
    pause
    exit /b 1
)

echo.
echo Build complete: dist\MinerU_PDF_Preflight.exe
pause
endlocal
