@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo  Sin'X Launcher - Build Script
echo ========================================
echo [1/3] Memeriksa dependencies build...
pip install pyinstaller requests

echo.
echo [2/3] Mengompilasi Sin'X Launcher executable...
if exist SinX-Launcher.spec (
    pyinstaller --clean SinX-Launcher.spec
) else (
    pyinstaller --clean --onefile --windowed --name "SinX-Launcher" --icon="icon.ico" --add-data "icon.ico;." launcher.py
)

echo.
echo [3/3] Memeriksa hasil build...
if exist "dist\SinX-Launcher.exe" (
    echo ========================================
    echo  [SUKSES] Build selesai!
    echo  File exe: dist\SinX-Launcher.exe
    echo ========================================
    echo Distribusikan folder launcher atau jalankan Install-OSAP.bat.
) else (
    echo ========================================
    echo  [ERROR] Build gagal! File dist\SinX-Launcher.exe tidak ditemukan.
    echo ========================================
)
echo.
pause

