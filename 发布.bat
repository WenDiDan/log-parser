@echo off
setlocal EnableDelayedExpansion

:: LogParser one-click GitHub Releases publish
:: Usage: publish.bat [owner/repo]
set "REPO=WenDiDan/log-parser"
if not "%~1"=="" set "REPO=%~1"

set "ASSETS_DIR=%~dp0github-release"

:: 1. locate a usable Python (rejects Windows Store stubs)
call "%~dp0_find_python.bat"
if errorlevel 1 (
  pause
  exit /b 1
)
echo Using Python: %PY%

:: 2. check gh
where gh >nul 2>nul || (
  echo [ERROR] GitHub CLI gh not found.
  echo Install: winget install GitHub.cli   or visit https://cli.github.com
  pause
  exit /b 1
)

:: 3. check login
gh auth status >nul 2>nul || (
  echo [INFO] Not logged in to GitHub CLI, starting login...
  gh auth login
  if errorlevel 1 (
    echo [ERROR] Login failed, publish cancelled.
    pause
    exit /b 1
  )
)

:: 4. version consistency check (single source of truth: LogParser.py)
"%PY%" "%~dp0check_version.py"
if errorlevel 1 (
  echo [ERROR] Version mismatch. Run:  "%PY%" "%~dp0check_version.py" --fix
  pause
  exit /b 1
)

:: 5. read TAG from the same single source of truth
::    (replaces parsing version.json with findstr)
set "TAG="
for /f "delims=" %%a in ('call "%PY%" "%~dp0check_version.py" --tag') do set "TAG=%%a"
if not defined TAG (
  echo [ERROR] Cannot read version tag.
  pause
  exit /b 1
)

:: 6. check assets
if not exist "%ASSETS_DIR%\version.json" (
  echo [ERROR] Missing %ASSETS_DIR%\version.json
  pause
  exit /b 1
)
if not exist "%ASSETS_DIR%\LogParser.exe" (
  echo [ERROR] Missing %ASSETS_DIR%\LogParser.exe, build it first.
  pause
  exit /b 1
)

:: 7. confirm
echo ============================================
echo  REPO: %REPO%
echo  TAG : %TAG%
echo  EXE : %ASSETS_DIR%\LogParser.exe
echo ============================================
set /p "CONFIRM=Publish this version? [Y/n]: "
if /i not "%CONFIRM%"=="Y" if /i not "%CONFIRM%"=="" (
  echo Publish cancelled.
  pause
  exit /b 0
)

:: 8. create or upload
::    NOTE: do NOT use "A && B || C" here - a failed upload would wrongly
::    trigger the create branch. Explicit if/else keeps the semantics right.
gh release view "%TAG%" --repo "%REPO%" >nul 2>nul
if errorlevel 1 (
  echo [INFO] Creating release %TAG% ...
  gh release create "%TAG%" "%ASSETS_DIR%\LogParser.exe" "%ASSETS_DIR%\version.json" --repo "%REPO%" --title "%TAG%" --notes "LogParser %TAG% auto release"
) else (
  echo [INFO] Tag already exists, appending assets...
  gh release upload "%TAG%" "%ASSETS_DIR%\LogParser.exe" "%ASSETS_DIR%\version.json" --repo "%REPO%" --clobber
)
if errorlevel 1 (
  echo [ERROR] Publish failed, check network or repo permission.
  pause
  exit /b 1
)

:: 9. post-publish self check (read the published manifest back)
set "VER=%TAG:v=%"
echo.
echo [INFO] Verifying published manifest ...
"%PY%" "%~dp0verify_release.py" --manifest "https://github.com/%REPO%/releases/download/%TAG%/version.json" --expect %VER%
if errorlevel 1 (
  echo [WARN] Self-check failed - CDN may need a few minutes. Re-run: verify_release.py --github
) else (
  echo [OK] Self-check passed.
)

echo.
echo [DONE] Published %TAG% to %REPO%
echo Upgrade URL: https://github.com/%REPO%/releases/download/%TAG%/version.json
pause
