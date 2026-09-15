@echo off
echo ========================================
echo  Sin'X Launcher - Build Script
echo ========================================
pip install pyinstaller requests
pyinstaller --clean SinX-Launcher.spec
echo.
echo Build selesai! File exe: dist\SinX-Launcher.exe
echo Distribusikan ke karyawan.
pause

