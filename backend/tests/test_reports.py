from app.core.database import SessionLocal
from app.data.seed import generate_simulated_data


def test_report_draft_and_exports_are_traceable(client, login):
    with SessionLocal() as db:
        generate_simulated_data(db, session_count=1_000)
    headers = login()
    query = "report_type=monthly&start=2026-06-01&end_exclusive=2026-07-01"
    response = client.get(f"/api/v1/reports/draft?{query}", headers=headers)
    assert response.status_code == 200
    report = response.json()
    assert report["metadata"]["data_classification"] == "simulated"
    assert report["metadata"]["status"] == "draft"
    assert report["metadata"]["analysis_run_id"] in report["markdown"]
    assert str(report["metrics"]["charging_revenue"]) in report["markdown"]
    assert str(round(report["metrics"]["gross_margin"] * 100, 4)) in report["markdown"]
    assert "不构成因果结论" in report["markdown"]

    markdown = client.get(f"/api/v1/reports/export?format=markdown&{query}", headers=headers)
    assert markdown.status_code == 200
    assert markdown.headers["x-data-classification"] == "simulated"
    assert markdown.headers["x-analysis-run-id"] in markdown.text
    csv_export = client.get(f"/api/v1/reports/export?format=csv&{query}", headers=headers)
    assert csv_export.status_code == 200
    assert "charging_revenue" in csv_export.content.decode("utf-8-sig")
    assert csv_export.headers["x-analysis-run-id"] in csv_export.content.decode("utf-8-sig")
