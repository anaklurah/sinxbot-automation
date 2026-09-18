@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ========================================
echo  Sin'X Automation - Enterprise Builder
echo ========================================

REM Find Python executable
set "PY_CMD=python"
python --version >nul 2>&1
if errorlevel 1 (
    if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
        set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    ) else if exist "%ProgramFiles%\Python311\python.exe" (
        set "PY_CMD=%ProgramFiles%\Python311\python.exe"
    ) else if exist "py.exe" (
        set "PY_CMD=py -3"
    )
)

echo [1/4] Memeriksa dependencies build...
"%PY_CMD%" -m pip install --quiet pyinstaller pywebview pythonnet requests
if errorlevel 1 (
    echo [ERROR] Gagal menginstall dependencies build.
    pause
    exit /b 1
)

echo.
echo [2/4] Mengompilasi sinx-automation.exe (Standalone Client)...
if exist sinx-automation.spec (
    "%PY_CMD%" -m PyInstaller --clean --noconfirm sinx-automation.spec
) else (
    echo [ERROR] sinx-automation.spec tidak ditemukan!
    pause
    exit /b 1
)

if not exist "dist\sinx-automation.exe" (
    echo ========================================
    echo  [ERROR] Build sinx-automation.exe gagal!
    echo ========================================
    pause
    exit /b 1
)

echo.
echo [3/4] Mengompilasi install.exe (Enterprise All-in-One Installer)...
if exist installer.spec (
    "%PY_CMD%" -m PyInstaller --clean --noconfirm installer.spec
) else (
    echo [WARNING] installer.spec tidak ditemukan, melewati build installer.
)

echo.
echo [4/4] Menyalin hasil build ke folder downloads...
if not exist "..\downloads" mkdir "..\downloads"
if exist "dist\sinx-automation.exe" copy /y "dist\sinx-automation.exe" "..\downloads\sinx-automation.exe" >nul
if exist "dist\install.exe" copy /y "dist\install.exe" "..\downloads\install.exe" >nul

echo ========================================
echo  [SUKSES] Semua file berhasil dikompilasi!
echo ========================================
if exist "..\downloads\install.exe" echo  - Enterprise Installer : downloads\install.exe
if exist "..\downloads\sinx-automation.exe" echo  - Standalone Client   : downloads\sinx-automation.exe
echo ========================================
echo Karyawan cukup menjalankan 'install.exe' (All-in-One).
echo.
pause

