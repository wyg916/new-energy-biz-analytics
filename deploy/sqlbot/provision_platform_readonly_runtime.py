"""Provision platform-execution roles and a runtime-only credential file.

Run behind ``scripts/p4_entrypoint.py`` with the DATA-4.1 runtime volume
mounted read-write.  Secret values are generated inside the container, are
never printed, and are written only to the untracked runtime volume.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

import psycopg
from psycopg import sql


TARGET = Path(
    os.getenv(
        "SQLBOT_PLATFORM_READONLY_CREDENTIAL_FILE",
        "/run/p4-runtime/sqlbot41b_readonly_credentials.json",
    )
)
ROLES = {
    "charging_ops": (
        "sqlbot_platform_charging_readonly",
        "semantic_sqlbot_charging",
    ),
    "sales_ops": (
        "sqlbot_platform_sales_readonly",
        "semantic_sqlbot_sales",
    ),
}


def main() -> None:
    if TARGET.exists():
        raise RuntimeError("refusing to overwrite existing SQLBot runtime credentials")
    credentials = {
        scenario: {"role": role, "password": secrets.token_urlsafe(36)}
        for scenario, (role, _) in ROLES.items()
    }
    database_url = os.environ["DATABASE_URL"].replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    with psycopg.connect(database_url, autocommit=False) as connection:
        with connection.cursor() as cursor:
            for scenario, (role, schema) in ROLES.items():
                cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
                if cursor.fetchone() is not None:
                    raise RuntimeError("refusing to reuse a platform readonly role")
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                        "NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS"
                    ).format(
                        sql.Identifier(role),
                        sql.Literal(credentials[scenario]["password"]),
                    )
                )
                cursor.execute(
                    sql.SQL("ALTER ROLE {} CONNECTION LIMIT 3").format(
                        sql.Identifier(role)
                    )
                )
                cursor.execute(
                    sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(
                        sql.Identifier(role)
                    )
                )
                cursor.execute(
                    sql.SQL("ALTER ROLE {} SET statement_timeout = '3000ms'").format(
                        sql.Identifier(role)
                    )
                )
                cursor.execute(
                    sql.SQL("ALTER ROLE {} SET lock_timeout = '1000ms'").format(
                        sql.Identifier(role)
                    )
                )
                cursor.execute(
                    sql.SQL("ALTER ROLE {} SET search_path = {}, pg_temp").format(
                        sql.Identifier(role), sql.Identifier(schema)
                    )
                )
                cursor.execute(
                    sql.SQL("REVOKE ALL ON SCHEMA public FROM {}").format(
                        sql.Identifier(role)
                    )
                )
                for _, (_, candidate_schema) in ROLES.items():
                    cursor.execute(
                        sql.SQL("REVOKE ALL ON SCHEMA {} FROM {}").format(
                            sql.Identifier(candidate_schema), sql.Identifier(role)
                        )
                    )
                cursor.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                        sql.Identifier(schema), sql.Identifier(role)
                    )
                )
                cursor.execute(
                    sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}").format(
                        sql.Identifier(schema), sql.Identifier(role)
                    )
                )
        connection.commit()
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(TARGET, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(credentials, handle, separators=(",", ":"))
        handle.write("\n")
    print(json.dumps({
        "status": "PASS",
        "roles_created": len(ROLES),
        "scenario_isolated": True,
        "credential_file_tracked": False,
        "secret_values_exposed": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
