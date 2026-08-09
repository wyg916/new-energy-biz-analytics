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
    settings = get_settings()
    scenario_urls = {
        "charging_ops": settings.sqlbot_readonly_charging_database_url,
        "sales_ops": settings.sqlbot_readonly_sales_database_url,
    }
    database_url = scenario_urls.get(request.scenario_id)
    if request.scenario_id not in scenario_urls:
        raise SQLBotEngineError(
            SQLBotErrorCode.POLICY_DENIED,
            "controlled NL2SQL scenario has no readonly execution boundary",
        )
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
                    text("SELECT set_config('statement_timeout', :timeout, true)"),
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
        original = getattr(exc, "orig", exc)
        sqlstate = getattr(original, "sqlstate", None) or "NO_SQLSTATE"
        raise SQLBotEngineError(
            SQLBotErrorCode.UPSTREAM_UNAVAILABLE,
            f"readonly SQL execution failed ({type(exc).__name__}:{sqlstate})",
            retryable=True,
        ) from exc
    if len(rows) > context.max_rows:
        raise SQLBotEngineError(
            SQLBotErrorCode.POLICY_DENIED,
            "readonly execution exceeded the row limit",
        )
    return columns, rows
