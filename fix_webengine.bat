@echo off
echo Installing PyQt6-WebEngine into the project venv...
"E:\Solace\FlexStoreLauncher\venv\Scripts\python.exe" -m pip install PyQt6-WebEngine
echo.
echo Verifying...
"E:\Solace\FlexStoreLauncher\venv\Scripts\python.exe" -m pip show PyQt6-WebEngine
echo.
echo Done! Press any key to close.
pause
