from app.core.database import SessionLocal
from app.data.seed import generate_simulated_data


def test_metric_catalog_returns_published_semantic_layer_with_truth_metadata(client, login):
    with SessionLocal() as db:
        generate_simulated_data(db, session_count=100)

    response = client.get(
        "/api/v1/dashboard/metric-catalog?start=2026-01-01&end_exclusive=2026-07-01",
        headers=login(),
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["rows"]) == 15
    assert {row["metric_id"] for row in body["rows"]} >= {
        "charging_revenue",
        "gross_profit",
        "device_online_rate",
    }
    charging_revenue = next(row for row in body["rows"] if row["metric_id"] == "charging_revenue")
    assert charging_revenue["display_name"] == "充电收入"
    assert charging_revenue["version"] == "0.1.0"
    assert charging_revenue["status"] == "approved_for_implementation"
    assert "station" in charging_revenue["allowed_dimensions"]
    assert charging_revenue["business_domain"] == "收入分析"
    assert charging_revenue["definition"] == "已完成充电订单中，电费净额与服务费净额之和。"
    assert charging_revenue["source_tables"] == ["fact_charging_session"]
    assert charging_revenue["supported_grains"] == ["day", "week", "month"]
    assert charging_revenue["metric_type"] == "aggregation"
    assert body["dimension_labels"]["station"] == "场站"
    assert body["scenario"]["scenario_id"] == "charging_ops"
    assert body["scenario"]["version"] == "0.1.0"
    assert body["scenario"]["status"] == "published"
    assert len(body["scenario"]["manifest_checksum"]) == 64
    assert body["metadata"]["scenario_version"] == "0.1.0"
    assert body["metadata"]["data_classification"] == "simulated"
    assert body["metadata"]["source"] == "platform_database"
    assert body["metadata"]["analysis_run_id"].startswith("DASH-")


def test_metric_catalog_requires_authentication(client):
    response = client.get(
        "/api/v1/dashboard/metric-catalog?start=2026-01-01&end_exclusive=2026-07-01"
    )
    assert response.status_code == 401


def test_frontend_context_uses_persisted_published_batch(client, login):
    with SessionLocal() as db:
        generate_simulated_data(db, session_count=100)

    response = client.get("/api/v1/dashboard/context", headers=login())

    assert response.status_code == 200
    body = response.json()
    assert body["default_time_range"] == {
        "start": "2026-01-01",
        "end_exclusive": "2026-07-01",
    }
    assert body["available_time_range"] == {
        "start": "2025-01-01",
        "end_exclusive": "2026-07-01",
    }
    assert body["metric_count"] == 15
    assert body["scenario"]["scenario_id"] == "charging_ops"
    assert body["metadata"]["batch_id"].startswith("SIM-")
    assert body["metadata"]["analysis_run_id"].startswith("CTX-")


def test_frontend_context_fails_closed_without_published_batch(client, login):
    response = client.get("/api/v1/dashboard/context", headers=login())

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PUBLISHED_DATASET_NOT_READY"
