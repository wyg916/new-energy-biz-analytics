from datetime import date

import pytest

from app.bootstrap import bootstrap_demo_users
from app.core.database import SessionLocal
from app.data.seed import generate_simulated_data
from app.models.auth import User
from app.models.business import ChargingSession
from app.models.sales import SalesOrder
from app.platform.identity import IdentityContextFactory
from app.platform.scenario_packages import (
    ScenarioPackageError,
    ScenarioPackageLoader,
    ScenarioRegistry,
    ScenarioValidator,
)
from app.query_engines.context import build_query_context
from app.scenarios.charging_ops.package_adapter import install_platform_foundation
from app.scenarios.charging_ops.runtime import resolve_charging_ops_context
from app.scenarios.sales_ops.engine import (
    SalesOpsDeterministicEngine,
    SalesOpsQueryError,
)
from app.scenarios.sales_ops.metrics import SALES_METRICS, SalesOpsMetricService
from app.scenarios.sales_ops.package_adapter import install_sales_ops_foundation
from app.scenarios.sales_ops.runtime import resolve_sales_ops_context
from app.scenarios.sales_ops.seed import generate_sales_orders
from app.platform.query_engine import QueryRequest


@pytest.mark.no_db
def test_sales_ops_package_uses_existing_contract_without_core_special_case() -> None:
    package = ScenarioPackageLoader().load("sales_ops")
    result = ScenarioValidator().validate(package)
    assert result["status"] == "PASSED"
    assert result["validated_files"] == 12
    assert package.manifest["data_classification"] == "simulated"
    assert package.manifest["validation"] == {
        "metric_count": 12,
        "free_sql_allowed": False,
    }
    assert len(package.documents["metrics.yaml"]["metrics"]) == 12
    assert {
        item["code"]
        for item in package.documents["dimensions.yaml"]["dimensions"]
    } == {
        "date",
        "region",
        "channel",
        "product",
        "category",
        "customer_segment",
        "salesperson",
        "organization",
    }


def test_sales_seed_metrics_versions_engine_and_scenario_isolation() -> None:
    bootstrap_demo_users()
    with SessionLocal() as db:
        generate_simulated_data(db, session_count=500)
        charging_count = db.query(ChargingSession).count()
        first = generate_sales_orders(db, order_count=2_000)
        second = generate_sales_orders(db, order_count=2_000)
        assert first.order_count == second.order_count == 2_000
        assert first.order_item_count == second.order_item_count
        assert first.checksum == second.checksum
        assert first.data_classification == "simulated"

        values = SalesOpsMetricService(db).calculate(
            date(2025, 1, 1),
            date(2026, 7, 1),
        )
        assert set(values) == set(SALES_METRICS)
        assert len(values) == 12
        assert values["order_count"] == 2_000
        assert values["sales_revenue"] > 0
        assert values["sales_quantity"] >= values["order_count"]
        assert 0 <= values["refund_rate"] <= 1
        assert 0 <= values["channel_contribution"] <= 1

        analyst = db.query(User).filter_by(username="analyst").one()
        identity = IdentityContextFactory.from_user(analyst)
        charging = install_platform_foundation(db, identity)
        sales = install_sales_ops_foundation(
            db,
            identity,
            expected_order_count=2_000,
        )
        assert charging["metric_count"] == 15
        assert sales["metric_count"] == 12
        assert sales["scenario_status"] == "ACTIVE"
        assert sales["data_classification"] == "simulated"

        _, active_sales = resolve_sales_ops_context(db, analyst)
        query_context = build_query_context(
            db,
            conversation_id="sales-conversation",
            platform_context=active_sales,
        )
        assert query_context.scenario_version == "1.0.0"
        assert query_context.semantic_version == "1.0.0"
        assert "sales_order" in query_context.allowed_relations
        assert "customer_name" not in query_context.allowed_relations["sales_customer"]
        result = SalesOpsDeterministicEngine(db).execute(
            QueryRequest(
                question="2026年6月销售收入、订单数和销售毛利率是多少？",
                identity_context=identity,
                scenario_id="sales_ops",
            ),
            query_context,
        )
        assert result.scenario == "sales_ops"
        assert set(result.rows[0]) == {
            "sales_revenue",
            "order_count",
            "gross_margin",
        }
        assert result.evidence["data_classification"] == "simulated"
        assert result.evidence["dataset_version_id"] == sales["dataset_version_id"]

        with pytest.raises(SalesOpsQueryError) as cross_engine:
            SalesOpsDeterministicEngine(db).execute(
                QueryRequest(
                    question="2026年6月销售收入",
                    identity_context=identity,
                    scenario_id="charging_ops",
                ),
                query_context,
            )
        assert cross_engine.value.code == "SCENARIO_MISMATCH"

        ScenarioRegistry(db).disable(identity, "sales_ops", "1.0.0")
        with pytest.raises(ScenarioPackageError) as disabled:
            resolve_sales_ops_context(db, analyst)
        assert disabled.value.code == "SCENARIO_NOT_ACTIVE"
        _, active_charging = resolve_charging_ops_context(db, analyst)
        assert active_charging.dataset_version_id == charging["dataset_version_id"]
        assert db.query(ChargingSession).count() == charging_count
        assert db.query(SalesOrder).count() == 2_000
