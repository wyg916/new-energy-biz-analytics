@echo off
setlocal EnableExtensions
title Renewable Operations - Full Integration 4.1 Startup

cd /d "%~dp0"

echo.
echo ============================================================
echo   Renewable Operations Analytics - Full Integration 4.1
echo   Version: 4.1.0-integration-full.1 ^| Migration: integration_41_full_0001
echo   P6 business loops, DATA/RAG/Memory and registered ModelGateway providers.
echo   Open NL2SQL: disabled. Formal ChatBI: deterministic only.
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
echo [FAILED] Full Integration 4.1 startup did not pass all checks.
echo Review runtime startup reports for non-secret diagnostics.
echo.
echo Press any key to close this window.
pause >nul
exit /b 1
