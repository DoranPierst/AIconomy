@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Acik olan eski surum kapatiliyor (varsa)...
taskkill /f /im AI-Arac-Merkezi.exe >nul 2>&1
timeout /t 1 /nobreak >nul
echo [1/2] Bagimliliklar ve PyInstaller kontrol ediliyor...
uv sync --dev
echo [2/2] Hafif ve tasinabilir AI-Arac-Merkezi.exe uretiliyor...
uv run pyinstaller --noconfirm --onefile --windowed --name "AI-Arac-Merkezi" ^
  --add-data "version.json;." ^
  --exclude-module PySide6.QtWebEngineCore ^
  --exclude-module PySide6.QtWebEngineWidgets ^
  --exclude-module PySide6.QtPdf ^
  --exclude-module PySide6.QtQml ^
  --exclude-module PySide6.QtQuick ^
  main.py
echo.
echo Tamamlandi! EXE dosyasi: %~dp0dist\AI-Arac-Merkezi.exe
pause
