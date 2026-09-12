@echo off
:: ============================================================
:: Locate a usable Python interpreter and set the variable PY.
::
:: Usage:
::   call "%~dp0_find_python.bat"
::   if errorlevel 1  -> no usable python found
::   "%PY%"  your_script.py
::
:: Why not just "where python":
::   Windows Store installs python.exe / py.exe as stubs under
::   %LOCALAPPDATA%\Microsoft\WindowsApps. They do nothing and
::   still return exit code 0, so a plain existence check is not
::   enough. We require "python -V" to print a banner starting
::   with "Python" to prove the interpreter really runs.
::
:: NOTE 1: keep this file pure ASCII.
:: NOTE 2: never put unescaped parens in an echo line inside an
::         if/for block - cmd reads a ")" as the end of the block.
:: ============================================================
set "PY="
set "_LOCALV=%~dp0.venv\Scripts\python.exe"
set "_WBV=%USERPROFILE%\.workbuddy\binaries\python\envs\default\Scripts\python.exe"

if exist "%_LOCALV%" set "PY=%_LOCALV%"
if not defined PY if exist "%_WBV%" set "PY=%_WBV%"

if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 (
    for /f "tokens=1" %%v in ('python -V 2^>nul') do if /i "%%v"=="Python" set "PY=python"
  )
)

if not defined PY (
  echo [ERROR] No usable Python found - Windows Store stubs are rejected. 1>&2
  echo         Install Python 3, or create a .venv next to this script. 1>&2
  exit /b 1
)
exit /b 0
