from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.memory.episodic import EpisodicMemoryService
from app.memory.models import P2B_MEMORY_TABLES
from app.models.auth import User
from app.platform.identity import IdentityContextFactory
from app.skills.contracts import SkillRequest
from app.skills.definitions import install_initial_skills
from app.skills.runtime import SkillExecutor


pytestmark = pytest.mark.no_db


class EvaluationAdapter:
    scenario_id = "charging_ops"
    revenue_metric = "charging_revenue"
    order_metric = "order_count"
    gross_profit_metric = "gross_profit"
    efficiency_metric = "station_utilization_rate"
    default_dimension = "station"

    def metrics(self, start, end, metric_ids):
        del end
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
        del end, metric_id, dimension
        current = start >= date(2026, 1, 1)
        values = (("S01", 50.0), ("S02", 30.0)) if current else (("S01", 55.0), ("S02", 45.0))
        return tuple(
            {"dimension": member, "dimension_name": member, "value": value}
            for member, value in values[:limit]
        )

    def drivers(self, skill_code, start, end, comparison):
        del start, end, comparison
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
        return {
            "metric_id": metric_id,
            "metric_name": metric_id,
            "metric_version": "evaluation",
            "source": "published semantic layer",
        }

    def report_metrics(self):
        return (
            "charging_revenue", "order_count", "gross_profit",
            "station_utilization_rate", "device_online_rate",
        )


class EvaluationRegistry:
    def __init__(self, adapter): self.adapter = adapter
    def get(self, scenario_id):
        if scenario_id != self.adapter.scenario_id:
            raise ValueError("scenario mismatch")
        return self.adapter


@pytest.fixture(scope="module")
def skill_runtime():
    engine = create_engine("sqlite:///:memory:")
    for table in P2B_MEMORY_TABLES:
        table.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        admin = User(id=201, username="eval-admin", password_hash="x", display_name="Admin", role="analyst_admin", region_code=None, is_active=True)
        analyst = User(id=202, username="eval-user", password_hash="x", display_name="Analyst", role="analyst", region_code=None, is_active=True)
        install_initial_skills(db, IdentityContextFactory.from_user(admin))
        yield db, analyst, SkillExecutor(db, analyst, adapter_registry=EvaluationRegistry(EvaluationAdapter()))
    engine.dispose()


def _assert_execution(skill_runtime, skill_code: str, index: int):
    db, analyst, executor = skill_runtime
    comparison = "yoy" if index % 2 else "mom"
    limit = 1 + index % 2
    run_id = f"EVAL-{skill_code}-{index}"
    output = executor.execute(SkillRequest(
        skill_code=skill_code,
        scenario_id="charging_ops",
        start=date(2026, 1 + (index % 5), 1),
        end_exclusive=date(2026, 2 + (index % 5), 1),
        comparison=comparison,
        dimension="station" if index % 2 else "region",
        limit=limit,
        session_id=f"EVAL-SKILL-{index}",
        run_id=run_id,
        trace_id=f"TRACE-{run_id}",
    ))
    assert output.skill_code == skill_code
    assert output.run_id == run_id
    assert output.evidence and output.steps
    assert all(step["run_id"] == run_id for step in output.steps)
    assert all(item["classification"] == "candidate_cause" for item in output.candidate_causes)
    assert any("不构成因果" in limitation for limitation in output.limitations)
    replay = EpisodicMemoryService(db, IdentityContextFactory.from_user(analyst)).replay(
        run_id=run_id, scenario_id="charging_ops"
    )
    assert replay["skill_code"] == skill_code


@pytest.mark.parametrize("index", range(1, 10))
def test_revenue_decline_evaluation_expansion(skill_runtime, index):
    _assert_execution(skill_runtime, "revenue_decline_diagnosis", index)


@pytest.mark.parametrize("index", range(1, 8))
def test_order_anomaly_evaluation_expansion(skill_runtime, index):
    _assert_execution(skill_runtime, "order_anomaly_analysis", index)


@pytest.mark.parametrize("index", range(1, 8))
def test_gross_profit_evaluation_expansion(skill_runtime, index):
    _assert_execution(skill_runtime, "gross_profit_change_decomposition", index)


@pytest.mark.parametrize("index", range(1, 7))
def test_station_efficiency_evaluation_expansion(skill_runtime, index):
    _assert_execution(skill_runtime, "station_efficiency_diagnosis", index)


@pytest.mark.parametrize("index", range(1, 7))
def test_report_generation_evaluation_expansion(skill_runtime, index):
    _assert_execution(skill_runtime, "operating_report_generation", index)
