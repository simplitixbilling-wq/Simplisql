@echo off
setlocal EnableDelayedExpansion

echo ============================================================
echo  SimpliSQL - Build Script
echo ============================================================
echo.

:: ── Locate Python (prefer venv, fall back to system) ────────────────
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo [WARN] .venv not found, using system Python
    set "PYTHON=python"
)

:: ── Verify PyInstaller is available ─────────────────────────────────
"%PYTHON%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing PyInstaller...
    "%PYTHON%" -m pip install pyinstaller --quiet
)

:: ── Clean previous build output ──────────────────────────────────────
echo [1/4] Cleaning previous build artefacts...
if exist "%~dp0build"  rmdir /s /q "%~dp0build"
if exist "%~dp0dist"   rmdir /s /q "%~dp0dist"
echo       Done.
echo.

:: ── Remove stale __pycache__ ─────────────────────────────────────────
echo [2/4] Removing __pycache__ folders...
for /d /r "%~dp0" %%d in (__pycache__) do (
    if exist "%%d" rmdir /s /q "%%d"
)
echo       Done.
echo.

:: ── Run PyInstaller ──────────────────────────────────────────────────
echo [3/4] Building SimpliSQL with PyInstaller...
echo       Spec file: SimpliSQL.spec
echo.
"%PYTHON%" -m PyInstaller SimpliSQL.spec --noconfirm
if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller build failed. Check output above for details.
    pause
    exit /b 1
)
echo.

:: ── Done ─────────────────────────────────────────────────────────────
echo [4/4] Build complete!
echo.
echo  Output folder : dist\SimpliSQL\
echo  Executable    : dist\SimpliSQL\SimpliSQL.exe
echo.
echo  NOTE: The 'models' folder is bundled but GGUF files are large.
echo        If models are missing in dist, copy them manually:
echo          xcopy /s /y models dist\SimpliSQL\models\
echo.
echo ============================================================
pause
