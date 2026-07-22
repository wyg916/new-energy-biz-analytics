@echo off
setlocal EnableExtensions
title Renewable Operations Alpha - One-click Startup

cd /d "%~dp0"

echo.
echo ============================================================
echo   Renewable Operations Analytics - Product Alpha
echo   Fixed-seed simulated data only. Not for production use.
echo ============================================================
echo.

where docker >nul 2>&1
if errorlevel 1 goto :docker_missing

docker info >nul 2>&1
if errorlevel 1 goto :docker_not_running

docker compose version >nul 2>&1
if errorlevel 1 goto :compose_missing

if not exist ".env" (
    echo [1/4] Creating local development configuration from .env.example...
    copy /Y ".env.example" ".env" >nul
    if errorlevel 1 goto :failed
) else (
    echo [1/4] Existing local .env configuration found.
)

echo [2/4] Building and starting PostgreSQL, Redis, API and Web...
docker compose up -d --build
if errorlevel 1 goto :failed

echo [3/4] Checking and generating fixed-seed simulated data...
echo       The first 300,000-session generation may take several minutes.
docker compose exec -T api python -m app.data.seed --session-count 300000
if errorlevel 1 goto :failed

echo [4/4] Checking service status...
docker compose ps
if errorlevel 1 goto :failed

echo.
echo ============================================================
echo   STARTUP SUCCEEDED
echo   Web:      http://localhost:8080
echo   API docs: http://localhost:18000/docs
echo ============================================================
echo.
echo Opening the product page...
start "" "http://localhost:8080"
echo.
echo Press any key to close this window. Services will keep running.
pause >nul
exit /b 0

:docker_missing
echo [FAILED] Docker was not found. Install and start Docker Desktop first.
goto :hold_failure

:docker_not_running
echo [FAILED] Docker is not running. Start Docker Desktop and retry.
goto :hold_failure

:compose_missing
echo [FAILED] Docker Compose v2 was not found. Update Docker Desktop and retry.
goto :hold_failure

:failed
echo.
echo [FAILED] A startup command failed. Keep this window open for diagnostics.
echo Run "docker compose ps" to inspect the current service state.

:hold_failure
echo.
echo Press any key to close this window.
pause >nul
exit /b 1
