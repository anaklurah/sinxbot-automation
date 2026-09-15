@echo off
echo ========================================
echo  OSAP Launcher - Build Script
echo ========================================
pip install pyinstaller requests
pyinstaller --onefile --windowed --name "OSAP-Launcher" launcher.py
echo.
echo Build selesai! File exe: dist\OSAP-Launcher.exe
echo Distribusikan ke karyawan.
pause
