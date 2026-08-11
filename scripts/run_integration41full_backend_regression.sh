#!/bin/sh
set -eu

: "${INTEGRATION41_REDIS_HOST:?INTEGRATION41_REDIS_HOST is required}"

redis_password="$(cat /run/p4-runtime/redis_password)"
export MEMORY41_TEST_REDIS_URL="redis://:${redis_password}@${INTEGRATION41_REDIS_HOST}:6379/15"
unset redis_password

exec python scripts/p4_entrypoint.py \
  python -m pytest backend/tests -q --tb=short --junitxml=/tmp/backend-full.xml
