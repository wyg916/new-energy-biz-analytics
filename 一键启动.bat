@echo off
setlocal EnableExtensions
title Renewable Operations - Integration 4.1 Core Startup

cd /d "%~dp0"

echo.
echo ============================================================
echo   Renewable Operations Analytics - Integration 4.1 Core
echo   Version: 4.1.0-integration.1 ^| Migration: integration_41_merge_0001
echo   Open-source data, governed RAG and Memory lifecycle.
echo   SQLBot remains Shadow/disabled. Not production approved.
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
echo [FAILED] Integration 4.1 Core startup did not pass all checks.
echo Review runtime\integration41-startup-report.json for non-secret diagnostics.
echo.
echo Press any key to close this window.
pause >nul
exit /b 1
