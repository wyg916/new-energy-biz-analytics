from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.memory.models import MemoryRecord, P2B_MEMORY_TABLES, SkillExecutionRecord
from app.models.auth import User
from app.platform.identity import IdentityContextFactory
from app.skills.contracts import SkillRequest
from app.skills.definitions import install_initial_skills
from app.skills.runtime import SkillExecutionError, SkillExecutor


pytestmark = pytest.mark.no_db


class FakeAdapter:
    scenario_id = "charging_ops"
    revenue_metric = "charging_revenue"
    order_metric = "order_count"
    gross_profit_metric = "gross_profit"
    efficiency_metric = "station_utilization_rate"
    default_dimension = "station"

    def metrics(self, start, end, metric_ids):
        current = start >= date(2026, 1, 1)
        values = {
            "charging_revenue": 80.0 if current else 100.0,
            "order_count": 90 if current else 100,
            "gross_profit": 30.0 if current else 40.0,
            "station_utilization_rate": 0.5 if current else 0.6,
            "device_online_rate": 0.95 if current else 0.96,
        }
        return {metric: values[metric] for metric in metric_ids}

    def breakdown(self, start, end, metric_id, dimension, limit):
        current = start >= date(2026, 1, 1)
        values = (50.0, 30.0) if current else (55.0, 45.0)
        return (
            {"dimension": "S01", "dimension_name": "场站一", "value": values[0]},
            {"dimension": "S02", "dimension_name": "场站二", "value": values[1]},
        )

    def drivers(self, skill_code, start, end, comparison):
        if skill_code == "revenue_decline_diagnosis":
            return (
                {"driver": "volume_effect", "contribution": -12.0, "classification": "verified_calculation"},
                {"driver": "price_effect", "contribution": -8.0, "classification": "verified_calculation"},
            )
        if skill_code == "gross_profit_change_decomposition":
            return (
                {"driver": "revenue_change", "contribution": -20.0, "classification": "verified_calculation"},
                {"driver": "cost_change", "contribution": 10.0, "classification": "verified_calculation"},
            )
        return ()

    def metric_metadata(self, metric_id):
        return {"metric_id": metric_id, "metric_name": metric_id, "metric_version": "test", "source": "test semantic layer"}

    def report_metrics(self):
        return (
            "charging_revenue",
            "order_count",
            "gross_profit",
            "station_utilization_rate",
            "device_online_rate",
        )


class FakeRegistry:
    def __init__(self, adapter):
        self.adapter = adapter

    def get(self, scenario_id):
        if scenario_id != self.adapter.scenario_id:
            raise ValueError("scenario mismatch")
        return self.adapter


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    for table in P2B_MEMORY_TABLES:
        table.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


@pytest.fixture
def users():
    admin = User(id=1, username="admin", password_hash="x", display_name="Admin", role="analyst_admin", region_code=None, is_active=True)
    analyst = User(id=2, username="analyst", password_hash="x", display_name="Analyst", role="analyst", region_code=None, is_active=True)
    return admin, analyst


def request(skill_code, *, scenario="charging_ops"):
    return SkillRequest(
        skill_code=skill_code,
        scenario_id=scenario,
        start=date(2026, 1, 1),
        end_exclusive=date(2026, 2, 1),
        comparison="yoy",
        session_id="CONV-SKILL",
    )


def install(db, admin):
    return install_initial_skills(db, IdentityContextFactory.from_user(admin))


def test_initial_skill_catalog_has_five_charging_and_three_sales(db, users):
    result = install(db, users[0])
    assert result["skill_count"] == 8
    assert sum(item["scenario_id"] == "charging_ops" for item in result["installed"]) == 5
    assert sum(item["scenario_id"] == "sales_ops" for item in result["installed"]) == 3
    assert all(item["status"] == "ACTIVE" and item["enabled"] for item in result["installed"])


@pytest.mark.parametrize(
    "skill_code",
    [
        "revenue_decline_diagnosis",
        "order_anomaly_analysis",
        "gross_profit_change_decomposition",
        "station_efficiency_diagnosis",
        "operating_report_generation",
    ],
)
def test_five_charging_skills_execute_with_governed_output(db, users, skill_code):
    install(db, users[0])
    output = SkillExecutor(
        db, users[1], adapter_registry=FakeRegistry(FakeAdapter())
    ).execute(request(skill_code))
    assert output.skill_code == skill_code
    assert output.scenario_id == "charging_ops"
    assert output.run_id.startswith("SKRUN-")
    assert output.trace_id.startswith("TRACE-")
    assert output.data_classification == "simulated"
    assert output.evidence
    assert all(step["run_id"] == output.run_id for step in output.steps)
    assert all(item["classification"] == "candidate_cause" for item in output.candidate_causes)
    assert any("不构成因果" in item for item in output.limitations)


@pytest.mark.parametrize(
    "skill_code",
    [
        "revenue_decline_diagnosis",
        "order_anomaly_analysis",
        "gross_profit_change_decomposition",
    ],
)
def test_sales_reuses_three_generic_skill_procedures(db, users, skill_code):
    result = install(db, users[0])
    charging = next(item for item in result["installed"] if item["skill_code"] == skill_code and item["scenario_id"] == "charging_ops")
    sales = next(item for item in result["installed"] if item["skill_code"] == skill_code and item["scenario_id"] == "sales_ops")
    from app.memory.models import SkillDefinition
    assert db.get(SkillDefinition, charging["skill_id"]).procedure_id == db.get(SkillDefinition, sales["skill_id"]).procedure_id


def test_failed_skill_does_not_write_success_episode(db, users):
    install(db, users[0])
    adapter = FakeAdapter()
    adapter.efficiency_metric = None
    executor = SkillExecutor(db, users[1], adapter_registry=FakeRegistry(adapter))
    with pytest.raises(SkillExecutionError):
        executor.execute(request("station_efficiency_diagnosis"))
    execution = db.scalar(select(SkillExecutionRecord))
    assert execution.status == "FAILED"
    assert db.scalars(select(MemoryRecord)).all() == []


def test_skill_success_writes_replayable_episode_not_full_rows(db, users):
    install(db, users[0])
    output = SkillExecutor(
        db, users[1], adapter_registry=FakeRegistry(FakeAdapter())
    ).execute(request("revenue_decline_diagnosis"))
    episode = db.scalar(select(MemoryRecord).where(MemoryRecord.run_id == output.run_id))
    assert episode is not None
    assert "result_summary" in episode.structured_value_json
    assert '"rows"' not in episode.structured_value_json
