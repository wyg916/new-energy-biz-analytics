from app.core.database import SessionLocal
from app.data.seed import generate_simulated_data


def test_revenue_analysis_is_fact_backed_and_scope_filtered(client, login):
    with SessionLocal() as db:
        generate_simulated_data(db, session_count=1_000)

    response = client.get(
        "/api/v1/revenue/analysis?start=2026-06-01&end_exclusive=2026-07-01",
        headers=login(),
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["daily_trend"]) == 30
    assert len(body["heatmap"]) == 7 * 24
    assert sum(item["value"] for item in body["daily_trend"]) > 0
    assert sum(item["value"] for item in body["heatmap"]) > 0
    assert body["regions"]
    assert body["cities"]
    assert body["metadata"]["data_classification"] == "simulated"
    assert body["metadata"]["source"] == "platform_database"
    assert body["metadata"]["analysis_run_id"].startswith("REV-")
    summary = client.get(
        "/api/v1/dashboard/summary?start=2026-06-01&end_exclusive=2026-07-01",
        headers=login(),
    ).json()
    assert round(sum(item["value"] for item in body["regions"]), 2) == round(summary["metrics"]["charging_revenue"], 2)

    regional = client.get(
        "/api/v1/revenue/analysis?start=2026-06-01&end_exclusive=2026-07-01",
        headers=login("regional", "AlphaRegion!2026"),
    )
    assert regional.status_code == 200
    assert {item["region_id"] for item in regional.json()["regions"]} == {"R01"}
