@echo off
setlocal EnableExtensions
title Renewable Operations - P5B Local RC Startup

cd /d "%~dp0"

echo.
echo ============================================================
echo   Renewable Operations Analytics - P5B Local RC
echo   Version: 4.0.0-rc.3 ^| Migration: p5_0001
echo   Fixed-seed simulated data only. Not production approved.
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\release\start-project.ps1"
if errorlevel 1 goto :failed

echo.
echo Press any key to close this window. Services will keep running.
pause >nul
exit /b 0

:failed
echo.
echo [FAILED] P5B local RC startup did not pass all checks.
echo Review runtime\p5c-startup-report.json for non-secret diagnostics.
echo.
echo Press any key to close this window.
pause >nul
exit /b 1
