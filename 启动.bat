@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: LogParser GUI needs tkinter - do not accept an interpreter without it.
call "%~dp0_find_python.bat" tkinter
if errorlevel 1 (
  echo [ERROR] No Python with tkinter found. Install Python 3 and retry.
  pause
  exit /b 1
)

"%PY%" LogParser.py
if errorlevel 1 pause
