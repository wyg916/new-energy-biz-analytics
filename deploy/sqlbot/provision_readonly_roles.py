"""Provision two scenario-isolated SQLBot roles from runtime-only secrets.

Required environment variables:
  DATABASE_URL
  SQLBOT_READONLY_CHARGING_PASSWORD
  SQLBOT_READONLY_SALES_PASSWORD

The script never prints connection strings or password values.
"""

import os
import re

import psycopg
from psycopg import sql

ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,62}$")
SCENARIOS = {
    "charging": {
        "role_env": "SQLBOT_READONLY_CHARGING_ROLE",
        "password_env": "SQLBOT_READONLY_CHARGING_PASSWORD",
        "default_role": "sqlbot_charging_readonly",
        "schema": "semantic_sqlbot_charging",
    },
    "sales": {
        "role_env": "SQLBOT_READONLY_SALES_ROLE",
        "password_env": "SQLBOT_READONLY_SALES_PASSWORD",
        "default_role": "sqlbot_sales_readonly",
        "schema": "semantic_sqlbot_sales",
    },
}


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"required CredentialReference env://{name} is unavailable")
    return value


def _provision(connection: psycopg.Connection, item: dict) -> None:
    role = os.getenv(item["role_env"], item["default_role"])
    if not ROLE_PATTERN.fullmatch(role):
        raise RuntimeError("SQLBot role name is invalid")
    password = _required(item["password_env"])
    schema = item["schema"]
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
        if cursor.fetchone() is None:
            cursor.execute(
                sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT")
                .format(sql.Identifier(role))
            )
        cursor.execute(
            sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                sql.Identifier(role),
                sql.Literal(password),
            ),
        )
        cursor.execute(
            sql.SQL("ALTER ROLE {} CONNECTION LIMIT 3").format(sql.Identifier(role))
        )
        cursor.execute(
            sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on")
            .format(sql.Identifier(role))
        )
        cursor.execute(
            sql.SQL("ALTER ROLE {} SET statement_timeout = '3000ms'")
            .format(sql.Identifier(role))
        )
        cursor.execute(
            sql.SQL("ALTER ROLE {} SET lock_timeout = '1000ms'")
            .format(sql.Identifier(role))
        )
        cursor.execute(
            sql.SQL("ALTER ROLE {} SET search_path = {}, pg_temp")
            .format(sql.Identifier(role), sql.Identifier(schema))
        )
        cursor.execute(
            sql.SQL("REVOKE ALL ON SCHEMA public FROM {}")
            .format(sql.Identifier(role))
        )
        other_schema = (
            "semantic_sqlbot_sales"
            if schema == "semantic_sqlbot_charging"
            else "semantic_sqlbot_charging"
        )
        cursor.execute(
            sql.SQL("REVOKE ALL ON SCHEMA {} FROM {}")
            .format(sql.Identifier(other_schema), sql.Identifier(role))
        )
        cursor.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}")
            .format(sql.Identifier(schema), sql.Identifier(role))
        )
        cursor.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO {}")
            .format(sql.Identifier(schema), sql.Identifier(role))
        )


def main() -> None:
    database_url = _required("DATABASE_URL").replace(
        "postgresql+psycopg://",
        "postgresql://",
        1,
    )
    with psycopg.connect(database_url, autocommit=False) as connection:
        for item in SCENARIOS.values():
            _provision(connection, item)
        connection.commit()
    print("SQLBot scenario-isolated readonly roles provisioned; secrets were not displayed.")


if __name__ == "__main__":
    main()
