@echo off
echo === FlexStore 3D Setup ===
echo.

echo [1/2] Copying StrokeBrush.glb to assets...
copy /Y "%USERPROFILE%\Downloads\StrokeBrush.glb" "%~dp0assets\StrokeBrush.glb"
if errorlevel 1 (
    echo ERROR: Could not find StrokeBrush.glb in Downloads.
    echo Please copy it manually to: %~dp0assets\
    goto install
)
echo Done.

:install
echo.
echo [2/2] Installing PyQt6-WebEngine...
call "%~dp0venv\Scripts\pip.exe" install PyQt6-WebEngine
echo.
echo === Setup complete! You can now run the launcher. ===
pause
