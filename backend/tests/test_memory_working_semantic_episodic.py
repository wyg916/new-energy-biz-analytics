import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.memory.contracts import MemoryStatus
from app.memory.episodic import EpisodicMemoryError, EpisodicMemoryService, EpisodicRun
from app.memory.models import MemoryAuditEvent, MemoryRecord, P2B_MEMORY_TABLES
from app.memory.semantic import SemanticMemoryError, SemanticMemoryService
from app.memory.working import WorkingMemoryError, WorkingMemoryService, WorkingMemoryState
from app.models.auth import User
from app.platform.identity import IdentityContextFactory


pytestmark = pytest.mark.no_db


class FakeRedis:
    def __init__(self, *, fail=False):
        self.data = {}
        self.ttls = {}
        self.fail = fail

    def get(self, key):
        if self.fail:
            raise ConnectionError("redis unavailable")
        return self.data.get(key)

    def set(self, key, value, *, ex):
        if self.fail:
            raise ConnectionError("redis unavailable")
        self.data[key] = value
        self.ttls[key] = ex
        return True

    def delete(self, key):
        if self.fail:
            raise ConnectionError("redis unavailable")
        return int(self.data.pop(key, None) is not None)


@pytest.fixture
def identity(db):
    user = User(
        id=1,
        username="memory-user",
        password_hash="x",
        display_name="Memory User",
        role="analyst",
        region_code=None,
        is_active=True,
    )
    return IdentityContextFactory.from_user(user)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    for table in P2B_MEMORY_TABLES:
        table.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    engine.dispose()


def test_working_memory_round_trip_ttl_and_idempotency(db, identity):
    redis = FakeRedis()
    service = WorkingMemoryService(db, identity, redis_client=redis, ttl_seconds=600)
    state = WorkingMemoryState(
        scenario_id="charging_ops",
        metrics=["revenue"],
        time_range={"relative_days": 30},
        run_id="RUN-WORK-1",
    )
    first = service.save(session_id="CONV-1", state=state)
    second = service.save(session_id="CONV-1", state=state)
    loaded = service.load(scenario_id="charging_ops", session_id="CONV-1")
    assert first.status == "AVAILABLE"
    assert second.idempotent is True
    assert loaded.state.metrics == ["revenue"]
    assert redis.ttls[next(iter(redis.ttls))] == 600


def test_working_memory_multiturn_inheritance(db, identity):
    redis = FakeRedis()
    service = WorkingMemoryService(db, identity, redis_client=redis)
    state = WorkingMemoryState(
        scenario_id="charging_ops",
        metrics=["revenue"],
        time_range={"relative_days": 30},
    )
    service.save(session_id="CONV-2", state=state)
    loaded = service.load(scenario_id="charging_ops", session_id="CONV-2").state
    loaded.filters = [{"field": "region", "operator": "eq", "value": "华东"}]
    loaded.dimensions = ["station"]
    loaded.comparison = {"type": "yoy"}
    loaded.current_intent = "operating_report_generation"
    loaded.state_version += 1
    service.save(session_id="CONV-2", state=loaded)
    final = service.load(scenario_id="charging_ops", session_id="CONV-2").state
    assert final.metrics == ["revenue"]
    assert final.time_range == {"relative_days": 30}
    assert final.filters[0]["value"] == "华东"
    assert final.dimensions == ["station"]
    assert final.comparison == {"type": "yoy"}
    assert final.current_intent == "operating_report_generation"


def test_working_memory_close_removes_state(db, identity):
    redis = FakeRedis()
    service = WorkingMemoryService(db, identity, redis_client=redis)
    service.save(
        session_id="CONV-3",
        state=WorkingMemoryState(scenario_id="charging_ops"),
    )
    result = service.close(scenario_id="charging_ops", session_id="CONV-3")
    assert result.status == "CLEARED"
    assert service.load(scenario_id="charging_ops", session_id="CONV-3").status == "MISS"


def test_working_memory_redis_failure_is_explicit_and_audited(db, identity):
    result = WorkingMemoryService(db, identity, redis_client=FakeRedis(fail=True)).save(
        session_id="CONV-4",
        state=WorkingMemoryState(scenario_id="charging_ops", run_id="RUN-DEGRADED"),
    )
    assert result.status == "DEGRADED"
    audit = db.scalar(select(MemoryAuditEvent).where(MemoryAuditEvent.run_id == "RUN-DEGRADED"))
    assert audit.outcome == "degraded"


def test_working_memory_rejects_secret_fields(db, identity):
    service = WorkingMemoryService(db, identity, redis_client=FakeRedis())
    with pytest.raises(WorkingMemoryError) as error:
        service.save(
            session_id="CONV-5",
            state=WorkingMemoryState(
                scenario_id="charging_ops",
                filters=[{"database_password": "must-not-store"}],
            ),
        )
    assert error.value.code == "SECRET_FIELD_REJECTED"


