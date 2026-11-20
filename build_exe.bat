@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Stopping any running AIconomy instance...
taskkill /f /im AIconomy.exe >nul 2>&1
timeout /t 1 /nobreak >nul
echo [1/3] Compiling native RAM secret bridge (aiconomy-bridge.exe)...
if exist "%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" (
  "%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /optimize+ /target:exe /r:System.Web.Extensions.dll /out:"assets\aiconomy-bridge.exe" "app\bridge_host.cs"
)
echo [2/3] Syncing dependencies and PyInstaller...
uv sync --dev
echo [3/3] Building AIconomy.exe...
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
