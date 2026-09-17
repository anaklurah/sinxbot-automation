@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo  Sin'X Automation - Build Script
echo ========================================
echo [1/3] Memeriksa dependencies build...
pip install pyinstaller requests

echo.
echo [2/3] Mengompilasi sinx-automation executable...
if exist sinx-automation.spec (
    pyinstaller --clean sinx-automation.spec
) else if exist SinX-Launcher.spec (
    pyinstaller --clean SinX-Launcher.spec
) else (
    pyinstaller --clean --onefile --windowed --name "sinx-automation" --icon="icon.ico" --add-data "icon.ico;." launcher.py
)

echo.
echo [3/3] Memeriksa hasil build...
if exist "dist\sinx-automation.exe" (
    echo ========================================
    echo  [SUKSES] Build selesai!
    echo  File exe: dist\sinx-automation.exe
    echo ========================================
    echo Distribusikan folder launcher atau jalankan Install-OSAP.bat.
) else (
    echo ========================================
    echo  [ERROR] Build gagal! File dist\sinx-automation.exe tidak ditemukan.
    echo ========================================
)
echo.
pause

