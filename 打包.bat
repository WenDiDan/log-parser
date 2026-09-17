@echo off
:: ============================================================
:: Package LogParser into a standalone exe (dist\LogParser.exe).
::
:: Locates a Python that has tkinter + PyInstaller
:: via _find_python.bat, then runs build_inproc.py.
::
:: build_inproc.py applies an in-process shim for
:: PyInstaller.isolated.Python so the helper subprocess
:: (discover_hook_directories / process_search_paths) is NOT
:: spawned. On some machines that child process is killed or
:: severed, causing:
::   SubprocessDiedError: Child process died calling
::   discover_hook_directories() ... exit code 0
:: The shim removes that failure mode entirely.
:: ============================================================
setlocal
set "CODEBUDDY_SAFE_DELETE_SANDBOX=0"
cd /d "%~dp0"

call "%~dp0_find_python.bat" "tkinter, PyInstaller"
if errorlevel 1 (
  echo [ERROR] Need a Python with tkinter + PyInstaller to build.
  echo         Install them into that Python, or set LOGPARSER_PYTHON to it.
  pause
  exit /b 1
)

echo === Cleaning previous build artifacts ===
if exist build rmdir /s /q build
if exist dist\LogParser.exe del /f /q dist\LogParser.exe

echo === Starting PyInstaller via patched in-process launcher ===
"%PY%" build_inproc.py
if errorlevel 1 (
  echo [ERROR] Build failed. See messages above.
  pause
  exit /b 1
)

echo === Done. dist\LogParser.exe built with the detected Python. ===
pause
