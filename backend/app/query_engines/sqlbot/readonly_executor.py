from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.chatbi.executor import _readonly_engine
from app.core.config import get_settings
from app.platform.query_engine import QueryContext, QueryRequest
from app.query_engines.sqlbot.error_mapper import SQLBotEngineError, SQLBotErrorCode


def execute_generated_readonly(
    sql: str,
    request: QueryRequest,
    context: QueryContext,
) -> tuple[tuple[str, ...], tuple[dict[str, Any], ...]]:
    """Execute policy-approved SQL through the independent PostgreSQL role."""
    del request
    settings = get_settings()
    database_url = settings.chatbi_readonly_database_url
    if not settings.chatbi_readonly_execution_enabled or not database_url:
        raise SQLBotEngineError(
            SQLBotErrorCode.NOT_CONFIGURED,
            "independent readonly PostgreSQL boundary is required",
        )
    if not database_url.startswith("postgresql"):
        raise SQLBotEngineError(
            SQLBotErrorCode.POLICY_DENIED,
            "controlled NL2SQL execution requires PostgreSQL readonly credentials",
        )
    try:
        with _readonly_engine(database_url).connect() as connection:
            with connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                connection.execute(
                    text("SET LOCAL statement_timeout = :timeout"),
                    {"timeout": f"{settings.chatbi_statement_timeout_ms}ms"},
                )
                result = connection.execute(text(sql))
                columns = tuple(result.keys())
                rows = tuple(
                    dict(row)
                    for row in result.mappings().fetchmany(context.max_rows + 1)
                )
    except SQLBotEngineError:
        raise
    except Exception as exc:
        raise SQLBotEngineError(
            SQLBotErrorCode.UPSTREAM_UNAVAILABLE,
            "readonly SQL execution failed",
            retryable=True,
        ) from exc
    if len(rows) > context.max_rows:
        raise SQLBotEngineError(
            SQLBotErrorCode.POLICY_DENIED,
            "readonly execution exceeded the row limit",
        )
    return columns, rows
