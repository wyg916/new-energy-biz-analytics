"""Load infrastructure bootstrap files without printing them, then exec a command."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import quote


def _read(name: str) -> str:
    runtime_dir = Path(os.getenv("ACCEPTANCE_RUNTIME_DIR", "/run/p4-runtime"))
    value = (runtime_dir / name).read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"runtime file is empty: {name}")
    return value


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("command required")
    password = quote(_read("postgres_password"), safe="")
    postgres_user = os.getenv("ACCEPTANCE_POSTGRES_USER", "alpha")
    postgres_host = os.getenv("ACCEPTANCE_POSTGRES_HOST", "db")
    postgres_port = os.getenv("ACCEPTANCE_POSTGRES_PORT", "5432")
    postgres_database = os.getenv("ACCEPTANCE_POSTGRES_DB", "renewable_p4")
    database_url = (
        f"postgresql+psycopg://{postgres_user}:{password}"
        f"@{postgres_host}:{postgres_port}/{postgres_database}"
    )
    os.environ["DATABASE_URL"] = database_url
    if os.getenv("ACCEPTANCE_TEST_DATABASE_URL_FROM_RUNTIME", "false").lower() == "true":
        os.environ["TEST_DATABASE_URL"] = database_url
    redis_password = quote(_read("redis_password"), safe="")
    redis_host = os.getenv("ACCEPTANCE_REDIS_HOST", "redis")
    redis_port = os.getenv("ACCEPTANCE_REDIS_PORT", "6379")
    os.environ["REDIS_URL"] = f"redis://:{redis_password}@{redis_host}:{redis_port}/0"
    os.environ["SECRET_KEY"] = _read("application_signing_key")
    os.execvpe(sys.argv[1], sys.argv[1:], os.environ)


if __name__ == "__main__":
    main()
