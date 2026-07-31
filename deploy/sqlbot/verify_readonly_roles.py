"""Negative validation for scenario-isolated SQLBot read-only roles."""

import os

import psycopg


def _connection_kwargs(role_env: str, password_env: str) -> dict:
    host = os.getenv("SQLBOT_READONLY_DB_HOST", "db")
    port = os.getenv("SQLBOT_READONLY_DB_PORT", "5432")
    database = os.getenv("SQLBOT_READONLY_DB_NAME", "renewable_alpha")
    role = os.getenv(role_env)
    password = os.getenv(password_env)
    if not role or not password:
        raise RuntimeError("readonly role CredentialReference is unavailable")
    return {
        "host": host,
        "port": int(port),
        "dbname": database,
        "user": role,
        "password": password,
    }


def _assert_denied(cursor, statement: str) -> None:
    try:
        cursor.execute(statement)
    except psycopg.Error:
        cursor.connection.rollback()
        return
    raise AssertionError("negative readonly statement unexpectedly succeeded")


def _verify(connection_kwargs: dict, own_schema: str, other_schema: str) -> None:
    with psycopg.connect(**connection_kwargs, autocommit=False) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_read_only")
            assert cursor.fetchone()[0] == "on"
            cursor.execute(f"SELECT 1 FROM {own_schema}.active_context LIMIT 1")
            cursor.fetchone()
            for statement in (
                "CREATE TABLE forbidden_create (id integer)",
                "INSERT INTO public.audit_log "
                "(actor_user_id, action, resource, outcome, detail_json, created_at) "
                "VALUES (NULL, 'x', 'x', 'x', '{}', now())",
                "UPDATE public.audit_log SET outcome = 'x'",
                "DELETE FROM public.audit_log",
                "DROP TABLE public.audit_log",
                "ALTER TABLE public.audit_log ADD COLUMN forbidden integer",
                "COPY public.audit_log FROM STDIN",
                "SELECT * FROM pg_authid",
                f"SELECT * FROM {other_schema}.active_context",
                "SELECT * FROM public.app_user",
            ):
                _assert_denied(cursor, statement)


def main() -> None:
    _verify(
        _connection_kwargs(
            "SQLBOT_READONLY_CHARGING_ROLE",
            "SQLBOT_READONLY_CHARGING_PASSWORD",
        ),
        "semantic_sqlbot_charging",
        "semantic_sqlbot_sales",
    )
    _verify(
        _connection_kwargs(
            "SQLBOT_READONLY_SALES_ROLE",
            "SQLBOT_READONLY_SALES_PASSWORD",
        ),
        "semantic_sqlbot_sales",
        "semantic_sqlbot_charging",
    )
    print("SQLBot readonly negative validation passed; successful forbidden operations: 0.")


if __name__ == "__main__":
    main()
