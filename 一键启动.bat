@echo off
setlocal EnableExtensions
title Renewable Operations - P6 4.1 Business Loop Startup

cd /d "%~dp0"

echo.
echo ============================================================
echo   Renewable Operations Analytics - P6 Business Closed Loops
echo   Version: 4.1.0-p6.1 ^| Migration: p6_41_0001
echo   Alerts, reports and metric governance; DATA/RAG/Memory retained.
echo   SQLBot remains Shadow/disabled. Notifications use a controlled receiver.
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
echo [FAILED] P6-4.1 startup did not pass all checks.
echo Review runtime\p6-41-startup-report.json for non-secret diagnostics.
echo.
echo Press any key to close this window.
pause >nul
exit /b 1
