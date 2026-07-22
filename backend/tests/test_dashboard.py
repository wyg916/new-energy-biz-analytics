from app.core.database import SessionLocal
from app.data.seed import generate_simulated_data


def test_dashboard_uses_database_and_enforces_region_scope(client, login):
    with SessionLocal() as db:
        generate_simulated_data(db, session_count=1_000)
    analyst_headers = login()
    summary = client.get("/api/v1/dashboard/summary?start=2025-01-01&end_exclusive=2026-07-01", headers=analyst_headers)
    assert summary.status_code == 200
    body = summary.json()
    assert len(body["metrics"]) == 15
    assert body["metrics"]["charging_revenue"] > 0
    assert body["metadata"]["data_classification"] == "simulated"
    assert body["metadata"]["source"] == "platform_database"
    assert body["metadata"]["batch_id"].startswith("SIM-")
    assert body["metadata"]["analysis_run_id"].startswith("DASH-")

    regional_headers = login("regional", "AlphaRegion!2026")
    stations = client.get("/api/v1/dashboard/stations?start=2025-01-01&end_exclusive=2026-07-01&limit=30", headers=regional_headers)
    assert stations.status_code == 200
    assert stations.json()["rows"]
    assert {row["region_id"] for row in stations.json()["rows"]} == {"R01"}


def test_dashboard_rejects_unapproved_metric(client, login):
    response = client.get("/api/v1/dashboard/trend?metric=repurchase_rate&start=2025-01-01&end_exclusive=2025-02-01", headers=login())
    assert response.status_code == 422
