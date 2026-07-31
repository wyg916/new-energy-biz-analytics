#!/bin/sh
set -eu

# SQLBot v1.8.0 starts its bundled PostgreSQL asynchronously. On slow local
# Docker Desktop storage, first-start recovery can exceed the upstream
# 120-second wait-for-it window. This script is only for LOCAL_ACCEPTANCE_ONLY
# and does not change the pinned image or any persisted secret.

SSR_PATH=/opt/sqlbot/g2-ssr
APP_PATH=/opt/sqlbot/app
PM2_CMD_PATH="$SSR_PATH/node_modules/pm2/bin/pm2"
MAX_ATTEMPTS="${SQLBOT_LOCAL_DB_READY_ATTEMPTS:-120}"
SLEEP_SECONDS="${SQLBOT_LOCAL_DB_READY_INTERVAL_SECONDS:-5}"

/usr/local/bin/docker-entrypoint.sh postgres &

attempt=1
while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
    if pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
        break
    fi
    sleep "$SLEEP_SECONDS"
    attempt=$((attempt + 1))
done

if ! pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
    echo "SQLBot bundled PostgreSQL did not become ready within the bounded local acceptance window." >&2
    exit 1
fi

nohup "$PM2_CMD_PATH" start "$SSR_PATH/app.js" >/dev/null 2>&1 &
nohup uvicorn main:mcp_app --host 0.0.0.0 --port 8001 >/dev/null 2>&1 &

cd "$APP_PATH"
exec uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers
