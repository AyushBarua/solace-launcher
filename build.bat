@echo off
echo Building FlexStore Launcher...

:: Ensure we're in the right directory
cd /d "%~dp0"

:: Install reportlab if needed
pip install reportlab --quiet

:: Build the executable
"venv\Scripts\pyinstaller.exe" --noconfirm --onedir ^
    --name "FlexStore" ^
    --add-data "games_db.json;." ^
    --add-data "assets;assets" ^
    --add-data "ui;ui" ^
    --add-data "core;core" ^
    --add-data "resources;resources" ^
    --hidden-import "reportlab.pdfgen.canvas" ^
    --hidden-import "reportlab.lib.pagesizes" ^
    --hidden-import "reportlab.lib.units" ^
    --icon "resources\icon.ico" ^
    launcher.py

echo Build complete. Executable is in dist\FlexStore\
pause
