@echo off
title Sin'X Automation - Installer
color 0b
echo ======================================================
echo           Sin'X Automation Installer
echo ======================================================
echo.

set "INSTALL_DIR=%LOCALAPPDATA%\SinXAutomation"
echo [1/4] Menyiapkan direktori aplikasi: %INSTALL_DIR%
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

echo [2/4] Menyalin file aplikasi dan Icon...
if exist "%~dp0sinx-automation.exe" (
    copy /y "%~dp0sinx-automation.exe" "%INSTALL_DIR%\sinx-automation.exe" >nul 2>&1
) else if exist "%~dp0dist\sinx-automation.exe" (
    copy /y "%~dp0dist\sinx-automation.exe" "%INSTALL_DIR%\sinx-automation.exe" >nul 2>&1
) else if exist "%~dp0SinX-Launcher.exe" (
    copy /y "%~dp0SinX-Launcher.exe" "%INSTALL_DIR%\sinx-automation.exe" >nul 2>&1
) else if exist "%~dp0dist\SinX-Launcher.exe" (
    copy /y "%~dp0dist\SinX-Launcher.exe" "%INSTALL_DIR%\sinx-automation.exe" >nul 2>&1
)

if exist "%~dp0icon.ico" (
    copy /y "%~dp0icon.ico" "%INSTALL_DIR%\icon.ico" >nul 2>&1
) else if exist "%~dp0dist\icon.ico" (
    copy /y "%~dp0dist\icon.ico" "%INSTALL_DIR%\icon.ico" >nul 2>&1
)

echo [3/4] Membuat Shortcut Desktop dengan Icon Resmi Sin'X...
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $d = [System.IO.Path]::Combine([System.Environment]::GetFolderPath('Desktop'), 'Sin''X Automation.lnk'); $s = $ws.CreateShortcut($d); $s.TargetPath = '%INSTALL_DIR%\sinx-automation.exe'; $s.WorkingDirectory = '%INSTALL_DIR%'; if (Test-Path '%INSTALL_DIR%\icon.ico') { $s.IconLocation = '%INSTALL_DIR%\icon.ico,0' }; $s.Save()"

echo [4/4] Membuat Shortcut Start Menu...
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $sm = [System.IO.Path]::Combine([System.Environment]::GetFolderPath('Programs'), 'Sin''X Automation.lnk'); $s = $ws.CreateShortcut($sm); $s.TargetPath = '%INSTALL_DIR%\sinx-automation.exe'; $s.WorkingDirectory = '%INSTALL_DIR%'; if (Test-Path '%INSTALL_DIR%\icon.ico') { $s.IconLocation = '%INSTALL_DIR%\icon.ico,0' }; $s.Save()"

echo.
echo ======================================================
echo   SUKSES! Sin'X Automation Berhasil Terpasang!
echo ======================================================
echo.
echo Icon aplikasi resmi sudah terpasang di Desktop: [Sin'X Automation]
echo.
set /p RUN_NOW="Buka Sin'X Automation sekarang? (Y/N, default Y): "
if /i "%RUN_NOW%" neq "n" (
    start "" "%INSTALL_DIR%\sinx-automation.exe"
)
exit /b
