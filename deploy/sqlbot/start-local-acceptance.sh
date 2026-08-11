#!/bin/sh
set -eu

# SQLBot's offline image starts its bundled PostgreSQL asynchronously. On slow local
# Docker Desktop storage, crash recovery can exceed the upstream 120-second
# wait-for-it window. This LOCAL_ACCEPTANCE_ONLY supervisor also stops the
# bundled database cleanly so a normal container restart does not force crash
# recovery on the next boot. It does not change the pinned image or secrets.

SSR_PATH=/opt/sqlbot/g2-ssr
APP_PATH=/opt/sqlbot/app
PM2_CMD_PATH="$SSR_PATH/node_modules/pm2/bin/pm2"
MAX_ATTEMPTS="${SQLBOT_LOCAL_DB_READY_ATTEMPTS:-180}"
SLEEP_SECONDS="${SQLBOT_LOCAL_DB_READY_INTERVAL_SECONDS:-5}"
APP_MODULE="${SQLBOT_APP_MODULE:-sqlbot41_runtime:app}"
MCP_APP_MODULE="${SQLBOT_MCP_APP_MODULE:-sqlbot41_runtime:mcp_app}"
postgres_pid=""
mcp_pid=""
main_pid=""
cleanup_started="false"

cleanup() {
    if [ "$cleanup_started" = "true" ]; then
        return
    fi
    cleanup_started="true"

    if [ -n "$main_pid" ]; then
        kill -TERM "$main_pid" 2>/dev/null || true
    fi
    if [ -n "$mcp_pid" ]; then
        kill -TERM "$mcp_pid" 2>/dev/null || true
    fi
    "$PM2_CMD_PATH" delete all >/dev/null 2>&1 || true

    if pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
        gosu postgres pg_ctl -D "${PGDATA:-/var/lib/postgresql/data}" \
            -m fast -w stop >/dev/null 2>&1 || true
    fi
    if [ -n "$postgres_pid" ]; then
        wait "$postgres_pid" 2>/dev/null || true
    fi
}

on_signal() {
    exit 143
}

trap cleanup EXIT
trap on_signal HUP INT TERM

/usr/local/bin/docker-entrypoint.sh postgres &
postgres_pid=$!

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

cd "$APP_PATH"
"$PM2_CMD_PATH" start "$SSR_PATH/app.js" >/dev/null 2>&1
uvicorn "$APP_MODULE" --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers &
main_pid=$!

attempt=1
while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
    if curl -fsS http://127.0.0.1:8000/ >/dev/null 2>&1; then
        break
    fi
    if ! kill -0 "$main_pid" 2>/dev/null; then
        wait "$main_pid"
        exit $?
    fi
    sleep "$SLEEP_SECONDS"
    attempt=$((attempt + 1))
done
if ! curl -fsS http://127.0.0.1:8000/ >/dev/null 2>&1; then
    echo "SQLBot HTTP did not become ready within the bounded local acceptance window." >&2
    exit 1
fi

uvicorn "$MCP_APP_MODULE" --host 0.0.0.0 --port 8001 &
mcp_pid=$!

set +e
wait "$main_pid"
main_status=$?
set -e
exit "$main_status"
