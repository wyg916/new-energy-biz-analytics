@echo off
setlocal EnableExtensions
title Renewable Operations - Full Integration 4.1 Startup

cd /d "%~dp0"

echo.
echo ============================================================
echo   Renewable Operations Analytics - Full Integration 4.1
echo   P6 business loops, DATA/RAG/Memory and controlled SQLBot.
echo   Default SQLBot mode: SHADOW. Not production approved.
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
echo [FAILED] Full Integration 4.1 startup did not pass all checks.
echo Review runtime startup reports for non-secret diagnostics.
echo.
echo Press any key to close this window.
pause >nul
exit /b 1
