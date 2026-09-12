@echo off
setlocal

:: LogParser one-click Gitee publish
:: Token source (never committed):
::   env var GITEE_TOKEN  or  %USERPROFILE%\.logparser\gitee_token.txt
:: NOTE: keep this file pure ASCII. Chinese chars in a .bat get read as GBK
:: and will corrupt the whole script.

:: 1. locate a usable Python (rejects Windows Store stubs)
call "%~dp0_find_python.bat"
if errorlevel 1 (
  pause
  exit /b 1
)
echo Using Python: %PY%
echo.

:: 2. version consistency check (single source of truth: LogParser.py)
"%PY%" "%~dp0check_version.py"
if errorlevel 1 (
  echo [ERROR] Version mismatch. Run:  "%PY%" "%~dp0check_version.py" --fix
  pause
  exit /b 1
)
echo.

:: 3. publish
"%PY%" "%~dp0publish_gitee.py"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [ERROR] Publish failed, exit code %RC%
  pause
  exit /b %RC%
)

:: 4. post-publish self check (read the published manifest back)
echo.
echo [INFO] Verifying published Gitee manifest ...
"%PY%" "%~dp0verify_release.py" --gitee
if errorlevel 1 (
  echo [WARN] Self-check failed - CDN may need a few minutes. Re-run: verify_release.py --gitee
) else (
  echo [OK] Self-check passed.
)

echo.
echo [DONE] Gitee publish finished
pause
exit /b 0
