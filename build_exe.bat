@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Acik olan eski surum kapatiliyor (varsa)...
taskkill /f /im AIconomy.exe >nul 2>&1
taskkill /f /im AI-Arac-Merkezi.exe >nul 2>&1
timeout /t 1 /nobreak >nul
echo [1/2] Bagimliliklar, surum kanali ve PyInstaller kontrol ediliyor...
uv sync --dev
uv run python -c "from app.updater import auto_stamp_version_json; auto_stamp_version_json()"
echo [2/2] AIconomy.exe uretiliyor...
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
echo Tamamlandi! EXE dosyasi: %~dp0dist\AIconomy.exe
pause
