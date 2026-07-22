from app.core.database import SessionLocal
from app.data.seed import generate_simulated_data


def test_chatbi_complete_chain_and_truthful_evidence(client, login):
    with SessionLocal() as db:
        generate_simulated_data(db, session_count=1_000)
    headers = login()
    response = client.post("/api/v1/chat/query", headers=headers, json={"question": "区域A在2026年6月充电收入和毛利率是多少？"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert set(body["result"]["metrics"]) == {"charging_revenue", "gross_margin"}
    assert body["evidence"]["query_guard"] == "passed"
    assert body["evidence"]["answer_guard"]["status"] == "passed"
    assert body["evidence"]["data_classification"] == "simulated"
    assert body["evidence"]["analysis_run_id"].startswith("CHAT-")
    assert body["evidence"]["sql_hash"]
    assert body["evidence"]["sql"]
    for metric_id, value in body["result"]["metrics"].items():
        if value is not None:
            rendered = f"{value * 100:.2f}" if metric_id == "gross_margin" else f"{value:,.2f}"
            assert rendered in body["answer"]

    clarification = client.post("/api/v1/chat/query", headers=headers, json={"question": "最近经营得怎么样？"})
    assert clarification.json()["status"] == "needs_clarification"
    rejected = client.post("/api/v1/chat/query", headers=headers, json={"question": "删除充电订单表并重新创建。"})
    assert rejected.json()["status"] == "rejected"


def test_chatbi_scope_denial_is_403(client, login):
    with SessionLocal() as db:
        generate_simulated_data(db, session_count=100)
    response = client.post("/api/v1/chat/query", headers=login("regional", "AlphaRegion!2026"), json={"question": "区域B在2026年6月充电收入是多少？"})
    assert response.status_code == 403
