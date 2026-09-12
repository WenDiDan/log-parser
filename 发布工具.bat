@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: LogParser packaging + publishing GUI launcher
:: The GUI itself needs tkinter.
call "%~dp0_find_python.bat" tkinter
if errorlevel 1 (
  echo [ERROR] No Python with tkinter found. Install Python 3 and retry.
  pause
  exit /b 1
)

:: prefer pythonw so no console window stays behind
set "PYW=%PY:python.exe=pythonw.exe%"
if exist "%PYW%" (
  start "" "%PYW%" "%~dp0ReleaseTool.py"
) else (
  start "" "%PY%" "%~dp0ReleaseTool.py"
)
