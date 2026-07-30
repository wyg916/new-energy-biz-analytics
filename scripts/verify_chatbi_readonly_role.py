"""Verify an independent PostgreSQL read-only role in a temporary schema."""

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

INNER_SCRIPT = r'''
import json
import os
import secrets

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

SCHEMA = "p1a_readonly_verify"
ROLE = "p1a_chatbi_readonly_verify"
password = secrets.token_urlsafe(32)
url = make_url(os.environ["DATABASE_URL"])
owner_kwargs = {
    "host": url.host,
    "port": url.port or 5432,
    "dbname": url.database,
    "user": url.username,
    "password": url.password,
}
result = {
    "database": "existing_postgresql_database",
    "isolation": "temporary_schema",
    "schema": SCHEMA,
    "role": ROLE,
    "select_allowed_view": False,
    "base_table_denied": False,
    "insert_denied": False,
    "update_denied": False,
    "delete_denied": False,
    "ddl_denied": False,
    "sensitive_system_object_denied": False,
    "default_transaction_read_only": False,
    "statement_timeout_configured": False,
    "statement_timeout_enforced": False,
    "schema_removed": False,
    "role_removed": False,
    "credential_exposed": False,
}

def denied(connection, statement):
    try:
        with connection.cursor() as cursor:
            cursor.execute(statement)
        connection.commit()
        return False
    except Exception:
        connection.rollback()
        return True

owner = psycopg.connect(**owner_kwargs)
try:
    owner.autocommit = True
    with owner.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = %s)",
            (SCHEMA,),
        )
        schema_exists = cursor.fetchone()[0]
        cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)", (ROLE,))
        role_exists = cursor.fetchone()[0]
        if schema_exists or role_exists:
            raise RuntimeError("refusing to reuse readonly verification objects")
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(SCHEMA)))
        cursor.execute(sql.SQL(
            "CREATE TABLE {}.source_data (id integer PRIMARY KEY, value text NOT NULL)"
        ).format(sql.Identifier(SCHEMA)))
        cursor.execute(
            sql.SQL("INSERT INTO {}.source_data VALUES (1, 'simulated')").format(
                sql.Identifier(SCHEMA)
            )
        )
        cursor.execute(sql.SQL(
            "CREATE VIEW {}.semantic_allowed AS SELECT id, value FROM {}.source_data"
        ).format(sql.Identifier(SCHEMA), sql.Identifier(SCHEMA)))
        cursor.execute(sql.SQL(
            "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE "
            "NOREPLICATION NOBYPASSRLS"
        ).format(sql.Identifier(ROLE), sql.Literal(password)))
        cursor.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                sql.Identifier(SCHEMA), sql.Identifier(ROLE)
            )
        )
        cursor.execute(
            sql.SQL("GRANT SELECT ON {}.semantic_allowed TO {}").format(
                sql.Identifier(SCHEMA), sql.Identifier(ROLE)
            )
        )
        cursor.execute(sql.SQL(
            "ALTER ROLE {} SET default_transaction_read_only = on"
        ).format(sql.Identifier(ROLE)))
        cursor.execute(sql.SQL(
            "ALTER ROLE {} SET statement_timeout = '1500ms'"
        ).format(sql.Identifier(ROLE)))
        cursor.execute(
            sql.SQL("ALTER ROLE {} SET search_path = {}, pg_catalog").format(
                sql.Identifier(ROLE), sql.Identifier(SCHEMA)
            )
        )

    readonly_kwargs = {
        **owner_kwargs,
        "user": ROLE,
        "password": password,
    }
    with psycopg.connect(**readonly_kwargs) as readonly:
        with readonly.cursor() as cursor:
            cursor.execute("SHOW transaction_read_only")
            result["default_transaction_read_only"] = cursor.fetchone()[0] == "on"
            cursor.execute("SHOW statement_timeout")
            result["statement_timeout_configured"] = cursor.fetchone()[0] in {
                "1500ms", "1.5s"
            }
            cursor.execute("SELECT count(*) FROM semantic_allowed")
            result["select_allowed_view"] = cursor.fetchone()[0] == 1
        readonly.rollback()
        result["base_table_denied"] = denied(readonly, "SELECT * FROM source_data")
        result["insert_denied"] = denied(
            readonly, "INSERT INTO semantic_allowed VALUES (2, 'blocked')"
        )
        result["update_denied"] = denied(
            readonly, "UPDATE semantic_allowed SET value = 'blocked' WHERE id = 1"
        )
        result["delete_denied"] = denied(
            readonly, "DELETE FROM semantic_allowed WHERE id = 1"
        )
        result["ddl_denied"] = denied(
            readonly, f"CREATE TABLE {SCHEMA}.blocked_ddl (id integer)"
        )
        result["sensitive_system_object_denied"] = denied(
            readonly, "SELECT rolname, rolpassword FROM pg_authid"
        )
        result["statement_timeout_enforced"] = denied(readonly, "SELECT pg_sleep(3)")
finally:
    try:
        with owner.cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP OWNED BY {}").format(sql.Identifier(ROLE))
            )
            cursor.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(ROLE)))
            cursor.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(SCHEMA))
            )
    finally:
        with owner.cursor() as cursor:
            cursor.execute(
                "SELECT NOT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = %s)",
                (SCHEMA,),
            )
            result["schema_removed"] = cursor.fetchone()[0]
            cursor.execute(
                "SELECT NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)",
                (ROLE,),
            )
            result["role_removed"] = cursor.fetchone()[0]
        owner.close()

checks = [
    "select_allowed_view", "base_table_denied", "insert_denied", "update_denied",
    "delete_denied", "ddl_denied", "sensitive_system_object_denied",
    "default_transaction_read_only", "statement_timeout_configured",
    "statement_timeout_enforced", "schema_removed", "role_removed",
]
result["passed"] = all(result[key] for key in checks)
print(json.dumps(result, ensure_ascii=False))
raise SystemExit(0 if result["passed"] else 1)
'''


def main() -> int:
    process = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", "-"],
        cwd=ROOT,
        input=INNER_SCRIPT,
        text=True,
        encoding="utf-8",
        capture_output=True,
    )
    if process.stdout:
        print(process.stdout, end="")
    if process.stderr:
        print(process.stderr, end="", file=sys.stderr)
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
