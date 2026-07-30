from datetime import date, datetime

import pytest

from app.chatbi.compiler import CompiledQuery
from app.chatbi.executor import execute_readonly, readonly_boundary_status
from app.core.config import get_settings
from app.core.database import SessionLocal


def _safe_query() -> CompiledQuery:
    return CompiledQuery(
        sql=(
            "SELECT station_id FROM dim_station "
            "WHERE station_id IN (:station_0) LIMIT :limit"
        ),
        parameters={
            "start_ts": datetime(2026, 1, 1),
            "end_ts": datetime(2026, 2, 1),
            "start_date": date(2026, 1, 1),
            "end_date": date(2026, 2, 1),
            "period_seconds": 1,
            "station_0": "S001",
            "limit": 1,
        },
        metric_ids=[],
        station_ids=["S001"],
    )


def test_readonly_boundary_is_default_off_and_never_exposes_credentials(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "chatbi_readonly_execution_enabled", False)
    monkeypatch.setattr(settings, "chatbi_readonly_database_url", None)
    assert readonly_boundary_status() == {
        "enabled": False,
        "mode": "guarded_application_session",
        "statement_timeout_ms": 5000,
        "credential_exposed": False,
    }


def test_enabled_readonly_boundary_fails_closed_without_postgresql_url(
    monkeypatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "chatbi_readonly_execution_enabled", True)
    monkeypatch.setattr(settings, "chatbi_readonly_database_url", None)
    with SessionLocal() as db:
        with pytest.raises(RuntimeError, match="READONLY_DATABASE_NOT_CONFIGURED"):
            execute_readonly(db, _safe_query())
