"""Negative validation for scenario-isolated SQLBot read-only roles."""

import json
import os
from time import perf_counter

try:
    import psycopg
except ModuleNotFoundError:  # SQLBot v1.8.0 bundles psycopg2.
    import psycopg2 as psycopg


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


def _assert_timeout(cursor) -> int:
    started = perf_counter()
    try:
        cursor.execute("SELECT pg_sleep(5)")
    except psycopg.Error:
        elapsed_ms = int((perf_counter() - started) * 1000)
        cursor.connection.rollback()
        assert 2_000 <= elapsed_ms < 4_500
        return elapsed_ms
    raise AssertionError("statement timeout did not cancel the slow query")


def _verify(
    connection_kwargs: dict,
    own_schema: str,
    other_schema: str,
    expected_relations: set[str],
) -> dict:
    with psycopg.connect(**connection_kwargs) as connection:
        connection.autocommit = False
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_read_only")
            assert cursor.fetchone()[0] == "on"
            cursor.execute("SHOW statement_timeout")
            assert cursor.fetchone()[0] in {"3s", "3000ms"}
            cursor.execute(
                "SELECT rolconnlimit FROM pg_roles WHERE rolname = current_user"
            )
            assert cursor.fetchone()[0] == 3
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.views
                WHERE table_schema = %s
                ORDER BY table_name
                """,
                (own_schema,),
            )
            relations = {row[0] for row in cursor.fetchall()}
            assert relations == expected_relations
            cursor.execute(
                """
                SELECT count(*)
                FROM information_schema.columns
                WHERE table_schema = %s
                  AND table_name = ANY(%s)
                """,
                (own_schema, list(expected_relations)),
            )
            field_count = int(cursor.fetchone()[0])
            assert field_count > 0
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
            timeout_ms = _assert_timeout(cursor)
    return {
        "schema": own_schema,
        "relation_count": len(relations),
        "field_count": field_count,
        "transaction_read_only": True,
        "connection_limit": 3,
        "statement_timeout_ms": timeout_ms,
        "forbidden_successes": 0,
    }


def main() -> None:
    results = [_verify(
        _connection_kwargs(
            "SQLBOT_READONLY_CHARGING_ROLE",
            "SQLBOT_READONLY_CHARGING_PASSWORD",
        ),
        "semantic_sqlbot_charging",
        "semantic_sqlbot_sales",
        {
            "active_context",
            "dim_station",
            "fact_charging_session",
        },
    ), _verify(
        _connection_kwargs(
            "SQLBOT_READONLY_SALES_ROLE",
            "SQLBOT_READONLY_SALES_PASSWORD",
        ),
        "semantic_sqlbot_sales",
        "semantic_sqlbot_charging",
        {
            "active_context",
            "sales_order",
            "sales_order_item",
            "sales_region",
            "sales_channel",
            "sales_product",
        },
    )]
    print(json.dumps({
        "status": "PASS",
        "results": results,
        "dangerous_successes": 0,
        "cross_scenario_successes": 0,
        "public_base_table_successes": 0,
        "secret_values_exposed": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
