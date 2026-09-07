@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Packaging LogParser ===

set CODEBUDDY_SAFE_DELETE_SANDBOX=0

rem ---- 1) Find a Python with matplotlib & PyInstaller ----
set "PY="
set "LOCALVENV=%~dp0.venv\Scripts\python.exe"
set "WBENV=C:\Users\Di\.workbuddy\binaries\python\envs\default\Scripts\python.exe"

if exist "%LOCALVENV%" (
    "%LOCALVENV%" -c "import matplotlib, PyInstaller" >nul 2>nul && set "PY=%LOCALVENV%"
)
if not defined PY if exist "%WBENV%" (
    "%WBENV%" -c "import matplotlib, PyInstaller" >nul 2>nul && set "PY=%WBENV%"
)
if not defined PY (
    where py >nul 2>nul && py -3 -c "import matplotlib, PyInstaller" >nul 2>nul && set "PY=py -3"
)
if not defined PY (
    where python >nul 2>nul && python -c "import matplotlib, PyInstaller" >nul 2>nul && set "PY=python"
)

rem ---- 2) Auto-create venv if no suitable Python found ----
if not defined PY (
    echo No Python with matplotlib & PyInstaller found. Creating venv...
    set "BOOT="
    where py >nul 2>nul && set "BOOT=py -3"
    if not defined BOOT where python >nul 2>nul && set "BOOT=python"
    if not defined BOOT (
        echo ERROR: Python not found. Please install Python 3.12+ and add to PATH.
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
    "%~dp0.venv\Scripts\python.exe" -m pip install pyinstaller matplotlib
    if errorlevel 1 (
        echo Dependency installation failed. Need internet or proxy.
        pause
        exit /b 1
    )
    set "PY=%~dp0.venv\Scripts\python.exe"
)

echo Using: %PY%
echo === Starting PyInstaller (may take 1-2 min) ===
"%PY%" -m PyInstaller --onefile --windowed --icon=app.ico --add-data="app.ico;." --version-file=version.txt --name=LogParser --noconfirm --hidden-import=urllib.request --hidden-import=PIL --hidden-import=PIL.ImageTk LogParser.py
if errorlevel 1 (
    echo Packaging failed! Check error messages above.
    pause
    exit /b 1
)
echo === Done: dist\LogParser.exe ===
pause