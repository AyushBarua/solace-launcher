@echo off
echo === Step 0: Installing/updating dependencies in the venv ===
"E:\Solace\FlexStoreLauncher\venv\Scripts\python.exe" -m pip install -r "E:\Solace\FlexStoreLauncher\requirements.txt" --quiet
if errorlevel 1 (
    echo.
    echo pip install FAILED. See errors above.
    pause
    exit /b 1
)

echo.
echo === Step 1: Building Solace.exe with PyInstaller ===
"E:\Solace\FlexStoreLauncher\venv\Scripts\python.exe" -m PyInstaller --noconfirm "E:\Solace\FlexStoreLauncher\Solace.spec"
if errorlevel 1 (
    echo.
    echo PyInstaller FAILED. See errors above.
    pause
    exit /b 1
)

echo.
echo === Step 2: Compiling Solace_Setup.exe with Inno Setup ===
"C:\Users\Uesr\AppData\Local\Programs\Inno Setup 6\ISCC.exe" "E:\Solace\FlexStoreLauncher\installer.iss"
if errorlevel 1 (
    echo.
    echo Inno Setup FAILED. See errors above.
    pause
    exit /b 1
)

echo.
echo === Done! dist\Solace_Setup.exe is ready ===
pause
