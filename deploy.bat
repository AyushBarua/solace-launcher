@echo off
:: ============================================================
:: deploy.bat  —  Solace full deploy script
::
:: IMPORTANT: All app code is FROZEN into Solace.exe via PyInstaller PYZ.
:: Editing .py files in dist\_internal has NO effect on what runs.
:: This script does the correct full rebuild every time.
::
:: Usage: deploy.bat
:: ============================================================

setlocal
set ISCC="C:\Users\Uesr\AppData\Local\Programs\Inno Setup 6\ISCC.exe"

echo ============================================================
echo  Solace Deploy — Full PyInstaller + Installer rebuild
echo ============================================================
echo.

:: Step 1: Kill any running Solace instance (locks files)
echo [0/2] Closing any running Solace instance...
taskkill /F /IM Solace.exe 2>nul
timeout /t 1 /nobreak >nul

:: Step 2: PyInstaller — freezes ALL source code into Solace.exe
echo [1/2] Running PyInstaller (freezes source into Solace.exe)...
python -m PyInstaller --noconfirm --clean Solace.spec
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: PyInstaller failed. Check output above.
    exit /b 1
)
echo PyInstaller done.
echo.

:: Step 3: Inno Setup — packages dist\Solace into Solace_Setup.exe
echo [2/2] Building installer (Inno Setup)...
%ISCC% installer.iss
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Inno Setup failed.
    exit /b 1
)

echo.
echo ============================================================
echo  Done! Installer ready: dist\Solace_Setup.exe
echo  You can also test directly: dist\Solace\Solace.exe
echo ============================================================
endlocal
