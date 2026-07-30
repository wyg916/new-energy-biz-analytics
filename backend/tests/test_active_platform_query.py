import pytest

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.data.seed import generate_simulated_data
from app.models.auth import User
from app.platform.identity import IdentityContextFactory
from app.platform.query_engine import QueryRequest, SQLBotEngine
from app.platform.scenario_packages import ScenarioRegistry
from app.platform.semantic_registry import ActiveSemanticResolver, SemanticRegistryError
from app.scenarios.charging_ops.package_adapter import install_platform_foundation
from app.scenarios.charging_ops.runtime import DATASET_CODE, SCENARIO_ID


def test_active_versions_route_all_formal_consumers_and_fail_closed(client, login, monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "platform_version_routing_enabled", True)
    with SessionLocal() as db:
        generate_simulated_data(db, session_count=1_000)
        user = db.query(User).filter_by(username="analyst").one()
        identity = IdentityContextFactory.from_user(user)
        with pytest.raises(SemanticRegistryError) as exc:
            ActiveSemanticResolver(db).resolve(
                identity,
                scenario_id=SCENARIO_ID,
                dataset_code=DATASET_CODE,
            )
        assert exc.value.code in {"DATASET_NOT_FOUND", "NO_ACTIVE_VERSION"}
        installed = install_platform_foundation(db, identity)
        assert installed["metric_count"] == 15
        assert installed["scenario_status"] == "ACTIVE"

    headers = login()
    summary = client.get(
        "/api/v1/dashboard/summary?start=2026-01-01&end_exclusive=2026-07-01",
        headers=headers,
    )
    assert summary.status_code == 200
    diagnostic = client.get(
        "/api/v1/diagnostics/decomposition?metric=gross_profit"
        "&start=2026-06-01&end_exclusive=2026-07-01&comparison=mom&limit=5",
        headers=headers,
    )
    assert diagnostic.status_code == 200
    report = client.get(
        "/api/v1/reports/draft?report_type=monthly"
        "&start=2026-06-01&end_exclusive=2026-07-01",
        headers=headers,
    )
    assert report.status_code == 200
    chat = client.post(
        "/api/v1/chat/query",
        headers=headers,
        json={"question": "区域A在2026年6月充电收入和毛利率是多少？"},
    )
    assert chat.status_code == 200
    chat_body = chat.json()
    query_result = chat_body["query_result"]
    required = {
        "engine", "engine_version", "scenario", "scenario_version",
        "semantic_version", "dataset_version", "sql", "columns", "rows",
        "chart_spec", "evidence", "warnings", "execution_time", "trace_id",
        "run_id", "status",
    }
    assert required == set(query_result)
    assert query_result["engine"] == "deterministic"
    assert query_result["warnings"] == []
    assert query_result["rows"]

    metadata_rows = [
        summary.json()["metadata"],
        diagnostic.json()["metadata"],
        report.json()["metadata"],
        chat_body["evidence"],
    ]
    assert {row["dataset_version_id"] for row in metadata_rows} == {
        installed["dataset_version_id"]
    }
    assert {row["semantic_model_version_id"] for row in metadata_rows} == {
        installed["semantic_model_version_id"]
    }
    assert {row["scenario_version"] for row in metadata_rows} == {"1.0.0"}
    assert report.json()["metadata"]["dataset_version"] in report.json()["markdown"]

    with SessionLocal() as db:
        user = db.query(User).filter_by(username="analyst").one()
        identity = IdentityContextFactory.from_user(user)
        ScenarioRegistry(db).disable(identity, SCENARIO_ID, "1.0.0")
    blocked = client.post(
        "/api/v1/chat/query",
        headers=headers,
        json={"question": "2026年6月充电收入是多少？"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "SCENARIO_NOT_ACTIVE"


def test_sqlbot_placeholder_is_disabled_and_not_configured() -> None:
    engine = SQLBotEngine(enabled=False)
    assert engine.health_check() == {
        "engine": "sqlbot",
        "version": "placeholder-0.1",
        "enabled": False,
        "status": "NOT_CONFIGURED",
    }
    with pytest.raises(RuntimeError, match="NOT_CONFIGURED"):
        engine.execute(QueryRequest(
            question="not executed",
            identity_context=None,  # type: ignore[arg-type]
            scenario_id="scenario-a",
        ))
