from datetime import date

from sqlalchemy import select

from app.core.database import SessionLocal
from app.data.quality import validate_published_batch
from app.data.seed import generate_simulated_data
from app.models.business import ChargingSession, MetricDefinition
from app.services.metric_catalog import METRICS
from app.scenarios.charging_ops.manifest import MANIFEST, MANIFEST_CHECKSUM
from app.services.metrics import MetricService


def test_fixed_seed_data_metrics_and_quality():
    with SessionLocal() as db:
        counts = generate_simulated_data(db, session_count=1_000)
        assert counts["regions"] == 3
        assert counts["cities"] == 6
        assert counts["stations"] == 30
        assert counts["devices"] == 120
        assert counts["users"] == 10_000
        assert counts["dates"] == 546
        assert counts["sessions"] == 1_000
        assert counts["metrics"] == 15
        assert validate_published_batch(db)["status"] == "passed"
        assert db.scalar(select(ChargingSession.session_id).order_by(ChargingSession.session_id)) == "CS-20260722-000000"
        assert len(db.scalars(select(MetricDefinition)).all()) == 15
        assert len(MANIFEST["metric_ids"]) == 15
        assert len(MANIFEST_CHECKSUM) == 64

        values = MetricService(db).compute(list(METRICS), date(2025, 1, 1), date(2026, 7, 1))
        assert set(values) == set(METRICS)
        assert values["charging_revenue"] > 0
        assert values["gross_profit"] == round(values["charging_revenue"] - values["energy_cost"] - values["variable_operating_cost"], 6)
        assert 0 <= values["station_utilization_rate"] <= 1
        assert 0 <= values["device_online_rate"] <= 1
        assert 0 <= values["device_fault_rate"] <= 1


def test_division_metrics_are_null_without_business_data():
    with SessionLocal() as db:
        values = MetricService(db).compute(["gross_margin", "avg_order_energy_kwh", "revenue_per_kwh", "cost_per_kwh", "station_utilization_rate", "device_online_rate"], date(2025, 1, 1), date(2025, 2, 1))
        assert all(value is None for value in values.values())
