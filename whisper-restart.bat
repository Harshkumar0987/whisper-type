@echo off
cd /d "%~dp0"
taskkill /F /IM pythonw.exe >nul 2>&1
timeout /t 2 /nobreak >nul
start "" pythonw whisper-dictate.py
