@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul && (python LogParser.py) || (py LogParser.py)
if errorlevel 1 pause
