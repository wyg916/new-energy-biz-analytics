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
    assert body["scenario"]["scenario_id"] == "charging_ops"
    assert body["metadata"]["data_classification"] == "simulated"
    assert body["metadata"]["source"] == "platform_database"
    assert body["metadata"]["analysis_run_id"].startswith("DASH-")


def test_metric_catalog_requires_authentication(client):
    response = client.get(
        "/api/v1/dashboard/metric-catalog?start=2026-01-01&end_exclusive=2026-07-01"
    )
    assert response.status_code == 401
