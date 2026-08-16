@echo off
setlocal EnableExtensions
title Renewable Operations - Copy Local Login Password

cd /d "%~dp0"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\release\Copy-LocalOidcPassword.ps1"
if errorlevel 1 goto :failed

echo.
echo Press any key to close this window.
pause >nul
exit /b 0

:failed
echo.
echo [FAILED] The local login password could not be copied.
echo Start Docker Desktop and run the project launcher successfully, then retry.
echo.
echo Press any key to close this window.
pause >nul
exit /b 1
