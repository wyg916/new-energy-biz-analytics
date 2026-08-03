"""Create or drop one explicitly named isolated P5A PostgreSQL test database."""

from __future__ import annotations

import argparse
import json
import re
from urllib.parse import unquote

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

from app.core.config import get_settings


NAME = re.compile(r"^p5a_targeted_[a-z0-9_]{4,40}$")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "drop"))
    parser.add_argument("database")
    args = parser.parse_args()
    if not NAME.fullmatch(args.database):
        parser.error("database must use the p5a_targeted_ prefix")
    url = make_url(get_settings().database_url)
    with psycopg.connect(
        host=url.host, port=url.port or 5432, dbname="postgres",
        user=url.username, password=unquote(url.password or ""), autocommit=True,
    ) as connection:
        exists = connection.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = %s)",
            (args.database,),
        ).fetchone()[0]
        if args.action == "create":
            if exists:
                raise RuntimeError("isolated test database already exists")
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(args.database)))
        else:
            if not exists:
                raise RuntimeError("isolated test database is absent")
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (args.database,),
            )
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(args.database)))
    print(json.dumps({
        "status": "PASS", "action": args.action, "database": args.database,
        "main_database_modified": False, "secret_value_printed": False,
    }, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({
            "status": "FAIL", "error_type": type(exc).__name__,
            "secret_value_printed": False,
        }, sort_keys=True))
        raise SystemExit(1) from None
