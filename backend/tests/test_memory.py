from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.database import SessionLocal
from app.data.seed import generate_simulated_data
from app.models.business import AnalysisRun, SessionState
from app.chatbi.memory import WorkingMemoryStore


def test_session_inheritance_override_isolation_and_run_evidence(client, login):
    with SessionLocal() as db:
        generate_simulated_data(db, session_count=1_000)
    analyst = login()
    first = client.post("/api/v1/chat/query", headers=analyst, json={"question": "2026年6月区域A充电收入环比如何？"})
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["status"] == "completed"
    assert first_body["state_version"] == 1
    conversation_id = first_body["conversation_id"]

    second = client.post("/api/v1/chat/query", headers=analyst, json={"conversation_id": conversation_id, "question": "改看区域B。"})
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["status"] == "completed"
    assert second_body["state_version"] == 2
    assert second_body["query_plan"]["metrics"] == ["charging_revenue"]
    assert second_body["query_plan"]["filters"] == [{"field": "region", "operator": "eq", "value": "区域B"}]
    assert "region" in second_body["query_plan"]["context_resolution"]["overridden_fields"]

    new_session = client.post("/api/v1/chat/query", headers=analyst, json={"question": "其中收入下降最大的3个场站是什么？"})
    assert new_session.json()["status"] == "needs_clarification"
    assert new_session.json()["conversation_id"] != conversation_id

    executive = login("executive", "AlphaExec!2026")
    cross_user = client.post("/api/v1/chat/query", headers=executive, json={"conversation_id": conversation_id, "question": "改看区域C。"})
    assert cross_user.status_code == 403

    cleared = client.delete(f"/api/v1/chat/sessions/{conversation_id}", headers=analyst)
    assert cleared.status_code == 200
    after_clear = client.post("/api/v1/chat/query", headers=analyst, json={"conversation_id": conversation_id, "question": "改看区域C。"})
    assert after_clear.json()["status"] == "needs_clarification"

    with SessionLocal() as db:
        state = db.get(SessionState, conversation_id)
        assert state.status == "cleared"
        runs = db.scalars(select(AnalysisRun).where(AnalysisRun.conversation_id == conversation_id)).all()
        assert len(runs) >= 3
        successful = [run for run in runs if run.status == "succeeded"]
        assert successful and all(run.result_digest and run.answer_digest and run.finished_at for run in successful)


def test_expired_session_is_not_inherited(client, login):
    with SessionLocal() as db:
        generate_simulated_data(db, session_count=100)
    headers = login()
    first = client.post("/api/v1/chat/query", headers=headers, json={"question": "2026年6月区域A充电收入是多少？"}).json()
    with SessionLocal() as db:
        state = db.get(SessionState, first["conversation_id"])
        state.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    followup = client.post("/api/v1/chat/query", headers=headers, json={"conversation_id": first["conversation_id"], "question": "改看区域B。"})
    assert followup.json()["status"] == "needs_clarification"


def test_work_memory_is_structured_versioned_and_released():
    store = WorkingMemoryStore()
    state = store.start("RUN-1", 1, "CONV-1", "digest")
    assert store.snapshot(state.task_id)["current_stage"] == "planning"
    updated = store.update(state.task_id, "executing")
    assert updated.state_version == 2
    store.finish(state.task_id)
    assert store.snapshot(state.task_id) is None
