@echo off
setlocal EnableExtensions
title Renewable Operations - SQLBot 4.1D Controlled Startup

cd /d "%~dp0"

echo.
echo ============================================================
echo   Renewable Operations Analytics - SQLBot 4.1D
echo   Default mode: SHADOW ^| Migration: sqlbot_41c2
echo   Simulated/open-source-derived acceptance data. Not production.
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\release\start-project.ps1"
if errorlevel 1 goto :failed

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Run-SQLBot41DOneClick.ps1"
if errorlevel 1 goto :failed

echo.
echo Press any key to close this window. Services will keep running.
pause >nul
exit /b 0

:failed
echo.
echo [FAILED] SQLBot 4.1D controlled startup did not pass all checks.
echo Review runtime startup reports for non-secret diagnostics.
echo.
echo Press any key to close this window.
pause >nul
exit /b 1
