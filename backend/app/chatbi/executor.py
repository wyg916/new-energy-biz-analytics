from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.chatbi.compiler import CompiledQuery
from app.chatbi.guard import guard_compiled_query
from app.core.config import get_settings


@lru_cache(maxsize=4)
def _readonly_engine(database_url: str):
    return create_engine(database_url, pool_pre_ping=True)


def readonly_boundary_status() -> dict:
    settings = get_settings()
    configured = bool(
        settings.chatbi_readonly_execution_enabled
        and settings.chatbi_readonly_database_url
    )
    return {
        "enabled": configured,
        "mode": "independent_postgresql_role" if configured else "guarded_application_session",
        "statement_timeout_ms": settings.chatbi_statement_timeout_ms,
        "credential_exposed": False,
    }


def execute_readonly(db: Session, compiled: CompiledQuery) -> dict[str, float | int | None]:
    guard_compiled_query(compiled)
    settings = get_settings()
    if settings.chatbi_readonly_execution_enabled:
        database_url = settings.chatbi_readonly_database_url
        if not database_url or not database_url.startswith("postgresql"):
            raise RuntimeError("READONLY_DATABASE_NOT_CONFIGURED")
        with _readonly_engine(database_url).connect() as connection:
            with connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                connection.execute(
                    text("SET LOCAL statement_timeout = :timeout"),
                    {"timeout": f"{settings.chatbi_statement_timeout_ms}ms"},
                )
                row = connection.execute(
                    text(compiled.sql), compiled.parameters
                ).mappings().one()
    else:
        row = db.execute(text(compiled.sql), compiled.parameters).mappings().one()
    result = {}
    for metric_id in compiled.metric_ids:
        value = row[metric_id]
        result[metric_id] = None if value is None else int(value) if metric_id in {"completed_order_count", "active_user_count"} else round(float(value), 6)
    return result
