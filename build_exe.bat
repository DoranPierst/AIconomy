@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Stopping any running AIconomy instance...
taskkill /f /im AIconomy.exe >nul 2>&1
taskkill /f /im AI-Arac-Merkezi.exe >nul 2>&1
timeout /t 1 /nobreak >nul
echo [1/2] Syncing dependencies and PyInstaller...
uv sync --dev
echo [2/2] Building AIconomy.exe...
uv run pyinstaller --noconfirm --onefile --windowed --name "AIconomy" ^
  --icon "assets/aiconomy.ico" ^
  --add-data "version.json;." ^
  --add-data "assets;assets" ^
  --exclude-module PySide6.QtWebEngineCore ^
  --exclude-module PySide6.QtWebEngineWidgets ^
  --exclude-module PySide6.QtPdf ^
  --exclude-module PySide6.QtQml ^
  --exclude-module PySide6.QtQuick ^
  main.py
echo.
echo Done! Standalone executable: %~dp0dist\AIconomy.exe
pause
