from app.bootstrap import bootstrap_demo_users
from app.core.database import SessionLocal
from app.data.seed import generate_simulated_data
from app.models.auth import AuditLog, User
from app.platform.identity import IdentityContextFactory
from app.scenarios.charging_ops.package_adapter import (
    install_platform_foundation,
)
from app.scenarios.sales_ops.package_adapter import (
    install_sales_ops_foundation,
)
from app.scenarios.sales_ops.seed import generate_sales_orders


def test_chatbi_uses_registry_for_two_isolated_scenarios(
    client,
    login,
) -> None:
    bootstrap_demo_users()
    with SessionLocal() as db:
        generate_simulated_data(db, session_count=500)
        generate_sales_orders(db, order_count=500)
        analyst = db.query(User).filter_by(username="analyst").one()
        identity = IdentityContextFactory.from_user(analyst)
        install_platform_foundation(db, identity)
        install_sales_ops_foundation(
            db,
            identity,
            expected_order_count=500,
        )

    analyst_headers = login()
    catalog = client.get(
        "/api/v1/chat/scenarios",
        headers=analyst_headers,
    )
    assert catalog.status_code == 200
    assert catalog.json()["data_classification"] == "simulated"
    assert {
        (item["scenario_id"], item["status"])
        for item in catalog.json()["scenarios"]
    } == {
        ("charging_ops", "ACTIVE"),
        ("sales_ops", "ACTIVE"),
    }
    scenario_rows = {
        item["scenario_id"]: item
        for item in catalog.json()["scenarios"]
    }
    assert scenario_rows["charging_ops"]["initial_question"]
    assert scenario_rows["charging_ops"]["data_time_range"] == {
        "start": "2025-01-01",
        "end_exclusive": "2026-07-01",
    }
    assert len(scenario_rows["charging_ops"]["suggested_questions"]) == 3
    assert scenario_rows["sales_ops"]["initial_question"]
    assert scenario_rows["sales_ops"]["data_time_range"] == {
        "start": "2025-01-01",
        "end_exclusive": "2026-07-01",
    }
    assert len(scenario_rows["sales_ops"]["suggested_questions"]) == 3

    sales = client.post(
        "/api/v1/chat/query",
        headers=analyst_headers,
        json={
            "scenario_id": "sales_ops",
            "question": "2026年6月销售收入、订单数和销售毛利率是多少？",
        },
    )
    assert sales.status_code == 200
    sales_body = sales.json()
    assert sales_body["status"] == "completed"
    assert sales_body["query_result"]["scenario"] == "sales_ops"
    assert sales_body["query_result"]["engine"] == "deterministic"
    assert sales_body["query_result"]["scenario_version"] == "1.0.0"
    assert sales_body["query_result"]["semantic_version"] == "1.0.1"
    assert sales_body["query_result"]["dataset_version"] == "1"
    assert sales_body["query_result"]["warnings"] == ["SQLBOT_DISABLED"]
    assert set(sales_body["query_result"]["rows"][0]) == {
        "sales_revenue",
        "order_count",
        "gross_margin",
    }
    assert sales_body["evidence"]["data_classification"] == "simulated"
    assert sales_body["evidence"]["answer_guard"]["status"] == "passed"
    assert sales_body["engine_routing"]["mode"] == "SHADOW"
    assert sales_body["engine_routing"]["route_decision"] == (
        "DETERMINISTIC_WITH_SHADOW"
    )
    assert "模拟数据" in sales_body["answer"]

    feedback = client.post(
        "/api/v1/chat/feedback",
        headers=analyst_headers,
        json={
            "conversation_id": sales_body["conversation_id"],
            "run_id": sales_body["query_result"]["run_id"],
            "scenario_id": "sales_ops",
            "rating": "helpful",
        },
    )
    assert feedback.status_code == 200
    assert feedback.json()["status"] == "recorded"
    with SessionLocal() as db:
        audit = db.query(AuditLog).filter_by(
            action="chat.feedback",
            outcome="helpful",
        ).one()
        assert sales_body["query_result"]["run_id"] in audit.resource

    cross_scenario = client.post(
        "/api/v1/chat/query",
        headers=analyst_headers,
        json={
            "conversation_id": sales_body["conversation_id"],
            "scenario_id": "charging_ops",
            "question": "2026年6月充电收入是多少？",
        },
    )
    assert cross_scenario.status_code == 403
    assert cross_scenario.json()["detail"]["code"] == (
        "CONVERSATION_SCENARIO_MISMATCH"
    )

    regional_headers = login("regional", "AlphaRegion!2026")
    cross_user = client.post(
        "/api/v1/chat/query",
        headers=regional_headers,
        json={
            "conversation_id": sales_body["conversation_id"],
            "scenario_id": "sales_ops",
            "question": "2026年6月销售收入是多少？",
        },
    )
    assert cross_user.status_code == 403

    charging = client.post(
        "/api/v1/chat/query",
        headers=analyst_headers,
        json={
            "scenario_id": "charging_ops",
            "question": "2026年6月充电收入是多少？",
        },
    )
    assert charging.status_code == 200
    assert charging.json()["query_result"]["scenario"] == "charging_ops"
    assert charging.json()["conversation_id"] != sales_body["conversation_id"]

    ambiguous = client.post(
        "/api/v1/chat/query",
        headers=analyst_headers,
        json={
            "scenario_id": "sales_ops",
            "question": "2026年6月表现如何？",
        },
    )
    assert ambiguous.status_code == 422
    assert ambiguous.json()["detail"]["code"] == "METRIC_AMBIGUOUS"

    unsupported = client.post(
        "/api/v1/chat/query",
        headers=analyst_headers,
        json={
            "scenario_id": "other_ops",
            "question": "2026年6月收入是多少？",
        },
    )
    assert unsupported.status_code == 404
    assert unsupported.json()["detail"]["code"] == "SCENARIO_NOT_SUPPORTED"

    cleared = client.delete(
        f"/api/v1/chat/sessions/{sales_body['conversation_id']}",
        headers=analyst_headers,
    )
    assert cleared.status_code == 200
