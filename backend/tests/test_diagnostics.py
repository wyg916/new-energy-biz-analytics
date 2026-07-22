import pytest

from app.core.database import SessionLocal
from app.data.seed import generate_simulated_data


def test_revenue_and_profit_decomposition_reconcile(client, login):
    with SessionLocal() as db:
        generate_simulated_data(db, session_count=1_000)
    headers = login()
    for metric in ("charging_revenue", "gross_profit"):
        response = client.get(f"/api/v1/diagnostics/decomposition?metric={metric}&start=2026-06-01&end_exclusive=2026-07-01&comparison=mom&limit=5", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["reconciliation"]["bridge_sum"] == pytest.approx(body["reconciliation"]["target_change"], abs=0.02)
        assert abs(body["reconciliation"]["residual"]) <= 0.02
        assert body["station_contributions"]
        assert all("因果" in item["statement"] or "关联" in item["statement"] for item in body["related_factors"])
        assert body["metadata"]["data_classification"] == "simulated"

    anomaly = client.get("/api/v1/diagnostics/anomalies?metric=charging_revenue&start=2026-06-01&end_exclusive=2026-07-01", headers=headers)
    assert anomaly.status_code == 200
    assert anomaly.json()["rule"]["threshold"] == 0.15
    peer = client.get("/api/v1/diagnostics/peer?station_id=S001&metric=gross_margin&start=2026-06-01&end_exclusive=2026-07-01", headers=headers)
    assert peer.status_code == 200
    assert peer.json()["peer_count"] > 0
    chat = client.post("/api/v1/chat/query", headers=headers, json={"question": "2026年6月区域A充电收入为什么环比下降？"})
    assert chat.status_code == 200
    assert chat.json()["chart"]["type"] == "waterfall"
    assert "不构成因果" in chat.json()["answer"]


def test_regional_peer_comparison_rejects_other_region(client, login):
    with SessionLocal() as db:
        generate_simulated_data(db, session_count=100)
    response = client.get("/api/v1/diagnostics/peer?station_id=S011&metric=charging_revenue&start=2026-06-01&end_exclusive=2026-07-01", headers=login("regional", "AlphaRegion!2026"))
    assert response.status_code == 403
