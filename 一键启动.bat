@echo off
setlocal EnableExtensions
title Renewable Operations - Full Integration 4.1 Startup

cd /d "%~dp0"

echo.
echo ============================================================
echo   Renewable Operations Analytics - Full Integration 4.1
echo   Version: 4.1.0-integration-full.1 ^| Migration: integration_41_full_0001
echo   P6 business loops, DATA/RAG/Memory and controlled SQLBot.
echo   Default SQLBot mode: SHADOW. Not production approved.
echo ============================================================
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\release\start-project.ps1" -NoBrowser
if errorlevel 1 goto :failed

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Run-SQLBot41DOneClick.ps1" -PlatformNetwork "renewable-integration41-full-network" -RuntimeVolume "renewable-integration41-full_p4_runtime" -RedisDataVolume "renewable-integration41-full_p4_redis" -RedisContainer "renewable-integration41-full-redis-1" -PlatformApiContainer "renewable-integration41-full-api-1" -PlatformDatabaseHost "renewable-integration41-full-db-1" -PlatformApiImage "renewable-integration41-full-api:4.1.0-integration-full.1" -ExpectedRevision "integration_41_full_0001" -SQLBotContainer "renewable-sqlbot-41c-runtime-v1-10-0" -SQLBotHostPort 18082 -SQLBotVolumePrefix "renewable-sqlbot41c"
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
