"""Inject scenario-isolated readonly URLs from an untracked runtime file."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import quote


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("command required")
    path = Path(os.getenv(
        "SQLBOT_PLATFORM_READONLY_CREDENTIAL_FILE",
        "/run/p4-runtime/sqlbot41b_readonly_credentials.json",
    ))
    credentials = json.loads(path.read_text(encoding="utf-8"))
    host = os.getenv("ACCEPTANCE_POSTGRES_HOST", "db")
    port = os.getenv("ACCEPTANCE_POSTGRES_PORT", "5432")
    database = os.getenv("ACCEPTANCE_POSTGRES_DB", "renewable_p5b")
    for scenario, env_name in (
        ("charging_ops", "SQLBOT_READONLY_CHARGING_DATABASE_URL"),
        ("sales_ops", "SQLBOT_READONLY_SALES_DATABASE_URL"),
    ):
        item = credentials[scenario]
        os.environ[env_name] = (
            f"postgresql+psycopg://{quote(item['role'], safe='')}:"
            f"{quote(item['password'], safe='')}@{host}:{port}/{database}"
        )
    os.environ["CHATBI_READONLY_EXECUTION_ENABLED"] = "true"
    os.execvpe(sys.argv[1], sys.argv[1:], os.environ)


if __name__ == "__main__":
    main()
