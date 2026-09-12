@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Packaging LogParser ===

set CODEBUDDY_SAFE_DELETE_SANDBOX=0

rem ---- 1) Find a Python with tkinter + matplotlib + PyInstaller ----
rem WBENV (WorkBuddy managed venv) has matplotlib+PyInstaller but NO tkinter, so it is skipped.
set "PY="
set "LOCALVENV=%~dp0.venv\Scripts\python.exe"
set "SYS314=C:\Users\Di\AppData\Local\Python\bin\python.exe"
set "WBENV=C:\Users\Di\.workbuddy\binaries\python\envs\default\Scripts\python.exe"

if exist "%LOCALVENV%" (
    "%LOCALVENV%" -c "import tkinter, matplotlib, PyInstaller" >nul 2>nul && set "PY=%LOCALVENV%"
)
if not defined PY if exist "%SYS314%" (
    "%SYS314%" -c "import tkinter, matplotlib, PyInstaller" >nul 2>nul && set "PY=%SYS314%"
)
if not defined PY if exist "%WBENV%" (
    "%WBENV%" -c "import tkinter, matplotlib, PyInstaller" >nul 2>nul && set "PY=%WBENV%"
)
if not defined PY (
    where py >nul 2>nul && py -3.14 -c "import tkinter, matplotlib, PyInstaller" >nul 2>nul && set "PY=py -3.14"
)
if not defined PY (
    where python >nul 2>nul && python -c "import tkinter, matplotlib, PyInstaller" >nul 2>nul && set "PY=python"
)

rem ---- 2) Auto-create a venv from Python 3.14 (has tkinter) if no suitable Python found ----
if not defined PY (
    echo No Python with tkinter + matplotlib + PyInstaller found. Creating venv from 3.14...
    set "BOOT="
    if exist "%SYS314%" set "BOOT=%SYS314%"
    if not defined BOOT where py >nul 2>nul && py -3.14 -c "import tkinter" >nul 2>nul && set "BOOT=py -3.14"
    if not defined BOOT where python >nul 2>nul && set "BOOT=python"
    if not defined BOOT where py >nul 2>nul && set "BOOT=py -3"
    if not defined BOOT (
        echo ERROR: Python 3.12+ not found. Please install Python and add to PATH.
        pause
        exit /b 1
    )
    echo Using %BOOT% to create .venv ...
    %BOOT% -m venv "%~dp0.venv"
    if errorlevel 1 (
        echo Failed to create venv. Check your Python installation.
        pause
        exit /b 1
    )
    "%~dp0.venv\Scripts\python.exe" -m pip install --upgrade pip
    "%~dp0.venv\Scripts\python.exe" -m pip install pyinstaller matplotlib pillow
    if errorlevel 1 (
        echo Dependency installation failed. Need internet or proxy.
        pause
        exit /b 1
    )
    set "PY=%~dp0.venv\Scripts\python.exe"
)

echo Using: %PY%

rem ---- 2.5) Version consistency check (single source of truth: LogParser.py) ----
%PY% "%~dp0check_version.py"
if errorlevel 1 (
    echo Version mismatch detected. Run  check_version.py --fix  before packaging.
    pause
    exit /b 1
)

rem ---- Clean previous build artifacts for a fresh package ----
if exist build rmdir /s /q build
if exist "dist\LogParser.exe" del /q "dist\LogParser.exe"
echo === Starting PyInstaller (patched in-process launcher, may take 1-2 min) ===
rem build_inproc.py applies an in-process shim for PyInstaller.isolated.Python so the
rem helper subprocess (discover_hook_directories / process_search_paths) does NOT spawn
rem a child process. On some machines that child process is killed/severed, causing
rem "SubprocessDiedError: Child process died calling discover_hook_directories()".
%PY% build_inproc.py
if errorlevel 1 (
    echo Packaging failed! Check error messages above.
    pause
    exit /b 1
)
echo === Done: dist\LogParser.exe ===
pause
