@echo off
chcp 65001 >nul
cd /d "%~dp0"

call "%~dp0_find_python.bat"
if errorlevel 1 (
  echo [ERROR] No usable Python found. Install Python 3 and retry.
  pause
  exit /b 1
)

"%PY%" LogParser.py
if errorlevel 1 pause