def test_semantic_unconfirmed_inference_cannot_be_active(db, identity):
    candidate = SemanticMemoryService(db, identity).propose(
        key="answer_style",
        value="简洁",
        scenario_id=None,
        source_type="MODEL_INFERENCE",
        source_id="RUN-S-1",
        explicitly_confirmed=False,
        idempotency_key="semantic-unconfirmed",
        write_reason="模型推断",
    )
    assert candidate.status == MemoryStatus.PENDING_APPROVAL
    assert db.scalars(select(MemoryRecord)).all() == []


def test_semantic_confirm_and_correct_versions(db, identity):
    service = SemanticMemoryService(db, identity)
    first = service.propose(
        key="answer_style",
        value="简洁",
        scenario_id=None,
        source_type="USER_STATEMENT",
        source_id="CONV-S-1",
        explicitly_confirmed=True,
        idempotency_key="semantic-confirm-1",
        write_reason="用户明确说明",
    )
    original = service.confirm(first.candidate_id)
    second = service.propose(
        key="answer_style",
        value="详细",
        scenario_id=None,
        source_type="USER_CORRECTION",
        source_id="CONV-S-2",
        explicitly_confirmed=True,
        idempotency_key="semantic-confirm-2",
        write_reason="用户更正",
    )
    corrected = service.confirm(second.candidate_id)
    db.refresh(original)
    assert original.status == MemoryStatus.SUPERSEDED
    assert corrected.status == MemoryStatus.ACTIVE
    assert corrected.version == 2
    assert corrected.conflict_group == original.conflict_group


@pytest.mark.parametrize("key", ["revenue", "order_amount", "root_cause", "sqlbot_shadow", "password", "token"])
def test_semantic_forbidden_content_is_rejected(db, identity, key):
    with pytest.raises(SemanticMemoryError):
        SemanticMemoryService(db, identity).propose(
            key=key,
            value="unsafe",
            scenario_id="charging_ops",
            source_type="MODEL_INFERENCE",
            source_id="RUN-S-2",
            explicitly_confirmed=False,
            idempotency_key=f"forbidden-{key}",
            write_reason="不应写入",
        )


def episode(**overrides):
    values = {
        "run_id": "RUN-E-1",
        "trace_id": "TRACE-E-1",
        "session_id": "CONV-E-1",
        "raw_question": "查询最近30天收入",
        "normalized_question": "最近30天收入",
        "scenario_id": "charging_ops",
        "dataset_version": "1",
        "semantic_version": "0.1.0",
        "engine": "deterministic",
        "query_plan": {"metric": "revenue"},
        "actual_sql": "SELECT 1",
        "result_summary": {"metric": "revenue", "value": 100},
        "rag_evidence": [],
        "final_answer": "模拟数据收入为100",
        "skill_code": None,
        "steps": [{"step_id": "STEP-1", "status": "completed"}],
        "errors": [],
        "adopted": None,
        "runtime_cost": {"token_usage": 0},
        "latency_ms": 10,
    }
    values.update(overrides)
    return EpisodicRun(**values)


def test_episodic_record_and_replay_by_run_id(db, identity):
    service = EpisodicMemoryService(db, identity)
    saved = service.record_success(episode())
    replayed = service.replay(run_id="RUN-E-1", scenario_id="charging_ops")
    assert saved.run_id == "RUN-E-1"
    assert replayed["result_summary"] == {"metric": "revenue", "value": 100}
    assert len(replayed["result_hash"]) == 64


def test_episodic_idempotent_write(db, identity):
    service = EpisodicMemoryService(db, identity)
    assert service.record_success(episode()).memory_id == service.record_success(episode()).memory_id


def test_episodic_search_is_scenario_scoped(db, identity):
    service = EpisodicMemoryService(db, identity)
    service.record_success(episode())
    assert len(service.search(query="收入", scenario_id="charging_ops")) == 1
    assert service.search(query="收入", scenario_id="sales_ops") == []


def test_episodic_shadow_cannot_become_fact_memory(db, identity):
    with pytest.raises(EpisodicMemoryError) as error:
        EpisodicMemoryService(db, identity).record_success(
            episode(run_id="RUN-E-SHADOW", engine="SQLBOT_SHADOW")
        )
    assert error.value.code == "SQLBOT_SHADOW_FACT_FORBIDDEN"


def test_episodic_full_rows_are_rejected(db, identity):
    with pytest.raises(EpisodicMemoryError) as error:
        EpisodicMemoryService(db, identity).record_success(
            episode(run_id="RUN-E-ROWS", result_summary={"rows": [{"value": 1}]})
        )
    assert error.value.code == "EPISODIC_DETAIL_RESULT_FORBIDDEN"
