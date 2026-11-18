@echo off
chcp 65001 >nul
cd /d "%~dp0"
start "" uv run pythonw main.py
