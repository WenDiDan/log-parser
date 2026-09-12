@echo off
:: ============================================================
:: Locate a usable Python interpreter and set the variable PY.
::
:: Usage:
::   call "%~dp0_find_python.bat"                        :: only needs stdlib
::   call "%~dp0_find_python.bat" tkinter                :: needs tkinter
::   call "%~dp0_find_python.bat" "tkinter, matplotlib"  :: needs several
::   if errorlevel 1  -> no usable python found
::   "%PY%"  your_script.py
::
:: Candidate order:
::   1) LOGPARSER_PYTHON env var (explicit override)
::   2) .venv next to this script
::   3) C:\Users\<you>\AppData\Local\Python\bin\python.exe   (system 3.x)
::   4) %USERPROFILE%\.workbuddy\...\envs\default\Scripts\python.exe
::
:: Why not just "where python":
::   Windows Store installs python.exe / py.exe as stubs under
::   %LOCALAPPDATA%\Microsoft\WindowsApps. They do nothing and
::   still return exit code 0, so a plain existence check is not
::   enough. Every candidate here must really import the requested
::   modules, which a stub can never do.
::
:: NOTE 1: keep this file pure ASCII.
:: NOTE 2: never put unescaped parens in an echo line inside an
::         if/for block - cmd reads a ")" as the end of the block.
:: ============================================================
set "_REQ=%~1"
if not defined _REQ set "_REQ=sys"

set "PY="
if defined LOGPARSER_PYTHON set "PY=%LOGPARSER_PYTHON%"

set "_LOCALV=%~dp0.venv\Scripts\python.exe"
set "_SYS=%LOCALAPPDATA%\Python\bin\python.exe"
set "_WBV=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"

if not defined PY if exist "%_LOCALV%" ("%_LOCALV%" -c "import %_REQ%" >nul 2>nul && set "PY=%_LOCALV%")
if not defined PY if exist "%_SYS%" ("%_SYS%" -c "import %_REQ%" >nul 2>nul && set "PY=%_SYS%")
if not defined PY if exist "%_WBV%" ("%_WBV%" -c "import %_REQ%" >nul 2>nul && set "PY=%_WBV%")

if not defined PY (
  echo [ERROR] No usable Python found. Required modules: %_REQ% 1>&2
  echo         Install Python 3, create a .venv, or set LOGPARSER_PYTHON. 1>&2
  exit /b 1
)
exit /b 0
